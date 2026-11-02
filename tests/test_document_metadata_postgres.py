"""Document metadata in PostgreSQL: migrations, CRUD, manifest import, sharing.

The backend-selection tests always run. The database tests need a disposable
PostgreSQL (pgvector is NOT required for metadata) and are skipped unless
ARIA_RAG_TEST_DATABASE_URL is set, e.g.
postgresql://user@127.0.0.1:55432/aria_rag_test. Rows are written under
throwaway user keys and removed afterwards.
"""
import json
import os
import uuid

import pytest

import insight_rag.config as config
import insight_rag.metadata_db as metadata_db
from insight_rag import storage
from insight_rag.storage import RAGMetadataStore

TEST_URL = os.getenv("ARIA_RAG_TEST_DATABASE_URL", "").strip()
needs_db = pytest.mark.skipif(not TEST_URL, reason="ARIA_RAG_TEST_DATABASE_URL is not set")


@pytest.fixture
def users_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAG_USERS_DIR", tmp_path / "users")
    return tmp_path / "users"


@pytest.mark.parametrize("backend,url,expected", [
    ("auto", "", "file"),
    ("auto", "postgresql://x@h/db", "postgres"),
    ("file", "postgresql://x@h/db", "file"),
    ("postgres", "postgresql://x@h/db", "postgres"),
])
def test_backend_selection(monkeypatch, backend, url, expected):
    monkeypatch.setattr(config, "RAG_METADATA_BACKEND", backend)
    monkeypatch.setattr(config, "RAG_DATABASE_URL", url)
    assert storage.metadata_backend_name() == expected


def test_config_rejects_unknown_or_unusable_backend(monkeypatch):
    monkeypatch.setattr(config, "RAG_METADATA_BACKEND", "mongo")
    with pytest.raises(RuntimeError, match="ARIA_RAG_METADATA_BACKEND"):
        config.validate_rag_config()
    monkeypatch.setattr(config, "RAG_METADATA_BACKEND", "postgres")
    monkeypatch.setattr(config, "RAG_DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="requires ARIA_RAG_DATABASE_URL"):
        config.validate_rag_config()


def test_file_backend_share_lookups(users_dir, monkeypatch):
    monkeypatch.setattr(config, "RAG_METADATA_BACKEND", "file")
    owner = RAGMetadataStore("file-owner")
    owner.put_document({"document_id": "doc-file-1", "filename": "a.pdf",
                        "share_token": "tok-file", "shared_with": ["bob"]})
    (users_dir / "broken-user").mkdir(parents=True)
    (users_dir / "broken-user" / "manifest.json").write_text("{not json")
    owner_dir, record = storage.find_shared_document("tok-file")
    assert owner_dir == owner.root and record["document_id"] == "doc-file-1"
    assert [d["document_id"] for d in storage.documents_shared_with("bob")] == ["doc-file-1"]
    assert storage.find_shared_document("missing") is None


# ── Live PostgreSQL ──────────────────────────────────────────────────────

@pytest.fixture
def pg(users_dir, monkeypatch):
    monkeypatch.setattr(config, "RAG_DATABASE_URL", TEST_URL)
    monkeypatch.setattr(config, "RAG_METADATA_BACKEND", "postgres")
    created: list[str] = []

    def make_user():
        user_id = f"meta-test-{uuid.uuid4().hex[:12]}"
        created.append(config.user_key(user_id))
        return user_id

    yield make_user
    from sqlalchemy import text
    engine = metadata_db._engine(TEST_URL)
    with engine.begin() as conn:
        for key in created:
            conn.execute(text("DELETE FROM aria_rag_documents WHERE user_key = :u"), {"u": key})
            conn.execute(text("DELETE FROM aria_rag_manifest_imports WHERE user_key = :u"), {"u": key})


def _record(document_id, **extra):
    return {"document_id": document_id, "filename": f"{document_id}.pdf", "sha256": "0" * 64,
            "status": "ready", "created_at": "2026-10-01T10:00:00+00:00", **extra}


@needs_db
def test_migrations_are_versioned_and_idempotent(pg):
    from sqlalchemy import text
    engine = metadata_db._engine(TEST_URL)
    assert metadata_db.apply_migrations(engine) == []
    with engine.connect() as conn:
        versions = [row[0] for row in conn.execute(text("SELECT version FROM aria_rag_schema_migrations"))]
        columns = {row[0] for row in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'aria_rag_documents'"))}
    assert versions == [version for version, _, _ in metadata_db.MIGRATIONS]
    assert {"user_key", "document_id", "sha256", "status", "share_token", "record"} <= columns


@needs_db
def test_crud_ordering_dedup_and_user_isolation(pg):
    alice, bob = RAGMetadataStore(pg()), RAGMetadataStore(pg())
    assert alice.backend == "postgres"
    alice.put_document(_record("doc-old", created_at="2026-01-01T00:00:00+00:00", sha256="a" * 64))
    alice.put_document(_record("doc-new", created_at="2026-06-01T00:00:00+00:00", sha256="b" * 64,
                               ingestion_quality={"grade": "good"}, note="nul\u0000char"))
    assert [d["document_id"] for d in alice.list_documents()] == ["doc-new", "doc-old"]
    assert alice.get_document("doc-new")["ingestion_quality"] == {"grade": "good"}
    assert alice.get_document("doc-new")["note"] == "nulchar"
    assert alice.find_by_sha256("a" * 64)["document_id"] == "doc-old"
    # Another user never sees (or dedups against) alice's documents.
    assert bob.list_documents() == [] and bob.find_by_sha256("a" * 64) is None

    updated = alice.get_document("doc-old")
    updated.update(status="failed", error_message="Index repair failed")
    alice.put_document(updated)
    assert alice.get_document("doc-old")["status"] == "failed"
    assert len(alice.list_documents()) == 2

    assert alice.remove_document("doc-old")["document_id"] == "doc-old"
    assert alice.remove_document("doc-old") is None
    assert [d["document_id"] for d in alice.list_documents()] == ["doc-new"]

    alice.save_manifest({"documents": {"doc-x": _record("doc-x")}})
    assert list(alice.load_manifest()["documents"]) == ["doc-x"]


@needs_db
def test_legacy_manifest_is_imported_once_and_kept_as_backup(pg):
    user_id = pg()
    root = config.user_dir(user_id)
    manifest = {"documents": {"doc-a": _record("doc-a"), "doc-b": _record("doc-b", status="failed")}}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    store = RAGMetadataStore(user_id)
    assert {d["document_id"] for d in store.list_documents()} == {"doc-a", "doc-b"}
    assert not (root / "manifest.json").exists()
    assert json.loads((root / "manifest.json.migrated").read_text(encoding="utf-8")) == manifest

    # A stale manifest reappearing later never overwrites newer database rows.
    store.put_document(_record("doc-a", status="ready", summary="newer"))
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    metadata_db._IMPORTED.clear()
    again = RAGMetadataStore(user_id)
    assert again.get_document("doc-a")["summary"] == "newer"
    assert len(again.list_documents()) == 2


@needs_db
def test_corrupt_manifest_fails_loudly_and_is_left_in_place(pg):
    user_id = pg()
    root = config.user_dir(user_id)
    (root / "manifest.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="could not be read"):
        RAGMetadataStore(user_id)
    assert (root / "manifest.json").read_text(encoding="utf-8") == "{broken"


@needs_db
def test_share_lookups_span_users(pg):
    owner_id = pg()
    owner = RAGMetadataStore(owner_id)
    token = uuid.uuid4().hex
    owner.put_document(_record("doc-shared", share_token=token, shared_with=["carol"]))
    owner.put_document(_record("doc-private"))

    owner_dir, record = storage.find_shared_document(token)
    assert owner_dir == owner.root and record["document_id"] == "doc-shared"
    assert storage.find_shared_document(uuid.uuid4().hex) is None
    assert "doc-shared" in {d["document_id"] for d in storage.documents_shared_with("carol")}
    assert "doc-private" not in {d["document_id"] for d in storage.documents_shared_with("carol")}


@needs_db
def test_pdf_ingestion_and_rollback_use_postgres_metadata(pg, monkeypatch, tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from insight_rag import ingestion

    class FakeVectors:
        added, deleted, fail = [], [], False

        def __init__(self, _user_id):
            pass

        def add_documents(self, documents):
            if FakeVectors.fail:
                raise ConnectionError("vector index down")
            FakeVectors.added.extend(d.metadata["chunk_id"] for d in documents)

        def delete_chunks(self, ids):
            FakeVectors.deleted.extend(ids)

    monkeypatch.setattr(ingestion, "UserPGVectorStore", FakeVectors)
    pdf = tmp_path / "policy.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Synthetic policy: refunds are accepted within 45 days of purchase.")
    page.insert_text((72, 96), "The warehouse holds 12,500 units of the lantern product line.")
    page.insert_text((72, 120), "Shipping to remote regions takes between five and nine business days.")
    doc.save(pdf)

    user_id = pg()
    first = ingestion.PDFIngestion(user_id).ingest_pdf(pdf, original_filename="policy.pdf")
    document_id = first["document"]["document_id"]
    stored = RAGMetadataStore(user_id).get_document(document_id)
    assert stored["status"] == "ready" and stored["chunk_ids"] == FakeVectors.added
    # Duplicate detection is a sha256 lookup against the metadata table.
    again = ingestion.PDFIngestion(user_id).ingest_pdf(pdf, original_filename="policy.pdf")
    assert again["duplicate"] is True and again["document"]["document_id"] == document_id

    other = pg()
    FakeVectors.fail = True
    with pytest.raises(ConnectionError):
        ingestion.PDFIngestion(other).ingest_pdf(pdf, original_filename="policy.pdf")
    assert RAGMetadataStore(other).list_documents() == []
    assert not list((config.user_dir(other) / "chunks").glob("*.json"))
