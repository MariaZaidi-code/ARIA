"""Live pgvector round trip: ingest -> hybrid search -> re-extract -> delete.

Skipped unless ARIA_RAG_DATABASE_URL points at PostgreSQL with the pgvector
extension (and the local embedding model can load). Uses a throwaway user id
and a synthetic PDF, and removes its vectors at the end.
"""
import os
import uuid

import pytest

if not (os.getenv("ARIA_RAG_DATABASE_URL") or os.getenv("RAG_DATABASE_URL")):
    pytest.skip("ARIA_RAG_DATABASE_URL is not set; live pgvector test skipped.", allow_module_level=True)

pymupdf = pytest.importorskip("pymupdf")

import api.document_routes as document_routes  # noqa: E402
from insight_rag.ingestion import PDFIngestion  # noqa: E402
from insight_rag.storage import RAGMetadataStore, UserPGVectorStore, probe_vector_database  # noqa: E402


def _synthetic_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Synthetic policy: refunds are accepted within 45 days of purchase.", fontsize=11)
    page.insert_text((72, 96), "The warehouse holds 12,500 units of the lantern product line.", fontsize=11)
    doc.save(path)


@pytest.fixture
def live_user(tmp_path, monkeypatch):
    import insight_rag.config as config
    monkeypatch.setattr(config, "RAG_USERS_DIR", tmp_path / "users")
    probe = probe_vector_database()
    if not (probe["reachable"] and probe["pgvector"]):
        pytest.skip(f"pgvector not available: {probe['error']}")
    user_id = f"live-test-{uuid.uuid4().hex[:12]}"
    yield user_id
    for record in RAGMetadataStore(user_id).list_documents():
        UserPGVectorStore(user_id).delete_chunks(record.get("chunk_ids") or [])


def test_live_ingest_search_rechunk_delete(live_user, tmp_path):
    pdf = tmp_path / "policy.pdf"
    _synthetic_pdf(pdf)
    stages = []
    result = PDFIngestion(live_user).ingest_pdf(pdf, original_filename="policy.pdf", progress=stages.append)
    document_id = result["document"]["document_id"]
    assert stages == ["validating", "extracting", "indexing", "saving"]

    adapter = document_routes._CanonicalRAGAdapter(live_user)
    hits = adapter.search_documents("refund window days", k=3)
    assert hits and hits[0]["score_type"] == "hybrid_rrf"
    assert "45 days" in hits[0]["content"] and hits[0]["page_number"] == 1

    rebuilt = PDFIngestion(live_user).rechunk(document_id)
    assert rebuilt["rechunked"] is True

    assert adapter.delete_document(document_id) is True
    assert RAGMetadataStore(live_user).get_document(document_id) is None
    assert not [h for h in adapter.search_documents("refund", k=3) if h["document_id"] == document_id]
