"""Citation locations, clean source text, structured tables and answer charts."""
import pandas as pd

from insight_rag.locations import context_location, source_location
from insight_rag.source_view import (
    build_visualization,
    clean_snippet,
    clean_text,
    parse_markdown_table,
    source_extras,
)
from insight_rag.tabular import dataframe_to_table_documents


def test_pdf_locations_use_real_pages():
    assert source_location({"page": 4, "content_type": "text"})["location_label"] == "p. 4"
    table = source_location({"page": 2, "content_type": "table", "table_index": 3, "page_end": 3})
    assert table["location_label"] == "pp. 2–3, table 3"
    assert table["location"] == {"kind": "page", "page": 2, "table_index": 3, "page_end": 3}


def test_tabular_sources_cite_rows_not_page_one():
    frame = pd.DataFrame({"Region": [f"R{i}" for i in range(60)], "Sales": range(60)})
    docs, _ = dataframe_to_table_documents(frame, document_id="doc-t", filename="sales.csv",
                                           rows_per_chunk=25, max_row_chunks=12)
    summary, first_rows, second_rows = docs[0], docs[1], docs[2]
    assert source_location(summary.metadata)["location_label"] == "table summary (60 rows)"
    assert source_location(first_rows.metadata)["location_label"] == "rows 1–25"
    assert source_location(second_rows.metadata)["location_label"] == "rows 26–50"
    assert context_location(first_rows.metadata) == "rows 1–25"
    assert "page" not in context_location(first_rows.metadata)


def test_sampled_tabular_rows_keep_original_row_numbers(monkeypatch):
    monkeypatch.setattr("insight_rag.tabular.TABULAR_MAX_ROWS", 10)
    frame = pd.DataFrame({"Item": [f"I{i}" for i in range(100)], "Qty": range(100)})
    docs, _ = dataframe_to_table_documents(frame, document_id="doc-s", filename="big.csv",
                                           rows_per_chunk=5, max_row_chunks=4)
    assert docs[0].metadata["source_row_count"] == 100
    assert "sample of 10 of 100 rows" in docs[0].page_content
    rows = docs[1].metadata
    assert rows["row_end"] > 10  # numbers refer to the original file, not the sample
    assert source_location(rows)["location_label"].startswith("sampled rows")


def test_snippets_drop_markdown_markers_and_empty_bullets():
    raw = "## Highlights\n**Revenue** grew 12%.\n-\n* \n- Margin held\n1.\n**"
    cleaned = clean_text(raw)
    assert "**" not in cleaned and "#" not in cleaned
    assert cleaned.splitlines() == ["Highlights", "Revenue grew 12%.", "- Margin held"]
    assert clean_snippet(raw) == "Highlights Revenue grew 12%. - Margin held"
    assert clean_text("call __init__ here") == "call __init__ here"


def test_table_parsing_keeps_empty_cells_aligned():
    table = parse_markdown_table("| Region | Q1 | Q2 |\n| --- | --- | --- |\n| North |  | 20 |\n| South | 5 | 7 |")
    assert table == {"columns": ["Region", "Q1", "Q2"], "rows": [["North", "", "20"], ["South", "5", "7"]]}


def test_source_extras_include_structured_table_and_excerpt():
    content = "| Region | Sales |\n| --- | --- |\n| North | 10 |\n| South | 20 |"
    extras = source_extras({"page": 3, "content_type": "table", "table_index": 1}, content)
    assert extras["location_label"] == "p. 3, table 1"
    assert extras["table"]["rows"] == [["North", "10"], ["South", "20"]]
    assert extras["excerpt"].count("\n") == 3  # rows kept on their own lines


def _table_source(sid, did, rows, header=("Region", "Sales")):
    return {"source_id": sid, "document_id": did, "filename": f"{did}.pdf",
            "table": {"columns": list(header), "rows": rows}}


def test_visualization_from_single_cited_table_skips_totals():
    chart = build_visualization([_table_source("S1", "d1", [
        ["North", "$1,200"], ["South", "800"], ["Total", "2,000"]])])
    assert chart["type"] == "bar" and chart["cross_document"] is False
    assert chart["data"] == [{"label": "North", "Sales": 1200.0}, {"label": "South", "Sales": 800.0}]
    assert chart["source_ids"] == ["S1"]


def test_visualization_merges_matching_tables_across_documents():
    chart = build_visualization([
        _table_source("S1", "report-2024", [["North", "10"], ["South", "20"]]),
        _table_source("S2", "report-2025", [["North", "15"], ["South", "25"]]),
    ])
    assert chart["cross_document"] is True
    assert [s["key"] for s in chart["series"]] == ["report-2024.pdf", "report-2025.pdf"]
    assert chart["data"][0] == {"label": "North", "report-2024.pdf": 10.0, "report-2025.pdf": 15.0}


def test_no_chart_without_numeric_table_evidence():
    assert build_visualization([{"source_id": "S1", "snippet": "Revenue rose 10%."}]) is None
    assert build_visualization([_table_source("S1", "d", [["North", "n/a"], ["South", "tbd"]])]) is None
