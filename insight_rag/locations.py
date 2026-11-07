"""Human-readable source locations for citations.

PDF chunks carry a real 1-based ``page``. Tabular chunks (CSV / XLSX / DOCX
records) are stored with ``page: 1`` for index compatibility, which is not a
meaningful citation; for those the location is the table and row span.
``page_number`` in API payloads is left untouched for compatibility; callers
add ``location_label`` / ``location`` alongside it.
"""

from __future__ import annotations


def is_tabular(meta: dict) -> bool:
    return str(meta.get("source_type") or "") == "tabular"


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def source_location(meta: dict) -> dict:
    """Return ``{"location_label": str, "location": {...}}`` for one chunk."""
    meta = meta or {}
    if is_tabular(meta):
        location = {"kind": "rows"}
        if meta.get("table_summary"):
            rows = _as_int(meta.get("source_row_count") or meta.get("table_row_count"))
            location.update(summary=True, row_count=rows)
            label = f"table summary ({rows} rows)" if rows else "table summary"
            return {"location_label": label, "location": location}
        start, end = _as_int(meta.get("row_start")), _as_int(meta.get("row_end"))
        if start and end:
            location.update(row_start=start, row_end=end,
                            contiguous=bool(meta.get("rows_contiguous", True)))
            span = f"row {start}" if start == end else f"rows {start}–{end}"
            if not location["contiguous"]:
                span = f"sampled {span}"
            return {"location_label": span, "location": location}
        part = _as_int(meta.get("table_chunk_index"))
        label = f"table part {part + 1}" if part is not None and part >= 0 else "table"
        return {"location_label": label, "location": location}

    page = _as_int(meta.get("page", meta.get("page_number")))
    location = {"kind": "page", "page": page}
    label = f"p. {page}" if page else ""
    if meta.get("content_type") == "table":
        index = _as_int(meta.get("table_index"))
        location["table_index"] = index
        if index:
            label = f"{label}, table {index}" if label else f"table {index}"
        page_end = _as_int(meta.get("page_end"))
        if page and page_end and page_end > page:
            location["page_end"] = page_end
            label = label.replace(f"p. {page}", f"pp. {page}–{page_end}", 1)
    return {"location_label": label, "location": location}


def context_location(meta: dict) -> str:
    """Location phrase used in the LLM context block title."""
    if is_tabular(meta):
        return source_location(meta)["location_label"]
    return f"page {meta.get('page')}"
