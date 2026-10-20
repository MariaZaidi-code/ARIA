from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from docx import Document as WordDocument
from fastapi import HTTPException, UploadFile

import api.insight_rag_routes as insight_rag_routes


@pytest.fixture
def document_upload(monkeypatch):
    stored = {
        "document_id": "doc-upload-test",
        "filename": "",
        "size_bytes": 0,
        "row_count": 2,
        "tags": [],
    }
    ingested = {}

    class Capability:
        def ingest_pdf(self, *_args, **_kwargs):
            raise AssertionError("tabular document upload must not use PDF ingestion")

        def ingest_tabular(self, source, *, filename, table_name):
            ingested.update(source=source, filename=filename, table_name=table_name)
            if isinstance(source, (str, Path)):
                ingested["source_content"] = Path(source).read_bytes()
            stored["filename"] = filename
            return {"ok": True, "document": dict(stored)}

    class MetadataStore:
        def __init__(self, _user_id):
            pass

        def get_document(self, document_id):
            return stored if document_id == stored["document_id"] else None

        def load_chunks(self, _document_id):
            return [SimpleNamespace(page_content="Quarterly sales report")]

        def put_document(self, record):
            stored.update(record)

    monkeypatch.setattr(insight_rag_routes, "_capability", lambda _user_id: Capability())
    monkeypatch.setattr(insight_rag_routes, "RAGMetadataStore", MetadataStore)
    return stored, ingested


def _upload(filename: str, content: bytes):
    return UploadFile(filename=filename, file=BytesIO(content))


def test_csv_upload_uses_tabular_rag_and_records_real_file_size(document_upload):
    stored, ingested = document_upload
    content = b"month,sales\nJanuary,125\nFebruary,150\n"

    response = insight_rag_routes.upload_document(
        _upload("sales.csv", content),
        {"user_id": "test-user"},
    )

    assert response["ok"] is True
    assert ingested["source_content"] == content
    assert stored["source_type"] == "csv"
    assert stored["size_bytes"] == len(content)
    assert stored["element_count"] == 2
    assert stored["tags"] == ["report"]


def test_xlsx_upload_reads_all_nonempty_sheets(document_upload):
    stored, ingested = document_upload
    workbook_bytes = BytesIO()
    with pd.ExcelWriter(workbook_bytes, engine="openpyxl") as writer:
        pd.DataFrame({"Month": ["Jan"], "Sales": [100]}).to_excel(writer, sheet_name="North", index=False)
        pd.DataFrame({"Month": ["Feb"], "Sales": [125]}).to_excel(writer, sheet_name="South", index=False)

    response = insight_rag_routes.upload_document(
        _upload("sales.xlsx", workbook_bytes.getvalue()),
        {"user_id": "test-user"},
    )

    assert response["ok"] is True
    assert ingested["source"]["_worksheet"].tolist() == ["North", "South"]
    assert stored["source_type"] == "xlsx"
    assert stored["element_count"] == 2


def test_docx_upload_indexes_paragraphs_and_table_rows(document_upload):
    stored, ingested = document_upload
    document = WordDocument()
    document.add_paragraph("Quarterly business summary")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Region"
    table.cell(0, 1).text = "Revenue"
    table.cell(1, 0).text = "West"
    table.cell(1, 1).text = "$125,000"
    content = BytesIO()
    document.save(content)

    response = insight_rag_routes.upload_document(
        _upload("summary.docx", content.getvalue()),
        {"user_id": "test-user"},
    )

    assert response["ok"] is True
    assert ingested["source"][0]["Text"] == "Quarterly business summary"
    assert ingested["source"][-1]["Text"] == "West | $125,000"
    assert stored["source_type"] == "docx"
    assert stored["element_count"] == 3


def test_upload_rejects_unsupported_file_extensions():
    with pytest.raises(HTTPException) as exc:
        insight_rag_routes.upload_document(
            _upload("malware.exe", b"not a supported document"),
            {"user_id": "test-user"},
        )

    assert exc.value.status_code == 400


def test_xlsx_upload_rejects_invalid_office_archive(document_upload):
    with pytest.raises(HTTPException) as exc:
        insight_rag_routes.upload_document(
            _upload("broken.xlsx", b"not an Office archive"),
            {"user_id": "test-user"},
        )

    assert exc.value.status_code == 400
