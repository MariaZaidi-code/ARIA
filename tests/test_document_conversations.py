"""Document chat sessions: saved scope, listing, reopening, deletion."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

import api.insight_rag_routes as insight_rag_routes
from insight_rag import InsightPDFRAG
from insight_rag.storage import ConversationStore

CID = "conversation-0001"


def document(did, text="Revenue was 100 in 2025.", page=1):
    return Document(page_content=text, metadata={
        "document_id": did, "filename": f"{did}.pdf", "page": page,
        "chunk_id": f"{did}-p{page}", "content_type": "text"})


class Model:
    provider = "cloud"

    def __init__(self):
        self.models = {}
        self.calls = []

    def chat(self, role, messages, **kwargs):
        self.calls.append(role)
        if role == "rag_scope":
            return json.dumps(dict(scope="DOCUMENT", task="DOCUMENT_QA", confidence=0.99,
                                   document_keys=["D1"]))
        if role == "rag_verify":
            return "SUPPORTED"
        return "Revenue was 100 in 2025 [S1]."


@pytest.fixture
def rag(tmp_path, monkeypatch):
    import insight_rag.config as config
    monkeypatch.setattr(config, "RAG_USERS_DIR", tmp_path)
    docs = [document("doc-first"), document("doc-second", "Costs were 40 in 2025.")]
    instance = InsightPDFRAG(insight_agent=SimpleNamespace(llm=Model()), user_id="chat-user")
    for doc in docs:
        did = doc.metadata["document_id"]
        instance.metadata.put_document({"document_id": did, "filename": f"{did}.pdf", "pages": 1})
        instance.metadata.save_chunks(did, [doc])
    seen_scopes = []

    def retrieve(question, ids, **kwargs):
        seen_scopes.append(sorted(ids))
        return [d for d in docs if d.metadata["document_id"] in ids]

    monkeypatch.setattr(instance, "_retrieve", retrieve)
    monkeypatch.setattr("insight_rag.reranker.LocalCrossEncoderReranker._get_model", lambda: None)
    instance.seen_scopes = seen_scopes
    return instance


def test_selection_is_saved_and_reused_by_follow_ups(rag):
    first = rag.chat("What was revenue?", conversation_id=CID, document_ids=["doc-first"])
    assert first["scope_source"] == "request" and first["scope_document_ids"] == ["doc-first"]

    follow_up = rag.chat("And in more detail?", conversation_id=CID, document_ids=None)
    assert follow_up["scope_source"] == "conversation"
    assert follow_up["scope_document_ids"] == ["doc-first"]
    assert all(scope == ["doc-first"] for scope in rag.seen_scopes)

    saved = ConversationStore("chat-user").load(CID)
    assert saved["scope_document_ids"] == ["doc-first"]
    assert saved["title"] == "What was revenue?"


def test_empty_list_explicitly_widens_to_all_documents(rag):
    rag.chat("What was revenue?", conversation_id=CID, document_ids=["doc-first"])
    widened = rag.chat("Compare revenue and costs", conversation_id=CID, document_ids=[])
    assert widened["scope_source"] == "all" and widened["scope_document_ids"] is None
    assert ConversationStore("chat-user").load(CID)["scope_document_ids"] is None


def test_removed_documents_fail_closed_for_saved_scope(rag):
    rag.chat("What was revenue?", conversation_id=CID, document_ids=["doc-first"])
    rag.metadata.remove_document("doc-first")
    with pytest.raises(ValueError, match="removed"):
        rag.chat("And later?", conversation_id=CID)


def test_chat_sources_carry_locations(rag):
    result = rag.chat("What was revenue?", conversation_id=CID, document_ids=["doc-first"])
    assert result["sources"] and result["sources"][0]["location_label"] == "p. 1"
    assert "visualization" in result


def test_conversation_routes_list_get_delete(rag):
    rag.chat("What was revenue?", conversation_id=CID, document_ids=["doc-first"])
    user = {"user_id": "chat-user"}

    listed = insight_rag_routes.list_conversations(limit=10, user=user)["conversations"]
    assert [c["conversation_id"] for c in listed] == [CID]
    assert listed[0]["message_count"] == 2 and listed[0]["scope_document_ids"] == ["doc-first"]

    opened = insight_rag_routes.get_conversation(CID, user=user)["conversation"]
    assert [m["role"] for m in opened["messages"]] == ["user", "assistant"]
    assert "metadata" not in opened["messages"][1]  # internal routing data stays server-side

    assert insight_rag_routes.delete_conversation(CID, user=user)["ok"] is True
    with pytest.raises(HTTPException) as missing:
        insight_rag_routes.get_conversation(CID, user=user)
    assert missing.value.status_code == 404


def test_conversations_are_private_per_user(rag):
    rag.chat("What was revenue?", conversation_id=CID, document_ids=["doc-first"])
    assert insight_rag_routes.list_conversations(limit=10, user={"user_id": "someone-else"})["conversations"] == []
    with pytest.raises(HTTPException) as exc:
        insight_rag_routes.get_conversation(CID, user={"user_id": "someone-else"})
    assert exc.value.status_code == 404


def test_invalid_conversation_id_rejected():
    with pytest.raises(HTTPException) as exc:
        insight_rag_routes.get_conversation("../../etc", user={"user_id": "u"})
    assert exc.value.status_code == 400
