"""ARIA unified semantic layer helpers (t.txt Phase 1-2, sections 8-13).

Pure, dependency-free helpers shared by schema/goal/query routes:
- semantic type classification for arbitrary column names/types
- structured result envelope (result/evidence/confidence/provenance)
- identifier validation for user overrides

Deterministic only — no LLM calls here (truth layer, RL must not alter it).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_NUMERIC_HINTS = ("int", "float", "double", "decimal", "numeric", "number", "real")
_DATE_HINTS = ("date", "time", "timestamp", "datetime")
_BOOL_HINTS = ("bool",)
_ID_HINTS = ("_id", "id", "uuid", "guid", "key", "code", "number", "no")
_MONEY_HINTS = ("price", "cost", "amount", "revenue", "profit", "salary", "total", "payment")
_PCT_HINTS = ("pct", "percent", "rate", "ratio")
_GEO_HINTS = ("city", "country", "region", "state", "zip", "postal", "lat", "lon", "lng", "address")


def is_valid_identifier(name: str, max_len: int = 64) -> bool:
    """Conservative identifier check for table/column names from user input."""
    return bool(name) and len(name) <= max_len and bool(IDENT_RE.match(name))


def humanize(name: str) -> str:
    """Turn a physical column/table name into natural language.

    Generic formatting only (no business dictionary): underscores become
    spaces, words are title-cased, trailing _id/_key/_code markers are
    dropped. ``order_date`` → ``Order Date``.
    """
    text = re.sub(r"[_-]+", " ", str(name or "")).strip()
    text = re.sub(r"\s+", " ", text)
    words = [w for w in text.split(" ") if w]
    drop_tail = {"id", "key", "code", "uuid", "guid", "pk", "fk"}
    while len(words) > 1 and words[-1].lower() in drop_tail:
        words.pop()
    return " ".join(w[:1].upper() + w[1:] for w in words) or str(name or "")


def kpi_label(agg: str, column: str) -> str:
    """Natural-language KPI label from aggregation + column (no table names)."""
    human = humanize(column)
    agg = (agg or "").upper()
    if agg == "AVG":
        return f"Average {human}"
    if agg == "DISTINCT":
        return f"{human} Count"
    if agg == "COUNT":
        return "Total Records"
    return f"Total {human}"


def classify_semantic_type(column_name: str, db_type: str = "") -> str:
    """Classify a column into a semantic type without assuming fixed schemas.

    Returns one of: identifier, measure, money, percentage, date, boolean,
    category, geography, text.
    """
    name = (column_name or "").lower()
    dtype = (db_type or "").lower()
    if any(h in dtype for h in _BOOL_HINTS) or dtype in ("boolean", "bit"):
        return "boolean"
    if any(h in dtype for h in _DATE_HINTS):
        return "date"
    if any(h in dtype for h in _NUMERIC_HINTS):
        if any(h in name for h in _ID_HINTS):
            return "identifier"
        if any(h in name for h in _MONEY_HINTS):
            return "money"
        if any(h in name for h in _PCT_HINTS):
            return "percentage"
        return "measure"
    if any(h in name for h in _ID_HINTS):
        return "identifier"
    if any(h in dtype for h in _DATE_HINTS) or "date" in name or "time" in name:
        return "date"
    if any(h in name for h in _MONEY_HINTS + _PCT_HINTS):
        return "measure"
    if any(h in name for h in _GEO_HINTS):
        return "geography"
    # Low-cardinality textual names behave as categories; default to text.
    return "text"


def build_result_envelope(
    result: object = None,
    *,
    evidence: list | None = None,
    source: str = "unknown",
    confidence: str = "medium",
    assumptions: list | None = None,
    warnings: list | None = None,
    errors: list | None = None,
    methodology: str = "",
    provenance: dict | None = None,
) -> dict:
    """Build the structured agent-output contract (t.txt section 7).

    Additive helper — callers spread existing payloads and add this envelope
    so the frontend can render trustworthy results consistently.
    """
    return {
        "result": result,
        "evidence": evidence or [],
        "source": source,
        "confidence": confidence,
        "assumptions": assumptions or [],
        "warnings": warnings or [],
        "errors": errors or [],
        "methodology": methodology,
        "provenance": provenance or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
