from types import SimpleNamespace

import api.document_routes as document_routes
import insight_rag.storage as storage


def test_document_list_uses_element_count_not_character_count(monkeypatch):
    class MetadataAdapter:
        def __init__(self, _user_id):
            pass

        def list_documents(self):
            return [{
                "document_id": "pdf-test",
                "filename": "sample.pdf",
                "size_bytes": 4968,
                "pages": 2,
                "element_count": 38,
                "text_chars": 3077,
                "total_chunks": 6,
                "tables": 3,
                "status": "ready",
            }]

    monkeypatch.setattr(document_routes, "_CanonicalRAGAdapter", MetadataAdapter)
    response = document_routes.list_documents(
        None, {"user_id": "test-user"}, status=None, limit=50
    )

    assert response["documents"][0]["element_count"] == 38
    assert response["documents"][0]["page_count"] == 2
    assert response["documents"][0]["chunk_count"] == 6
    assert response["documents"][0]["table_count"] == 3


def test_document_search_uses_saved_chunks_when_pgvector_is_unavailable(monkeypatch):
    chunks = {
        "pdf-test": [
            SimpleNamespace(
                page_content="Search test phrase: Juniper Lantern. September net sales were $491,200.",
                metadata={"chunk_id": "chunk-1", "page": 2, "section": "Highlights"},
            ),
            SimpleNamespace(
                page_content="The West region recorded net sales of $514,800.",
                metadata={"chunk_id": "chunk-2", "page": 2},
            ),
        ],
    }

    class MetadataStore:
        def __init__(self, _user_id):
            pass

        def list_documents(self):
            return [{"document_id": "pdf-test", "filename": "sample.pdf"}]

        def load_chunks(self, document_id):
            return chunks.get(document_id, [])

    def unavailable_vector_store(_user_id):
        raise RuntimeError("PGVector is not configured")

    monkeypatch.setattr(storage, "RAGMetadataStore", MetadataStore)
    adapter = document_routes._CanonicalRAGAdapter.__new__(document_routes._CanonicalRAGAdapter)
    adapter.user_id = "test-user"
    adapter._get_vector_store = unavailable_vector_store

    results = adapter.search_documents("Juniper Lantern", k=5)

    assert results[0]["document_id"] == "pdf-test"
    assert results[0]["filename"] == "sample.pdf"
    assert results[0]["chunk_id"] == "chunk-1"
    assert "Juniper Lantern" in results[0]["content"]
    assert results[0]["score"] > 0
