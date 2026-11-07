"""Geometry-aware PDF tables: no text duplication, cross-page stitching,
header detection, and safe re-extraction of existing documents.

PDFs are synthesised with PyMuPDF (ruled tables with made-up values).
"""
import pytest

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("pdfplumber")

from langchain_core.documents import Document  # noqa: E402

from insight_rag.pdf_ingest import (  # noqa: E402
    _row_is_header,
    _with_header,
    extract_pdf_documents,
)

ROW_H = 18


def _draw_table(page, top, rows, widths=(150, 120)):
    for r, row in enumerate(rows):
        y, x = top + r * ROW_H, 72
        for c, cell in enumerate(row):
            page.draw_rect(pymupdf.Rect(x, y, x + widths[c], y + ROW_H), color=(0, 0, 0), width=0.7)
            page.insert_text((x + 4, y + 13), cell, fontsize=10)
            x += widths[c]


def _region_rows(start, stop):
    return [[f"Region {i}", f"{1000 + i * 10}"] for i in range(start, stop)]


def _pdf(tmp_path, build):
    doc = pymupdf.open()
    build(doc)
    path = tmp_path / "synthetic.pdf"
    doc.save(path)
    return path


def test_table_text_is_indexed_once_and_stitched_across_pages(tmp_path):
    def build(doc):
        first = doc.new_page()
        first.insert_text((72, 72), "Quarterly report. Regional sales are summarised below.", fontsize=11)
        _draw_table(first, 120, [["Region", "Sales"]] + _region_rows(1, 36))  # runs to the page bottom
        second = doc.new_page()
        _draw_table(second, 50, [["Region", "Sales"]] + _region_rows(36, 41))  # repeated header
        second.insert_text((72, 300), "Closing notes follow the table.", fontsize=11)

    docs, stats = extract_pdf_documents(_pdf(tmp_path, build), document_id="doc-geometry", filename="s.pdf")

    text = [d for d in docs if d.metadata["content_type"] == "text"]
    tables = [d for d in docs if d.metadata["content_type"] == "table"]
    assert stats["tables"] == 1
    assert not any("Region 7" in d.page_content for d in text), "table cells leaked into prose chunks"
    assert any("Quarterly report" in d.page_content for d in text)
    assert any("Closing notes" in d.page_content for d in text)

    meta = tables[0].metadata
    assert meta["page"] == 1 and meta["page_end"] == 2
    assert meta["table_row_count"] == 40 and meta["table_header_detected"] is True
    assert meta["table_extraction"] == "geometry_v1" and len(meta["table_bbox"]) == 4
    body = "\n".join(d.page_content for d in tables)
    assert body.count("| Region | Sales |") == len(tables)  # header repeated per chunk only
    assert "Region 40" in body


def test_unrelated_tables_on_consecutive_pages_are_not_merged(tmp_path):
    def build(doc):
        first = doc.new_page()
        _draw_table(first, 100, [["Region", "Sales"]] + _region_rows(1, 4))  # ends mid-page
        first.insert_text((72, 400), "Enough prose to pass the text check on page one.", fontsize=11)
        second = doc.new_page()
        _draw_table(second, 50, [["Region", "Sales"]] + _region_rows(10, 13))
        second.insert_text((72, 400), "Enough prose to pass the text check on page two.", fontsize=11)

    docs, stats = extract_pdf_documents(_pdf(tmp_path, build), document_id="doc-separate", filename="s.pdf")
    assert stats["tables"] == 2
    assert all("page_end" not in d.metadata for d in docs)


def test_header_detection():
    assert _row_is_header(["Region", "2024", "2025"]) is True  # year headings are headers
    assert _row_is_header(["North", "1,200", "900"]) is False
    rows, detected = _with_header([["North", "1,200"], ["South", "900"]])
    assert detected is False
    assert rows[0] == ["Column 1", "Column 2"] and rows[1] == ["North", "1,200"]


class _Store:
    """Vector store double that records upserts/deletes and can fail once."""

    def __init__(self, fail_add=False):
        self.vectors, self.fail_add = {}, fail_add

    def __call__(self, _user):
        return self

    def add_documents(self, docs):
        if self.fail_add:
            self.fail_add = False
            for doc in docs[:1]:  # partial write before the failure
                self.vectors[doc.metadata["chunk_id"]] = doc.page_content
            raise RuntimeError("index unavailable")
        for doc in docs:
            self.vectors[doc.metadata["chunk_id"]] = doc.page_content
        return [d.metadata["chunk_id"] for d in docs]

    def delete_chunks(self, ids):
        for cid in ids:
            self.vectors.pop(cid, None)


@pytest.fixture
def stored_pdf(tmp_path, monkeypatch):
    import insight_rag.config as config
    import insight_rag.ingestion as ingestion
    from insight_rag.storage import RAGMetadataStore

    monkeypatch.setattr(config, "RAG_USERS_DIR", tmp_path / "users")

    def build(doc):
        page = doc.new_page()
        page.insert_text((72, 72), "Sales overview for the synthetic company.", fontsize=11)
        _draw_table(page, 120, [["Region", "Sales"]] + _region_rows(1, 5))

    source = _pdf(tmp_path, build)
    meta = RAGMetadataStore("geo-user")
    did = "doc-legacy-1"
    meta.document_file_path(did).write_bytes(source.read_bytes())
    old = [Document(page_content="Region 1 1010 Region 2 1020 (legacy flattened)",
                    metadata={"chunk_id": "legacy-chunk", "document_id": did, "page": 1})]
    meta.save_chunks(did, old)
    meta.put_document({"document_id": did, "filename": "legacy.pdf", "chunk_ids": ["legacy-chunk"],
                       "rag_schema_version": 2, "status": "ready"})
    return ingestion, meta, did


def test_rechunk_migrates_legacy_document(stored_pdf, monkeypatch):
    ingestion, meta, did = stored_pdf
    store = _Store()
    store.vectors["legacy-chunk"] = "old"
    monkeypatch.setattr(ingestion, "UserPGVectorStore", store)

    result = ingestion.PDFIngestion("geo-user").rechunk(did)

    record = meta.get_document(did)
    assert result["rechunked"] is True and record["rag_schema_version"] == ingestion.RAG_SCHEMA_VERSION
    assert "legacy-chunk" not in store.vectors  # stale vector removed
    assert set(store.vectors) == set(record["chunk_ids"])
    assert any(c.metadata["content_type"] == "table" for c in meta.load_chunks(did))


def test_rechunk_failure_restores_previous_chunks(stored_pdf, monkeypatch):
    ingestion, meta, did = stored_pdf
    store = _Store(fail_add=True)
    store.vectors["legacy-chunk"] = "Region 1 1010 Region 2 1020 (legacy flattened)"
    monkeypatch.setattr(ingestion, "UserPGVectorStore", store)

    with pytest.raises(RuntimeError):
        ingestion.PDFIngestion("geo-user").rechunk(did)

    assert set(store.vectors) == {"legacy-chunk"}  # partial new write rolled back
    assert [c.metadata["chunk_id"] for c in meta.load_chunks(did)] == ["legacy-chunk"]
    assert meta.get_document(did)["rag_schema_version"] == 2


def test_rechunk_rejects_non_pdf(stored_pdf):
    ingestion, meta, did = stored_pdf
    record = meta.get_document(did)
    record["source_type"] = "csv"
    meta.put_document(record)
    with pytest.raises(ValueError, match="Only PDF"):
        ingestion.PDFIngestion("geo-user").rechunk(did)
