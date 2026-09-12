"""Analytical result reasoning for ARIA.

The Goal IR states what the user asked for; a raw SQL result does not. This
module is the single place that decides whether a returned result actually
answers the question, repairs transaction-level output into the requested
granularity using only the rows that were returned, and produces the answer,
story and visualization from the validated frame.

Rules:
- truth layer only: re-aggregation uses returned values, never invented ones;
- provider-agnostic and deterministic (identical on local and cloud LLMs);
- intent-aware: granularity, ranking, sorting and chart type follow the
  question, not the incidental shape of the returned columns.
"""

from __future__ import annotations

import math
import re
from datetime import datetime


_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")
_DATETIME_NAME_RE = re.compile(
    r"(date|time|month|year|period|day|week|quarter|timestamp)", re.IGNORECASE
)

_GENERIC_CONCEPTS = {
    "general kpi", "aggregate total", "row count", "average value",
    "maximum value", "minimum value", "sales kpi", "revenue kpi",
    "profit kpi", "growth kpi",
}

_LABEL_PRIORITY = (
    "full_name", "fullname", "display_name", "name", "company_name", "company",
    "product_name", "customer_name", "employee_name", "title", "label",
    "description", "category_name", "category", "segment", "region", "country",
    "city", "state", "status",
)

_MEASURE_PRIORITY = (
    "total", "amount", "value", "revenue", "sales", "sum", "count", "quantity",
    "qty", "units", "price", "cost", "profit", "margin", "score", "rate",
)

_MEASURE_WORDS = {
    "value", "amount", "total", "revenue", "sales", "price", "quantity", "qty",
    "cost", "profit", "margin", "sum", "volume", "income",
}

_GROUPING_OPS = {"ranking", "aggregation", "distribution", "comparison", "summary"}

_TREND_OPS = {"trend"}


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _singular(word) -> str:
    w = str(word or "")
    if w.endswith("ies") and len(w) > 3:
        return w[:-3] + "y"
    if w.endswith("ses") and len(w) > 3:
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 1:
        return w[:-1]
    return w


def natural_label(identifier) -> str:
    """Identifier -> plain-English phrase: 'order_details' -> 'order detail'."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", str(identifier or "")) if p]
    if not parts:
        return str(identifier or "")
    return " ".join(_singular(p.lower()) for p in parts)


def _plural(label: str) -> str:
    if not label:
        return label
    if label.endswith("y") and len(label) > 1 and label[-2] not in "aeiou":
        return label[:-1] + "ies"
    if label.endswith(("s", "x", "z", "ch", "sh")):
        return label + "es"
    return label + "s"


def _is_id_like(name) -> bool:
    low = _norm(name)
    if not low:
        return False
    return (
        low in ("id", "key", "code", "codeid")
        or low.endswith("_id") or low.endswith("_key") or low.endswith("_code")
        or low.endswith("id")
    )


def _to_float(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if _NUMERIC_RE.match(s):
            try:
                return float(s)
            except ValueError:
                return None
    return None


def _looks_like_datetime(value) -> bool:
    if isinstance(value, datetime):
        return True
    if not isinstance(value, str):
        return False
    s = value.strip()
    if len(s) < 6:
        return False
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m",
                "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            datetime.strptime(s[:19], fmt)
            return True
        except ValueError:
            continue
    return bool(re.match(r"^\d{4}-\d{2}", s))


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def profile_columns(columns, rows) -> dict:
    """Classify returned columns into numeric / text / datetime / id-like."""
    sample = rows[:50]
    profile = {"numeric": [], "text": [], "datetime": [], "id_like": []}
    for col in columns or []:
        values = [r.get(col) for r in sample if isinstance(r, dict)]
        non_null = [v for v in values if v is not None and v != ""]
        numeric_hits = sum(1 for v in non_null if _to_float(v) is not None)
        dt_hits = sum(1 for v in non_null if _looks_like_datetime(v))
        if _is_id_like(col):
            profile["id_like"].append(col)
        if non_null and numeric_hits / len(non_null) >= 0.8:
            profile["numeric"].append(col)
        if _DATETIME_NAME_RE.search(str(col)) or (non_null and dt_hits / len(non_null) >= 0.8):
            profile["datetime"].append(col)
        if col not in profile["numeric"] and col not in profile["datetime"]:
            profile["text"].append(col)
    return profile


def _find_col(columns, *candidates):
    lowered = {_norm(c): c for c in columns or []}
    for cand in candidates:
        if cand and _norm(cand) in lowered:
            return lowered[_norm(cand)]
    return None


def _find_col_loose(columns, *candidates):
    exact = _find_col(columns, *candidates)
    if exact:
        return exact
    for cand in candidates:
        low = _norm(cand)
        if not low:
            continue
        for col in columns or []:
            cl = _norm(col)
            if cl.endswith(low) or low.endswith(cl):
                return col
    return None


def extract_intent(ir, goal="") -> dict:
    """Read the requested operation, entity, measure and ranking from the IR."""
    ir = ir or {}
    operation = _norm(ir.get("operation")) or _norm(ir.get("intent")) or "summary"
    ranking = ir.get("ranking") or {}
    direction = _norm(ranking.get("direction")) or "desc"
    limit = ranking.get("limit")

    entity = None
    for dim in ir.get("dimensions") or []:
        table = dim.get("resolved_table") or dim.get("concept")
        if not table:
            continue
        entity = {
            "table": table,
            "column": dim.get("resolved_column"),
            "concept": dim.get("concept") or table,
        }
        break

    metric = None
    metrics = ir.get("metrics") or []
    if metrics:
        m = metrics[0]
        agg = m.get("aggregation")
        expression = _norm(m.get("resolved_expression"))
        if not agg and expression == "count(*)":
            agg = "COUNT"
        metric = {
            "aggregation": agg or ("COUNT" if not m.get("resolved_column") else "SUM"),
            "column": m.get("resolved_column"),
            "table": m.get("resolved_table"),
            "expression": m.get("resolved_expression"),
            "concept": m.get("concept"),
            "inferred": bool(m.get("inferred")),
        }

    goal_l = _norm(goal) or _norm(ir.get("original_goal"))
    goal_words = set(re.findall(r"[a-z0-9]+", goal_l))
    if metric and metric.get("aggregation") == "COUNT" and metric.get("inferred"):
        if goal_words & _MEASURE_WORDS:
            metric["aggregation"] = "SUM"

    wants_share = bool(goal_words & {"share", "percentage", "percent", "proportion",
                                     "composition", "pie", "donut", "doughnut"})

    return {
        "operation": operation,
        "intent": _norm(ir.get("intent")) or operation,
        "direction": direction,
        "limit": int(limit) if limit else (10 if operation == "ranking" else None),
        "entity": entity,
        "metric": metric,
        "wants_share": wants_share,
    }


def _col_is_text(col, profile) -> bool:
    return (
        col not in profile["numeric"]
        and col not in profile["datetime"]
        and not _is_id_like(col)
    )


def _resolve_entity_key(intent, columns, rows, profile):
    table = (intent.get("entity") or {}).get("table")
    if table:
        t = _norm(table)
        found = _find_col_loose(columns, f"{t}_id", f"{t}id", f"{t}_key", f"id_{t}")
        if found:
            return found
    ratio = {}
    for col in profile["id_like"]:
        vals = {str(r.get(col)) for r in rows if isinstance(r, dict) and r.get(col) is not None}
        if vals:
            ratio[col] = len(vals) / max(1, len(rows))
    repeats = {c: v for c, v in ratio.items() if 0.02 <= v <= 0.9}
    if repeats:
        return min(repeats, key=lambda c: repeats[c])
    return None


def _resolve_label(intent, columns, rows, key_col, profile):
    dim_col = (intent.get("entity") or {}).get("column")
    if dim_col:
        found = _find_col_loose(columns, dim_col)
        if found and found != key_col and _col_is_text(found, profile):
            return found
    for cand in _LABEL_PRIORITY:
        found = _find_col_loose(columns, cand)
        if found and found != key_col and _col_is_text(found, profile):
            return found
    for col in columns or []:
        if col != key_col and _col_is_text(col, profile):
            return col
    return key_col


def _resolve_measure(intent, columns, rows, profile):
    metric = intent.get("metric") or {}
    if metric.get("aggregation") == "COUNT" and not metric.get("column"):
        return None
    col = metric.get("column")
    if col:
        found = _find_col_loose(columns, col)
        if found and found in profile["numeric"]:
            return found
    for cand in _MEASURE_PRIORITY:
        for c in profile["numeric"]:
            if cand in _norm(c):
                return c
    nums = [c for c in profile["numeric"] if not _is_id_like(c)]
    if nums:
        return nums[-1]
    return profile["numeric"][-1] if profile["numeric"] else None


def _aggregate_rows(rows, key_col, label_col, measure_col, aggregation):
    buckets, order = {}, []
    for r in rows:
        if not isinstance(r, dict):
            continue
        key = r.get(key_col)
        if key is None:
            continue
        skey = str(key)
        if skey not in buckets:
            buckets[skey] = {"label": None, "values": [], "count": 0}
            order.append(skey)
        b = buckets[skey]
        b["count"] += 1
        if b["label"] is None and label_col:
            lv = r.get(label_col)
            if lv not in (None, ""):
                b["label"] = lv
        if measure_col:
            v = _to_float(r.get(measure_col))
            if v is not None:
                b["values"].append(v)
    out = []
    for skey in order:
        b = buckets[skey]
        vals = b["values"]
        if aggregation == "COUNT" or not vals:
            value = float(b["count"])
        elif aggregation == "AVG":
            value = sum(vals) / len(vals)
        elif aggregation == "MIN":
            value = min(vals)
        elif aggregation == "MAX":
            value = max(vals)
        else:
            value = sum(vals)
        out.append({
            "key": skey,
            "label": b["label"] if b["label"] is not None else skey,
            "value": round(float(value), 2),
        })
    return out


def _frame(agg_rows, label_name, measure_name):
    return [{label_name: a["label"], measure_name: a["value"]} for a in agg_rows]


def _measure_label(intent, measure_col, aggregation) -> str:
    metric = intent.get("metric") or {}
    col = measure_col or metric.get("column")
    if aggregation == "COUNT" and not col:
        return "record count"
    if col:
        return natural_label(col)
    concept = metric.get("concept")
    if concept and _norm(concept) not in _GENERIC_CONCEPTS:
        return natural_label(concept)
    return "value"


def _entity_label(intent) -> str:
    """Human noun for the entity being grouped/ranked.

    Prefers the entity concept/table name, but when that is not a meaningful
    word (e.g. a CSV upload whose table is the filename stem 's'), falls back
    to the resolved grouping column so the answer reads "Region North …"
    rather than "S North …".
    """
    ent = intent.get("entity") or {}
    concept = ent.get("concept") or ent.get("table") or "group"
    col = ent.get("column")
    if col and not _is_id_like(col) and len(str(concept).strip()) < 3:
        return natural_label(col)
    return natural_label(concept)


def synthesize_answer(frame, measure_label, entity_label) -> str:
    if not frame:
        return "No matching rows were found for this question."
    names = list(frame[0].keys())
    if len(names) >= 2:
        label_name, measure_name = names[0], names[1]
        top = frame[:3]
        lead = top[0]
        head = (f"{entity_label.capitalize()} {lead[label_name]} has the highest "
                f"{measure_label} at {_fmt(lead[measure_name])}")
        if len(top) > 1:
            others = "; ".join(
                f"{r[label_name]} ({_fmt(r[measure_name])})" for r in top[1:]
            )
            return f"{head}, followed by {others}."
        return head + "."
    if len(names) == 1:
        return f"The result is {_fmt(frame[0][names[0]])}."
    return f"{names[0]} = {_fmt(frame[0][names[0]])}, {names[1]} = {_fmt(frame[0][names[1]])}."


def _numeric_key(frame, names):
    """The frame column that actually holds the computed measure."""
    if not frame:
        return names[-1] if names else None
    for n in list(names)[1:]:
        vals = [_to_float(r.get(n)) for r in frame if r.get(n) is not None]
        if vals and len(vals) == len(frame) and all(v is not None for v in vals):
            return n
    return names[1] if len(names) > 1 else names[0]


def synthesize_trend_answer(frame, measure_label, period_label) -> str:
    if not frame:
        return "No matching rows were found for this question."
    names = list(frame[0].keys())
    if len(names) < 2:
        return synthesize_answer(frame, measure_label, period_label)
    label_name = names[0]
    measure_name = _numeric_key(frame, names)
    values = [(_to_float(r.get(measure_name)) or 0.0) for r in frame]
    labels = [r.get(label_name) for r in frame]
    first, last = values[0], values[-1]
    if first:
        pct = (last - first) / abs(first) * 100.0
        direction = "increased" if pct > 0 else ("decreased" if pct < 0 else "stayed flat")
        movement = f"{measure_label} {direction} by about {abs(pct):.0f}%"
    else:
        movement = f"{measure_label} moved from {_fmt(first)} to {_fmt(last)}"
    peak_i = max(range(len(values)), key=lambda i: values[i])
    low_i = min(range(len(values)), key=lambda i: values[i])
    return (
        f"Over {len(frame)} periods from {labels[0]} to {labels[-1]}, {movement}. "
        f"The peak is {labels[peak_i]} at {_fmt(values[peak_i])} and the low is "
        f"{labels[low_i]} at {_fmt(values[low_i])}."
    )


def build_story(frame, measure_label, entity_label, based_on, op="") -> str:
    if not frame:
        return "No data matched this question, so no conclusion can be drawn."
    names = list(frame[0].keys())
    if len(names) < 2:
        return synthesize_answer(frame, measure_label, entity_label)
    label_name = names[0]
    measure_name = _numeric_key(frame, names)
    values = [(_to_float(r.get(measure_name)) or 0.0) for r in frame]
    total = sum(values)
    lead = frame[0]
    lead_share = values[0] / total * 100 if total else 0
    parts = [
        synthesize_answer(frame, measure_label, entity_label),
        (f"{entity_label.capitalize()} {lead[label_name]} alone accounts for about "
         f"{lead_share:.0f}% of the measured {measure_label} across {len(frame)} "
         f"{_plural(entity_label)}."),
    ]
    if len(frame) > 3:
        top3 = sum(values[:3])
        top3_share = top3 / total * 100 if total else 0
        parts.append(
            f"The top three {_plural(entity_label)} together hold about "
            f"{top3_share:.0f}% of the total, so {measure_label} is concentrated."
        )
    if based_on:
        parts.append(f"Computed over {based_on} underlying records from the connected source.")
    parts.append("These associations describe this dataset only and do not establish causation.")
    return " ".join(parts)


def _compatible(op, wants_share, n_groups):
    if op == "ranking":
        base = ["bar_horizontal", "bar", "pie"]
    elif op in _TREND_OPS:
        base = ["line", "area", "bar"]
    else:
        base = ["bar", "bar_horizontal"]
    if wants_share and n_groups <= 8:
        base = ["pie"] + [b for b in base if b != "pie"]
    return base


def select_visualization(intent, columns, frame, measure_label) -> dict:
    op = intent["operation"]
    if not frame:
        return {
            "chart_type": "table", "label": "Table",
            "reason": "no result rows to visualize",
            "x": None, "y": None, "results": [], "compatible": [],
        }
    if len(columns) < 2:
        profile = profile_columns(columns, frame)
        numeric = profile["numeric"]
        if numeric:
            return {
                "chart_type": "histogram", "label": "Distribution",
                "reason": "single measure — its distribution shows the spread",
                "x": numeric[0], "y": "count", "results": frame[:10],
                "compatible": ["histogram", "bar"], "measure_label": measure_label,
            }
        return {
            "chart_type": "table", "label": "Table",
            "reason": "no compatible chart for this shape",
            "x": None, "y": None, "results": frame[:10], "compatible": [],
            "measure_label": measure_label,
        }

    x, y = columns[0], columns[1]
    n_groups = len(frame)
    compatible = _compatible(op, intent.get("wants_share"), n_groups)
    reasons = {
        "bar_horizontal": "ranked comparison — names read best on a horizontal bar",
        "line": "ordered axis — a line shows the movement over time",
        "pie": "composition question over few groups — a share chart fits",
        "bar": "category comparison — bars compare the values directly",
        "histogram": "single measure — its distribution shows the spread",
    }
    if op == "ranking":
        chart_type = "bar_horizontal"
    elif op in _TREND_OPS:
        chart_type = "line"
    elif intent.get("wants_share") and n_groups <= 8:
        chart_type = "pie"
    else:
        chart_type = "bar"
    labels = {
        "bar_horizontal": "Horizontal bar", "line": "Line", "pie": "Donut",
        "bar": "Bar", "histogram": "Histogram",
    }
    return {
        "chart_type": chart_type,
        "label": labels.get(chart_type, chart_type),
        "reason": reasons.get(chart_type, "best fit for the result shape"),
        "x": x,
        "y": y,
        "results": frame[:10],
        "compatible": [c for c in compatible if c != chart_type][:3],
        "measure_label": measure_label,
    }


def build_why(intent, frame, columns, entity_label, measure_label, based_on,
              confidence, issues) -> dict:
    limitations = list(issues)
    if not frame:
        limitations.append("The query returned no rows, so no conclusion can be drawn.")
    limitations.append("Associations describe this dataset only and do not establish causation.")
    if frame and len(columns) >= 2:
        names = list(frame[0].keys())
        what = (
            f"Ranked {len(frame)} {_plural(entity_label)} by {measure_label}; "
            f"{names[0]} '{frame[0][names[0]]}' leads with {_fmt(frame[0][names[1]])}."
        )
    elif frame:
        what = "Computed a single summary value over the connected data."
    else:
        what = "The analysis produced no result to explain."
    factors = []
    if len(frame) > 1:
        factors = [f"differences across {_plural(entity_label)}"]
    return {
        "what_happened": what,
        "why_it_matters": (
            f"Answers the question directly from {based_on or 'the returned'} "
            f"records in the connected source."
        ),
        "evidence": {
            "tables": [entity_label],
            "columns": columns[:10],
            "row_count": len(frame),
            "sql": None,
        },
        "contributing_factors": factors,
        "comparisons": [],
        "confidence": confidence,
        "limitations": limitations,
    }


def analyze_result(ir, columns, rows, goal="", sql="", row_count=0) -> dict:
    """Validate, repair and describe a result. Returns the canonical envelope."""
    columns = list(columns or [])
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    based_on = int(row_count) if row_count else len(rows)

    intent = extract_intent(ir, goal)
    profile = profile_columns(columns, rows)

    issues = []
    repaired = False
    final_rows = rows
    final_columns = columns
    expected_granularity = "row_level"
    op = intent["operation"]
    entity_label = _entity_label(intent)

    key_col = _resolve_entity_key(intent, columns, rows, profile)
    label_col = _resolve_label(intent, columns, rows, key_col, profile) if key_col else None
    measure_col = _resolve_measure(intent, columns, rows, profile)
    aggregation = (intent.get("metric") or {}).get("aggregation") or (
        "SUM" if measure_col else "COUNT"
    )

    if op in _GROUPING_OPS and intent.get("entity") is not None and key_col:
        expected_granularity = f"one row per {entity_label}"
        groups = {str(r.get(key_col)) for r in rows if r.get(key_col) is not None}
        n_groups = len(groups)
        if n_groups and len(rows) > n_groups:
            agg = _aggregate_rows(rows, key_col, label_col, measure_col, aggregation)
            agg.sort(key=lambda a: a["value"], reverse=(intent["direction"] != "asc"))
            if intent.get("limit"):
                agg = agg[: int(intent["limit"])]
            label_name = label_col or "entity"
            measure_name = measure_col or ("count" if aggregation == "COUNT" else "value")
            final_rows = _frame(agg, label_name, measure_name)
            final_columns = [label_name, measure_name]
            repaired = True
            issues.append(
                f"the query returned transaction-level rows ({len(rows)} rows / "
                f"{n_groups} {_plural(entity_label)}); the result was re-aggregated "
                f"to the requested {expected_granularity}"
            )
    elif op in _TREND_OPS and profile["datetime"]:
        expected_granularity = "one row per period"
    elif op == "distribution" and profile["numeric"] and not profile["text"]:
        expected_granularity = "distribution over the measure"

    if not repaired and op == "ranking" and measure_col and measure_col in final_columns:
        limit = intent.get("limit") or 10
        final_rows = sorted(
            final_rows,
            key=lambda r: _to_float(r.get(measure_col)) or 0,
            reverse=(intent["direction"] != "asc"),
        )[: int(limit)]
    elif not repaired and op in _TREND_OPS and profile["datetime"]:
        tcol = profile["datetime"][0]
        final_rows = sorted(final_rows, key=lambda r: str(r.get(tcol) or ""))

    valid = bool(final_rows) and not (op in _GROUPING_OPS and intent.get("entity") and not key_col)
    if not final_rows:
        issues.append("the query returned no rows")

    measure_label = _measure_label(intent, measure_col, aggregation)
    confidence = "high" if valid and not repaired and len(final_rows) >= 3 else (
        "medium" if valid else "low"
    )

    if op in _TREND_OPS:
        answer = synthesize_trend_answer(final_rows, measure_label, entity_label)
    else:
        answer = synthesize_answer(final_rows, measure_label, entity_label)
    story = build_story(final_rows, measure_label, entity_label, based_on, op)
    chart_spec = select_visualization(intent, final_columns, final_rows, measure_label)
    why = build_why(
        intent, final_rows, final_columns, entity_label, measure_label,
        based_on, confidence, issues,
    )
    why["evidence"]["sql"] = sql or None

    analysis = {
        "based_on": based_on,
        "result_count": len(final_rows),
        "entity": entity_label,
        "entity_count": len(final_rows) if len(final_columns) >= 2 else None,
        "measure_label": measure_label,
        "measure_column": measure_col,
        "dimension_columns": [c for c in final_columns if c != measure_col],
        "aggregation": aggregation,
        "operation": op,
        "granularity": expected_granularity,
        "repaired": repaired,
        "confidence": confidence,
    }

    return {
        "data": final_rows,
        "columns": final_columns,
        "valid": valid,
        "repaired": repaired,
        "issues": issues,
        "granularity": {
            "expected": expected_granularity,
            "actual": "row_level" if len(final_columns) == len(columns) and not repaired else expected_granularity,
            "ok": valid,
        },
        "intent": intent,
        "chart_spec": chart_spec,
        "answer": answer,
        "story": story,
        "why": why,
        "analysis": analysis,
        "consistency": {
            "consistent": valid and not issues,
            "issues": issues,
            "chart_spec": chart_spec,
        },
    }