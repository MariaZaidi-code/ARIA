from types import SimpleNamespace

import api.document_routes as document_routes
import insight_rag.storage as rag_storage


class MetadataStore:
    def __init__(self, _user_id):
        self.document = {
            "document_id": "document-1",
            "filename": "quarterly-report.pdf",
            "summary": "Quarterly report Revenue 100 2025",
            "summary_version": 1,
        }

    def get_document(self, document_id):
        return self.document if document_id == "document-1" else None

    def put_document(self, record):
        self.document = dict(record)


def test_summary_upgrades_legacy_raw_excerpt_to_natural_sentence(monkeypatch):
    metadata = MetadataStore("test-user")
    monkeypatch.setattr(rag_storage, "RAGMetadataStore", lambda _user_id: metadata)
    monkeypatch.setattr(
        document_routes,
        "_load_chunks_for",
        lambda *_args: [
            {
                "text": "Quarterly report\nRevenue increased by 12 percent. The company expanded its southern operations.",
                "metadata": {"content_type": "text"},
            },
            {
                "text": "| Region | Revenue |\n| South | 120000 |",
                "metadata": {"content_type": "table"},
            },
        ],
    )
    monkeypatch.setattr("core.config.get_session", lambda _user_id: {"provider": None})
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    response = document_routes.summarize_document("document-1", None, {"user_id": "test-user"})

    assert response["summary_version"] == document_routes.DOCUMENT_SUMMARY_VERSION
    assert response["cached"] is False
    assert "Revenue increased by 12 percent." in response["summary"]
    assert "southern operations." in response["summary"]
    assert "|" not in response["summary"]
    assert metadata.document["summary_version"] == document_routes.DOCUMENT_SUMMARY_VERSION


def test_extractive_summary_reads_sentence_text_from_docx_table_chunks():
    summary = document_routes._extractive_summary(
        [
            {
                "text": (
                    "| Section | Text |\n| --- | --- |\n"
                    "| Paragraph 1 | Revenue increased by 12 percent during the quarter. |\n"
                    "| Paragraph 2 | The company expanded its southern operations. |"
                ),
                "metadata": {
                    "content_type": "table",
                    "filename": "quarterly-report.docx",
                },
            }
        ]
    )

    assert "Revenue increased by 12 percent during the quarter." in summary
    assert "The company expanded its southern operations." in summary


def test_document_assistant_returns_grounded_answer_without_model(monkeypatch):
    class Adapter:
        def __init__(self, _user_id):
            pass

        def search_documents(self, **_kwargs):
            return [{
                "document_id": "doc-1",
                "filename": "quarterly-report.pdf",
                "page_number": 2,
                "content": "Revenue increased by 12 percent during the quarter.",
            }]

    monkeypatch.setattr(document_routes, "_CanonicalRAGAdapter", Adapter)
    monkeypatch.setattr("core.config.get_session", lambda _user_id: {"provider": None})
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    response = document_routes.ask_documents(
        document_routes.DocumentAskRequest(question="How did revenue change?"),
        {"user_id": "test-user"},
    )

    assert response["answer_mode"] == "evidence"
    assert "Revenue increased by 12 percent" in response["answer"]
    assert response["citations"][0]["page_number"] == 2


def test_document_assistant_falls_back_to_chat_when_completion_fails(monkeypatch):
    class Provider:
        def complete(self, *_args, **_kwargs):
            raise RuntimeError("completion unavailable")

        def chat(self, *_args, **_kwargs):
            return "Revenue increased by 12 percent [1]."

    class Adapter:
        def __init__(self, _user_id):
            pass

        def search_documents(self, **_kwargs):
            return [{
                "document_id": "doc-1",
                "filename": "quarterly-report.pdf",
                "page_number": 2,
                "content": "Revenue increased by 12 percent during the quarter.",
            }]

    monkeypatch.setattr(document_routes, "_CanonicalRAGAdapter", Adapter)
    monkeypatch.setattr("core.config.get_session", lambda _user_id: {"provider": Provider()})

    response = document_routes.ask_documents(
        document_routes.DocumentAskRequest(question="How did revenue change?"),
        {"user_id": "test-user"},
    )

    assert response["answer_mode"] == "ai"
    assert response["answer"] == "Revenue increased by 12 percent [1]."


def test_document_assistant_uses_real_local_chunk_fallback(monkeypatch):
    class LocalMetadataStore:
        def __init__(self, _user_id):
            pass

        def list_documents(self):
            return [{"document_id": "doc-1", "filename": "quarterly-report.pdf"}]

        def load_chunks(self, _document_id):
            return [
                SimpleNamespace(
                    page_content="Revenue increased by 12 percent during the quarter.",
                    metadata={"chunk_id": "chunk-1", "page": 2, "content_type": "text"},
                ),
            ]

    def unavailable_vector_store(_user_id):
        raise RuntimeError("Vector search is unavailable")

    monkeypatch.setattr(rag_storage, "RAGMetadataStore", LocalMetadataStore)
    monkeypatch.setattr(rag_storage, "get_user_vector_store", unavailable_vector_store)
    monkeypatch.setattr("core.config.get_session", lambda _user_id: {"provider": None})
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    response = document_routes.ask_documents(
        document_routes.DocumentAskRequest(question="What was the revenue increase?"),
        {"user_id": "test-user"},
    )

    assert response["answer_mode"] == "evidence"
    assert "Revenue increased by 12 percent" in response["answer"]
    assert response["passages"][0]["document_id"] == "doc-1"
    assert response["citations"][0]["page_number"] == 2


def test_document_assistant_still_answers_when_session_lookup_fails(monkeypatch):
    class Adapter:
        def __init__(self, _user_id):
            pass

        def search_documents(self, **_kwargs):
            return [{
                "document_id": "doc-1",
                "filename": "quarterly-report.pdf",
                "page_number": 2,
                "content": "Revenue increased by 12 percent during the quarter.",
            }]

    def unavailable_session(_user_id):
        raise RuntimeError("Session store is unavailable")

    monkeypatch.setattr(document_routes, "_CanonicalRAGAdapter", Adapter)
    monkeypatch.setattr("core.config.get_session", unavailable_session)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    response = document_routes.ask_documents(
        document_routes.DocumentAskRequest(question="How did revenue change?"),
        {"user_id": "test-user"},
    )

    assert response["answer_mode"] == "evidence"
    assert "Revenue increased by 12 percent" in response["answer"]
