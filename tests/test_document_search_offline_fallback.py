from types import SimpleNamespace

import pandas as pd

import api.document_routes as document_routes
import api.insight_rag_routes as insight_rag_routes
import insight_rag.service as rag_service
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


def test_document_overview_returns_user_document_totals(monkeypatch):
    class MetadataAdapter:
        def __init__(self, _user_id):
            pass

        def list_documents(self):
            return [
                {
                    "filename": "sales-report.pdf",
                    "size_bytes": 2048,
                    "element_count": 12,
                    "created_at": "2025-10-18T12:30:00+00:00",
                    "tags": ["Sales"],
                    "collection": "Quarterly",
                },
                {
                    "filename": "forecast.pdf",
                    "size_bytes": 1024,
                    "element_count": 8,
                    "created_at": "2025-10-19T12:30:00",
                    "tags": ["Sales"],
                },
            ]

    monkeypatch.setattr(document_routes, "_CanonicalRAGAdapter", MetadataAdapter)
    response = document_routes.document_overview_stats({"user_id": "test-user"})

    assert response["overview"] == {
        "total_documents": 2,
        "storage_bytes": 3072,
        "elements_extracted": 20,
        "last_uploaded_at": "2025-10-19T12:30:00",
        "formats": {"pdf": 2},
        "categories": {"Sales": 2, "Quarterly": 1},
    }


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


def test_document_search_fallback_ranks_specific_terms_above_common_terms(monkeypatch):
    class MetadataStore:
        def __init__(self, _user_id):
            pass

        def list_documents(self):
            return [{"document_id": "pdf-test", "filename": "sample.pdf"}]

        def load_chunks(self, _document_id):
            return [
                SimpleNamespace(
                    page_content="Revenue was 1000 dollars.",
                    metadata={"chunk_id": "common", "page": 1},
                ),
                SimpleNamespace(
                    page_content="Revenue was 100 dollars in 2025.",
                    metadata={"chunk_id": "specific", "page": 2},
                ),
            ]

    monkeypatch.setattr(storage, "RAGMetadataStore", MetadataStore)
    adapter = document_routes._CanonicalRAGAdapter.__new__(document_routes._CanonicalRAGAdapter)
    adapter.user_id = "test-user"

    results = adapter._search_local_chunks("revenue 2025", k=2)

    assert results[0]["chunk_id"] == "specific"
    assert results[0]["page_number"] == 2


def test_tabular_ingestion_succeeds_without_pgvector(monkeypatch, tmp_path):
    class MetadataStore:
        def __init__(self):
            self.saved_chunks = []
            self.document = None

        def find_by_sha256(self, _digest):
            return None

        def save_chunks(self, _document_id, chunks):
            self.saved_chunks = chunks

        def put_document(self, record):
            self.document = dict(record)

    metadata = MetadataStore()

    def unavailable_vector_store(_user_id):
        raise RuntimeError("ARIA_RAG_DATABASE_URL is not configured")

    monkeypatch.setattr(rag_service, "UserPGVectorStore", unavailable_vector_store)
    rag = rag_service.InsightPDFRAG.__new__(rag_service.InsightPDFRAG)
    rag.user_id = "test-user"
    rag.metadata = metadata

    result = rag._ingest_tabular(
        pd.DataFrame({"region": ["South", "North"], "revenue": [120000, 90000]}),
        filename="sales.csv",
        table_name="sales.csv",
        table_index=1,
    )

    assert result["ok"] is True
    assert result["document"]["vector_indexed"] is False
    assert result["document"]["chunk_ids"] == []
    assert metadata.document["document_id"] == result["document"]["document_id"]
    assert metadata.saved_chunks


def test_cloud_document_chat_keeps_the_selected_provider_model(monkeypatch, tmp_path):
    class CloudProvider:
        provider = "cloud"

        def __init__(self):
            self.models = {
                "sql": "groq-chat-model",
                "story": "groq-chat-model",
            }

        def model_for(self, role):
            return self.models.get(role)

    provider = CloudProvider()
    monkeypatch.setattr("core.config.get_session", lambda _user_id: {
        "provider_name": "cloud",
        "api_keys": {},
    })
    monkeypatch.setattr("core.config.resolve_provider_key", lambda *_args: "test-key")
    monkeypatch.setattr(insight_rag_routes, "create_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(
        insight_rag_routes,
        "InsightAgent",
        lambda provider: SimpleNamespace(llm=provider),
    )
    monkeypatch.setattr(storage, "user_dir", lambda user_id: tmp_path / str(user_id))

    rag = insight_rag_routes._capability(328)

    assert rag.llm.model_for("rag") == "groq-chat-model"
    assert rag.llm.model_for("rag_rewrite") == "groq-chat-model"
    assert rag.llm.model_for("rag_verify") == "groq-chat-model"
    assert rag.llm.model_for("rag_plan") == "groq-chat-model"
