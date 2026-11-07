"""Client-facing views of evidence: clean snippets, structured tables, charts.

All functions are deterministic and work only on text/metadata already
retrieved for the user; nothing here calls a model or reads other storage.
Column names are never assumed: label and numeric columns are inferred from
the cell values of each cited table.
"""

from __future__ import annotations

import re

from .locations import source_location
from .tabular import _TOTAL_LIKE, _parse_number

_SNIPPET_CHARS = 280
_EXCERPT_CHARS = 700
_TABLE_MAX_ROWS = 25
_CHART_MAX_POINTS = 24
_CHART_MAX_SERIES = 3

# Only ``**`` is treated as emphasis: ``__`` appears in real identifiers.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_STRAY_MARKERS_RE = re.compile(r"\*\*")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_EMPTY_BULLET_RE = re.compile(r"^[ \t]*(?:[-*•‣◦▪]|\d+[.)])[ \t]*(?:\n|$)", re.M)
_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def clean_text(text: str) -> str:
    """Remove literal Markdown emphasis/heading markers and empty bullet lines."""
    text = str(text or "")
    text = _BOLD_RE.sub(r"\1", text)
    text = _STRAY_MARKERS_RE.sub("", text)
    text = _HEADING_RE.sub("", text)
    text = _EMPTY_BULLET_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_snippet(text: str, limit: int = _SNIPPET_CHARS) -> str:
    """One-line snippet (the legacy ``snippet`` contract) without Markdown noise."""
    flat = " ".join(clean_text(text).split())
    return flat[:limit]


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells = re.split(r"(?<!\\)\|", body)
    return [cell.replace("\\|", "|").strip() for cell in cells]


def parse_markdown_table(text: str, max_rows: int = _TABLE_MAX_ROWS) -> dict | None:
    """Parse the first pipe table in ``text`` into ``{columns, rows}``.

    Empty cells are preserved (never filtered) so rows stay aligned with the
    header.
    """
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    for index in range(len(lines) - 1):
        if "|" in lines[index] and _SEPARATOR_RE.match(lines[index + 1].strip()):
            columns = _split_row(lines[index])
            rows = []
            for line in lines[index + 2:]:
                if "|" not in line:
                    break
                cells = _split_row(line)
                cells = (cells + [""] * len(columns))[:len(columns)]
                rows.append(cells)
                if len(rows) >= max_rows:
                    break
            if columns and rows:
                return {"columns": columns, "rows": rows}
    return None


def _excerpt(text: str, is_table: bool) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= _EXCERPT_CHARS:
        return cleaned
    if is_table:
        # Cut on a line boundary so a table row is never half-rendered.
        kept, used = [], 0
        for line in cleaned.splitlines():
            if used + len(line) + 1 > _EXCERPT_CHARS:
                break
            kept.append(line)
            used += len(line) + 1
        return "\n".join(kept)
    return cleaned[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"


def source_extras(meta: dict, content: str) -> dict:
    """Extra, additive fields for a source payload."""
    is_table = (meta or {}).get("content_type") == "table"
    extras = dict(source_location(meta or {}))
    extras["excerpt"] = _excerpt(content, is_table)
    if is_table and not (meta or {}).get("table_summary"):
        table = parse_markdown_table(content)
        if table:
            extras["table"] = table
    return extras


# ── Charts ────────────────────────────────────────────────────────────

def _numeric_columns(table: dict) -> list[int]:
    out = []
    for col in range(len(table["columns"])):
        values = [row[col] for row in table["rows"] if row[col].strip()]
        if len(values) < 2:
            continue
        parsed = [_parse_number(v) for v in values]
        if sum(p is not None for p in parsed) / len(values) >= 0.8:
            out.append(col)
    return out


def _label_column(table: dict, numeric: list[int]) -> int | None:
    for col in range(len(table["columns"])):
        if col in numeric:
            continue
        labels = [row[col].strip() for row in table["rows"] if row[col].strip()]
        if len(labels) >= 2 and len(set(labels)) >= 0.6 * len(labels):
            return col
    return None


def _table_points(table: dict) -> tuple[str, list[str], list[dict]] | None:
    numeric = _numeric_columns(table)
    label_col = _label_column(table, numeric)
    if label_col is None or not numeric:
        return None
    series = [table["columns"][c] for c in numeric[:_CHART_MAX_SERIES]]
    points = []
    for row in table["rows"]:
        label = row[label_col].strip()
        if not label or label.casefold() in _TOTAL_LIKE:
            continue  # totals would dwarf the parts they sum
        point = {"label": label}
        for col, name in zip(numeric, series):
            value = _parse_number(row[col])
            if value is not None:
                point[name] = value
        if len(point) > 1:
            points.append(point)
    if len(points) < 2:
        return None
    return table["columns"][label_col], series, points[:_CHART_MAX_POINTS]


def build_visualization(sources: list[dict]) -> dict | None:
    """Chart spec from cited table evidence, or ``None`` when nothing is chartable.

    When cited tables from two or more documents share a label column and a
    numeric column, they are merged into one comparison chart with one series
    per document (cross-document aggregation). Otherwise the largest chartable
    cited table is used.
    """
    candidates = []
    for source in sources or []:
        table = source.get("table")
        if not isinstance(table, dict):
            continue
        parsed = _table_points(table)
        if parsed:
            candidates.append((source, *parsed))
    if not candidates:
        return None

    by_doc: dict[str, tuple] = {}
    for candidate in candidates:
        by_doc.setdefault(str(candidate[0].get("document_id")), candidate)
    if len(by_doc) >= 2:
        groups: dict[tuple[str, str], list[tuple]] = {}
        for source, label_name, series, points in by_doc.values():
            for name in series:
                groups.setdefault((label_name.casefold(), name.casefold()), []).append(
                    (source, label_name, name, points))
        shared = max(groups.values(), key=len)
        if len(shared) >= 2:
            merged: dict[str, dict] = {}
            series_out = []
            for source, label_name, name, points in shared:
                key = f"{source.get('filename') or source.get('document_id')}"
                series_out.append({"key": key, "label": key, "source_id": source.get("source_id")})
                for point in points:
                    if name in point:
                        merged.setdefault(point["label"], {"label": point["label"]})[key] = point[name]
            data = list(merged.values())[:_CHART_MAX_POINTS]
            if len(data) >= 2:
                first = shared[0]
                return {
                    "type": "bar",
                    "title": f"{first[2]} by {first[1]} across documents",
                    "x_key": "label",
                    "x_label": first[1],
                    "y_label": first[2],
                    "series": series_out,
                    "data": data,
                    "cross_document": True,
                    "source_ids": [s.get("source_id") for s, *_ in shared],
                }

    source, label_name, series, points = max(candidates, key=lambda c: len(c[3]))
    return {
        "type": "bar",
        "title": f"{', '.join(series)} by {label_name}",
        "x_key": "label",
        "x_label": label_name,
        "y_label": series[0] if len(series) == 1 else "",
        "series": [{"key": name, "label": name, "source_id": source.get("source_id")} for name in series],
        "data": points,
        "cross_document": False,
        "source_ids": [source.get("source_id")],
    }
