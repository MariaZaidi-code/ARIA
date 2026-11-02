"""Document preview quality: clean fallback summaries and honest extracted metrics."""
import api.document_routes as document_routes


def _docx_table(rows):
    lines = ["| Section | Text |", "| --- | --- |"]
    lines += [f"| Paragraph {i} | {text} |" for i, text in enumerate(rows, start=1)]
    return {"text": "\n".join(lines),
            "metadata": {"content_type": "table", "filename": "REPORT.docx", "table_summary": False}}


def test_headings_are_not_glued_onto_sentences():
    chunk = _docx_table([
        "Seven AI agent architectures for one food-delivery scenario",
        "All data used in this project is simulated (fictional city, roads, orders and prices).",
        "1. Objective",
        "The assignment asks how changing an agent's architecture changes the way it uses information.",
    ])
    summary = document_routes._extractive_summary([chunk])
    assert summary.startswith("All data used in this project is simulated")
    assert "scenario All" not in summary and "Objective The" not in summary


def test_metrics_ignore_generated_summary_and_ranges(monkeypatch):
    chunks = [
        {"text": "Table summary for REPORT.docx: 129 rows, 2 columns.",
         "metadata": {"content_type": "table", "table_summary": True}},
        _docx_table([
            "Orders were seen at 17-50 minutes after dispatch.",
            "Training: 1,500 episodes per agent.",
            "Average delivery time - 23.5",
            "Version 2: 3 builds",
        ]),
    ]
    import insight_rag.storage as storage
    monkeypatch.setattr(storage, "RAGMetadataStore",
                        lambda _uid: type("M", (), {"get_document": lambda self, _id: {"document_id": _id}})())
    monkeypatch.setattr(document_routes, "_load_chunks_for", lambda _uid, _id: chunks)

    result = document_routes.document_dashboard("doc-quality-1", user={"user_id": "u1"})
    metrics = {m["label"]: m["value"] for m in result["metrics"]}
    assert metrics == {"Training": 1500.0, "Average delivery time": 23.5}


def test_outdated_summary_is_hidden_so_the_page_regenerates_it():
    current = {"summary": "Fresh.", "summary_version": document_routes.DOCUMENT_SUMMARY_VERSION}
    stale = {"summary": "Old glued text", "summary_version": document_routes.DOCUMENT_SUMMARY_VERSION - 1}
    assert document_routes._summary_current(current) is True
    assert document_routes._summary_current(stale) is False
