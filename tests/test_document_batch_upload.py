"""Multi-file upload: per-file validation, stage progress, failure isolation."""
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

import api.document_routes as document_routes
import api.insight_rag_routes as insight_rag_routes
from insight_rag.jobs import STAGES, UploadJobRegistry

USER = {"user_id": "batch-user"}


def _upload(name, content=b"%PDF-1.4 synthetic"):
    return UploadFile(filename=name, file=BytesIO(content))


@pytest.fixture
def registry(monkeypatch):
    jobs = UploadJobRegistry(workers=2)
    monkeypatch.setattr(insight_rag_routes, "UPLOAD_JOBS", jobs)
    monkeypatch.setattr("insight_rag.jobs.UPLOAD_JOBS", jobs)
    return jobs


def _wait_all(jobs, response):
    for job in response["jobs"]:
        jobs.wait(job["job_id"], timeout=10)
    return {job["filename"]: jobs.get(USER["user_id"], job["job_id"]) for job in response["jobs"]}


def test_batch_reports_each_file_independently(registry, monkeypatch):
    seen_paths, stages = [], []

    def fake_ingest(user_id, temp_path, filename, extension, written, progress=None):
        seen_paths.append(temp_path)
        assert temp_path.exists() and temp_path.read_bytes().startswith(b"%PDF")
        for stage in ("validating", "extracting", "indexing", "saving"):
            progress(stage)
            stages.append((filename, stage))
        if filename == "broken.pdf":
            raise ValueError("The uploaded file does not appear to be a valid PDF.")
        return {"ok": True, "duplicate": False,
                "document": {"document_id": f"id-{filename}", "filename": filename}}

    monkeypatch.setattr(insight_rag_routes, "_ingest_spooled", fake_ingest)
    response = insight_rag_routes.upload_documents_batch(
        files=[_upload("a.pdf"), _upload("broken.pdf"), _upload("notes.txt"), _upload("empty.pdf", b"")],
        user=USER,
    )

    assert response["ok"] is True and len(response["jobs"]) == 4
    assert len({job["batch_id"] for job in response["jobs"]}) == 1
    final = _wait_all(registry, response)
    assert final["a.pdf"]["status"] == "ready" and final["a.pdf"]["progress"] == 100
    assert final["a.pdf"]["document"]["document_id"] == "id-a.pdf"
    assert final["broken.pdf"]["status"] == "failed"
    assert "valid PDF" in final["broken.pdf"]["error"]
    # Rejected before ingestion: never reaches the pipeline.
    assert final["notes.txt"]["status"] == "failed" and "PDF, CSV, XLSX" in final["notes.txt"]["error"]
    assert final["empty.pdf"]["status"] == "failed" and "empty" in final["empty.pdf"]["error"]
    assert {name for name, _ in stages} == {"a.pdf", "broken.pdf"}
    # Temp files are cleaned up whether ingestion succeeded or failed.
    assert all(not Path(path).exists() for path in seen_paths)


def test_unexpected_errors_are_sanitised(registry, monkeypatch):
    def explode(*_args, **_kwargs):
        raise OSError(r"C:\secret\path\db password=hunter2")

    monkeypatch.setattr(insight_rag_routes, "_ingest_spooled", explode)
    response = insight_rag_routes.upload_documents_batch(files=[_upload("a.pdf")], user=USER)
    job = _wait_all(registry, response)["a.pdf"]
    assert job["status"] == "failed"
    assert "hunter2" not in job["error"] and "secret" not in job["error"]


def test_batch_size_limit(registry):
    files = [_upload(f"f{i}.pdf") for i in range(insight_rag_routes.MAX_BATCH_FILES + 1)]
    with pytest.raises(HTTPException) as exc:
        insight_rag_routes.upload_documents_batch(files=files, user=USER)
    assert exc.value.status_code == 400


def test_jobs_are_isolated_per_user_and_listed_by_batch(registry):
    mine = registry.create("u1", filename="a.pdf", size_bytes=1, batch_id="b1")
    registry.create("u1", filename="b.pdf", size_bytes=1, batch_id="b2")
    registry.create("u2", filename="c.pdf", size_bytes=1, batch_id="b1")

    listed = document_routes.list_upload_jobs(batch_id="b1", user={"user_id": "u1"})["jobs"]
    assert [job["job_id"] for job in listed] == [mine["job_id"]]
    with pytest.raises(HTTPException) as exc:
        document_routes.get_upload_job(mine["job_id"], user={"user_id": "u2"})
    assert exc.value.status_code == 404


def test_stage_updates_map_to_progress(registry):
    job = registry.create("u1", filename="a.pdf", size_bytes=1)
    updated = registry.update("u1", job["job_id"], stage="indexing")
    assert updated["status"] == "processing" and updated["progress"] == STAGES["indexing"]


def test_single_upload_route_still_returns_the_document(monkeypatch):
    monkeypatch.setattr(insight_rag_routes, "_ingest_spooled",
                        lambda *a, **k: {"ok": True, "duplicate": False, "document": {"document_id": "d1"}})
    result = insight_rag_routes.upload_pdf(_upload("a.pdf"), USER)
    assert result["document"]["document_id"] == "d1"


def test_pdf_ingestion_reports_stages_in_order(tmp_path, monkeypatch):
    import insight_rag.config as config
    import insight_rag.ingestion as ingestion
    from langchain_core.documents import Document

    monkeypatch.setattr(config, "RAG_USERS_DIR", tmp_path)
    monkeypatch.setattr(ingestion, "extract_pdf_documents", lambda *_a, **_k: (
        [Document(page_content="Revenue was 10.", metadata={"chunk_id": "c1", "page": 1})],
        {"pages": 1, "tables": 0, "text_chunks": 1, "table_chunks": 0, "total_chunks": 1}))

    class Store:
        def __init__(self, _user):
            pass

        def add_documents(self, docs):
            return [d.metadata["chunk_id"] for d in docs]

        def delete_chunks(self, _ids):
            pass

    monkeypatch.setattr(ingestion, "UserPGVectorStore", Store)
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic")
    stages = []
    result = ingestion.PDFIngestion("stage-user").ingest_pdf(
        pdf, original_filename="in.pdf", progress=stages.append)
    assert stages == ["validating", "extracting", "indexing", "saving"]
    assert result["document"]["rag_schema_version"] == ingestion.RAG_SCHEMA_VERSION


def test_health_reports_unreachable_database(monkeypatch):
    monkeypatch.setattr(insight_rag_routes, "RAG_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    monkeypatch.setattr(insight_rag_routes, "probe_vector_database",
                        lambda: {"reachable": False, "pgvector": False, "error": "OperationalError"})
    monkeypatch.setattr("core.config.get_session", lambda _u: {"provider_name": "local"})
    monkeypatch.setattr(insight_rag_routes, "validate_rag_config", lambda: None)

    class Meta:
        def __init__(self, _u):
            pass

        def list_documents(self):
            return []

    monkeypatch.setattr(insight_rag_routes, "RAGMetadataStore", Meta)
    health = insight_rag_routes.pdf_rag_health(USER)
    assert health["database_configured"] is True
    assert health["database_reachable"] is False and health["ready"] is False
    assert "p@" not in str(health)
