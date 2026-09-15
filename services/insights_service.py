"""Insights business logic (services layer — canonical home).

Moved verbatim from api/insights_routes.py: pure detectors/formatters/chart
spec builders. The router re-exports every name imported from here, so
existing imports keep working. No FastAPI imports in this module.
"""
from __future__ import annotations

import logging
import math
import sqlite3
import statistics
import time
from datetime import datetime

from core.errors import DB_ERRORS, PURE_ERRORS, get_request_id, log_and_sanitize

log = logging.getLogger("aria.insights.service")

__all__ = ["CHART_SPEC_VOCAB", "_MAX_SPEC_ROWS", "_MAX_RAW_VALUES", "_safe_float", "_fmt", "_fmt_currency", "_fmt_pct", "_iqr_bands", "_sanitize_spec_rows", "_normalize_chart_spec", "_confidence_level", "_evidence_quality", "_capability_flags", "_histogram_bins", "_build_takeaways", "_enrich_insight", "_normalize_legacy_insight", "_translate_sql_for_sqlite"]


def _safe_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except (ValueError, TypeError) as exc:
        log.debug("safe float skipped: %s", exc)
        return None


def _fmt(v):
    if v is None:
        return "N/A"
    if isinstance(v, float):
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if abs(v) >= 1_000:
            return f"{v / 1_000:.1f}K"
        if abs(v) < 0.01 and v != 0:
            return f"{v:.4f}"
        return f"{v:,.2f}"
    return str(v)


def _fmt_currency(v):
    if v is None:
        return "N/A"
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:,.1f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:,.0f}K"
    return f"${v:,.0f}"


def _fmt_pct(v):
    if v is None:
        return "N/A"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def _iqr_bands(values):
    """Generic IQR fences with linear-interpolated quartiles.

    Returns (q1, q3, iqr, lower, upper, severe_lower, severe_upper) with
    1.5xIQR regular fences + 3.0xIQR severe tiers, or None when the series
    cannot support a band (too few finite values, non-finite spread, or
    iqr <= 0 e.g. flat series). Callers skip silently on None — no fake band.
    Pure math, no dataset assumptions.
    """
    try:
        nums = [float(v) for v in (values or []) if v is not None]
    except (ValueError, TypeError) as exc:
        log.debug("iqr band input skipped: %s", exc)
        return None
    nums = [v for v in nums if math.isfinite(v)]
    n = len(nums)
    if n < 4:
        return None
    s = sorted(nums)

    def _pct(p):
        pos = (n - 1) * p
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return s[lo]
        frac = pos - lo
        return s[lo] + (s[hi] - s[lo]) * frac

    try:
        q1 = float(_pct(0.25))
        q3 = float(_pct(0.75))
    except (ValueError, TypeError, IndexError) as exc:
        log.debug("iqr quartile skipped: %s", exc)
        return None
    if not (math.isfinite(q1) and math.isfinite(q3)):
        return None
    iqr = q3 - q1
    if not math.isfinite(iqr) or iqr <= 0:
        return None
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    severe_lower = q1 - 3.0 * iqr
    severe_upper = q3 + 3.0 * iqr
    if not all(math.isfinite(v) for v in (lower, upper, severe_lower, severe_upper)):
        return None
    return (q1, q3, iqr, lower, upper, severe_lower, severe_upper)


# ── n.txt-9: controlled chart vocabulary ─────────────────────────────────
# Backend emits ONLY {type,x,y,series,title,interactive,data}. The frontend
# renders this spec and never executes LLM-supplied frontend code.
# Provenance stays in this backend payload (admin/debug) — user-facing pages
# decide what to display; AI Analytics hides it.
CHART_SPEC_VOCAB = ("line", "bar", "area", "scatter", "pie", "donut", "histogram", "heatmap")
_MAX_SPEC_ROWS = 500
# Raw-value pulls for distribution statistics (IQR/outliers/CV/skew) are
# bounded samples, never full-column dumps: the detectors aggregate in Python
# (binned histograms ≤12 bins, scalar statistics) and the honest sample size
# travels with each insight. Full-dataset aggregates stay SQL-side wherever
# the detector shape allows (monthly sums, top-N, grouped averages).
_MAX_RAW_VALUES = 2000


def _sanitize_spec_rows(rows):
    """Validate chart data before it leaves the backend: dicts only, JSON-safe
    scalars, capped length. Never raises — returns [] when unusable so the
    frontend can show an insufficient-data state."""
    if not isinstance(rows, (list, tuple)):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        clean = {}
        for k, v in r.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean[k] = None
            elif isinstance(v, (str, int, float, bool)) or v is None:
                clean[k] = v
            else:
                clean[k] = str(v)
        out.append(clean)
        if len(out) >= _MAX_SPEC_ROWS:
            break
    return out


def _normalize_chart_spec(viz_type, viz_data, title=""):
    """Map internal detector viz types to the controlled vocabulary + infer
    x/y/series. Supported: line/bar/area/scatter/pie/donut/histogram/heatmap.
    Unknown types fall back to bar/line when the data shape fits, else the
    caller treats the spec as unsupported (frontend shows a graceful note)."""
    raw = (viz_type or "").lower()
    data = _sanitize_spec_rows(viz_data)
    vt = raw if raw in CHART_SPEC_VOCAB else ""
    if raw in ("leaderboard",):
        vt = "bar"
    elif raw in ("pie_share", "share"):
        vt = "pie"
    elif raw in ("box", "box_plot", "violin"):
        # No box-plot renderer in the controlled vocabulary: distribution
        # detail is preserved as a histogram (supported vocab).
        vt = "histogram"
    if not data:
        return {"type": vt or "bar", "x": None, "y": None, "series": [],
                "title": title or "", "interactive": True, "data": [],
                "unsupported": False, "insufficient": True}
    keys = list(data[0].keys())
    x = y = None
    series: list = []
    if vt in ("bar", "pie", "donut", "histogram") or not vt:
        if "name" in keys and "value" in keys:
            x, y, vt = "name", "value", vt or "bar"
        elif "period" in keys and "value" in keys:
            # Time-ordered bars render better as area/line unless caller said bar.
            x, y = "period", "value"
            vt = vt or "area"
        elif len(keys) >= 2:
            x, y = keys[0], keys[1]
            vt = vt or "bar"
        else:
            return {"type": "bar", "x": None, "y": None, "series": [],
                    "title": title or "", "interactive": True, "data": data,
                    "unsupported": False, "insufficient": True}
    elif vt in ("line", "area"):
        if "period" in keys and "value" in keys:
            x, y = "period", "value"
        elif len(keys) >= 2:
            x, y = keys[0], keys[1]
        # multi-series: extra numeric keys beyond x/y become toggleable
        # series so the frontend can render expected/band overlays. Bool
        # flags (e.g. anomaly) are excluded; any row carrying a real number
        # promotes the key (first-row-only checks would drop bands).
        series = [k for k in keys if k not in (x, y)
                and any(isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)
                        for r in data)]
        series = series[:8]
    elif vt == "scatter":
        if "table1" in keys and "table2" in keys:
            x, y = "table1", "table2"
        elif "x" in keys and "y" in keys:
            x, y = "x", "y"
        elif len(keys) >= 2:
            x, y = keys[0], keys[1]
    elif vt == "heatmap":
        if {"x", "y", "value"} <= set(keys):
            x, y, series = "x", "y", []
        elif len(keys) >= 3:
            x, y = keys[0], keys[1]
    if vt not in CHART_SPEC_VOCAB:
        return {"type": "bar", "x": x, "y": y, "series": series,
                "title": title or "", "interactive": True, "data": data,
                "unsupported": True, "insufficient": False}
    insufficient = (len(data) < 2 and vt in ("line", "area", "scatter")) or (len(data) < 1)
    return {"type": vt, "x": x, "y": y, "series": series,
            "title": title or "", "interactive": True, "data": data,
            "unsupported": False, "insufficient": insufficient}


# ── Generic per-insight contract (§§23-24,34) ─────────────────────────────
# All helpers are dataset-agnostic: no branching on table/column/metric
# names, no invented numbers. Everything derives from fields already
# present on the insight (or honest defaults when a detector provides no
# calibrated score).


def _confidence_level(conf) -> str:
    """Strong>=75, Moderate>=50, else Limited (from existing int only)."""
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return "Limited"
    if c >= 75:
        return "Strong"
    if c >= 50:
        return "Moderate"
    return "Limited"


def _evidence_quality(sample_size) -> str:
    """Generic count thresholds only: Strong>=100, Moderate>=30, else Limited."""
    try:
        n = int(sample_size) if sample_size is not None else 0
    except (TypeError, ValueError):
        return "Limited"
    if n >= 100:
        return "Strong"
    if n >= 30:
        return "Moderate"
    return "Limited"


def _capability_flags(sample_size) -> tuple:
    """scenario_supported / monitoring_supported via core/evidence.py + n>=10."""
    try:
        n = int(sample_size) if sample_size is not None else 0
    except (TypeError, ValueError):
        n = 0
    scen = mon = False
    try:
        from core.evidence import assess_evidence as _assess
        scen = _assess(n, "scenario").get("status") == "supported"
        mon = _assess(n, "monitoring").get("status") == "supported"
    except (ValueError, KeyError, TypeError, AttributeError, ImportError) as exc:
        log.debug("capability assess skipped: %s", exc)
        scen = n >= 10
        mon = n >= 10
    return bool(scen), bool(mon)


def _histogram_bins(vals, nbins: int = 12):
    """Generic value histogram {name, value} bins from raw numbers only."""
    try:
        nums = [float(v) for v in (vals or []) if v is not None]
    except (ValueError, TypeError) as exc:
        log.debug("histogram input skipped: %s", exc)
        return []
    nums = [v for v in nums if math.isfinite(v)]
    if not nums:
        return []
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    counts = [0] * nbins
    for v in nums:
        b = min(nbins - 1, max(0, int((v - lo) / span * nbins)))
        counts[b] += 1
    out = []
    for i in range(nbins):
        if not counts[i]:
            continue
        b_lo = lo + span * i / nbins
        b_hi = lo + span * (i + 1) / nbins
        out.append({"name": f"{_fmt(b_lo)}-{_fmt(b_hi)}", "value": counts[i]})
    return out


def _build_takeaways(evidence, affected_period, observations, support_metrics):
    """2-4 strings built ONLY from present numbers — skip missing, never invent.

    Primary sources: changePercent / baseline / currentValue / affectedPeriod.
    When fewer than 2 numeric takeaways exist, fill up to 2 with the
    detector's own observation strings (already evidence-backed, no new
    numbers invented). Capped at 4.
    """
    takeaways: list = []
    ev = evidence or {}
    cp = ev.get("changePercent")
    baseline = ev.get("baseline")
    current = ev.get("currentValue")
    try:
        if cp is not None:
            cp_f = float(cp)
            if math.isfinite(cp_f):
                takeaways.append(f"Changed {cp_f:+.1f}% versus the baseline.")
    except (TypeError, ValueError):
        pass
    try:
        if baseline is not None and current is not None:
            b_f, c_f = float(baseline), float(current)
            if math.isfinite(b_f) and math.isfinite(c_f):
                takeaways.append(f"Moved from {_fmt(b_f)} to {_fmt(c_f)}.")
        elif baseline is not None:
            b_f = float(baseline)
            if math.isfinite(b_f):
                takeaways.append(f"Baseline level: {_fmt(b_f)}.")
        elif current is not None:
            c_f = float(current)
            if math.isfinite(c_f):
                takeaways.append(f"Current level: {_fmt(c_f)}.")
    except (TypeError, ValueError):
        pass
    if affected_period:
        takeaways.append(f"Observed in {affected_period}.")
    # Fill to at least 2 with existing evidence strings (no new numbers).
    if len(takeaways) < 2:
        for s in list(observations or []) + list(support_metrics or []):
            if isinstance(s, str) and s.strip() and s not in takeaways:
                takeaways.append(s)
                if len(takeaways) >= 4:
                    break
    return takeaways[:4]


def _enrich_insight(ins: dict) -> dict:
    """Add generic contract fields to an already-shaped insight (idempotent).

    Adds: category, explanation, summary/description parity, confidence_level,
    evidence_quality, takeaways, recommendation, scenario_supported,
    monitoring_supported, associated_factors (only for real correlation
    evidence, else omitted). Ensures `visualization` exists via
    _normalize_chart_spec when only viz_type/viz_data are present.
    """
    if not isinstance(ins, dict):
        return ins
    itype = str(ins.get("type", "") or "")
    ins["category"] = itype.lower()
    desc = ins.get("description") or ins.get("summary") or ""
    if not ins.get("description") and ins.get("summary"):
        ins["description"] = ins.get("summary")
    if not ins.get("summary") and desc:
        ins["summary"] = desc
    ins["explanation"] = desc
    conf = ins.get("confidence")
    if not isinstance(conf, (int, float)) or not math.isfinite(float(conf)):
        conf = 50
        ins["confidence"] = conf
    else:
        conf = int(conf)
    ins["confidence_level"] = _confidence_level(conf)
    ev = ins.get("evidence") if isinstance(ins.get("evidence"), dict) else {}
    ss = ev.get("sampleSize")
    if ss is None:
        ss = ins.get("sample_size", ins.get("sampleSize"))
    ins["evidence_quality"] = _evidence_quality(ss)
    obs = ev.get("observations") or ins.get("observations") or []
    sup = ev.get("supportingMetrics") or ins.get("support_metrics") or []
    ins["takeaways"] = _build_takeaways(ev, ins.get("affectedPeriod"), obs, sup)
    # recommendation: reuse existing next-step / impact text, never invent.
    if not ins.get("recommendation"):
        nxt = ins.get("recommendedNextAnalysis") or {}
        rec = (nxt.get("question") if isinstance(nxt, dict) else "") or ins.get("next_question") or ""
        if rec:
            ins["recommendation"] = rec
    scen, mon = _capability_flags(ss)
    ins["scenario_supported"] = scen
    ins["monitoring_supported"] = mon
    # associated_factors only when real correlation evidence exists.
    t_low = itype.lower()
    if "correl" in t_low:
        src = (ins.get("source") or {}) if isinstance(ins.get("source"), dict) else {}
        tables = src.get("tables") or ins.get("source_tables") or []
        factors = [t for t in tables if isinstance(t, str) and t]
        if factors:
            ins["associated_factors"] = factors[:8]
    # visualization parity: map viz_type/viz_data -> visualization.
    if not isinstance(ins.get("visualization"), dict):
        vt = ins.get("viz_type", "bar")
        vd = ins.get("viz_data", [])
        ins["visualization"] = _normalize_chart_spec(vt, vd, ins.get("title", ""))
    return ins


def _normalize_legacy_insight(raw: dict) -> dict:
    """Normalize a B-shape raw detector dict to the full A-shape contract.

    Maps summary->description (keeps summary), viz_type/viz_data->
    visualization via _normalize_chart_spec (bounded 500/2000 caps), then
    enriches with the generic per-insight fields. Pure mapping — no
    dataset-specific literals, no invented numbers.
    """
    if not isinstance(raw, dict):
        return raw
    if isinstance(raw.get("visualization"), dict) and raw.get("description"):
        return _enrich_insight(raw)
    now = datetime.now().isoformat()
    title = raw.get("title", "")
    summary = raw.get("summary", "")
    viz_type = raw.get("viz_type", "bar")
    viz_data = raw.get("viz_data", [])
    spec = _normalize_chart_spec(viz_type, viz_data, title)
    ev_raw = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    sample_size = ev_raw.get("sampleSize", raw.get("sample_size"))
    table = raw.get("table", "")
    itype = raw.get("type", "")
    tags = [str(table)] if table else []
    if itype:
        tags.append(str(itype).lower())
    out = {
        "id": raw.get("id", f"ins_{now}"),
        "type": itype or "Trend",
        "severity": raw.get("severity", "low"),
        "title": title,
        "description": raw.get("description", summary),
        "summary": summary or raw.get("description", ""),
        "metric": raw.get("metric", ""),
        "metricValue": raw.get("metric_value", raw.get("metricValue")),
        "previousValue": raw.get("previous_value", raw.get("previousValue")),
        "magnitude": raw.get("magnitude", ""),
        "confidence": raw.get("confidence", 50),
        "detectedAt": raw.get("detectedAt", now),
        "affectedPeriod": raw.get("affectedPeriod", raw.get("affected_period", "")),
        "tags": tags,
        "evidence": {
            "observations": ev_raw.get("observations", raw.get("observations", [])),
            "supportingMetrics": ev_raw.get("supportingMetrics", raw.get("support_metrics", [])),
            "sampleSize": sample_size,
            "baseline": ev_raw.get("baseline", raw.get("baseline")),
            "currentValue": ev_raw.get("currentValue", raw.get("current_value")),
            "changePercent": ev_raw.get("changePercent", raw.get("change_pct", raw.get("changePercent"))),
        },
        "businessImpact": {
            "value": raw.get("impact_value", (raw.get("businessImpact") or {}).get("value") if isinstance(raw.get("businessImpact"), dict) else None),
            "direction": raw.get("impact_direction", "neutral"),
            "explanation": raw.get("impact_explanation", ""),
        },
        "recommendedNextAnalysis": {
            "question": raw.get("next_question", ""),
            "metric": raw.get("metric", ""),
            "dimensions": raw.get("next_dims", []),
        },
        "visualization": {
            "type": spec["type"],
            "x": spec["x"],
            "y": spec["y"],
            "series": spec["series"],
            "title": spec["title"],
            "interactive": spec["interactive"],
            "data": spec["data"],
            "insufficient": spec.get("insufficient", False),
            "unsupported": spec.get("unsupported", False),
        },
        "source": {
            "tables": raw.get("source_tables", ([table] if table else [])),
            "columns": raw.get("source_columns", []),
        },
    }
    # Preserve raw evidence extras (e.g. affectedValues) without overwriting.
    for k, v in ev_raw.items():
        if k not in out["evidence"]:
            out["evidence"][k] = v
    # Keep legacy viz keys for backward compatibility.
    out["viz_type"] = viz_type
    out["viz_data"] = _sanitize_spec_rows(viz_data)[:_MAX_SPEC_ROWS]
    return _enrich_insight(out)


# ── Insight Detection Engine ─────────────────────────────────────────────


def _translate_sql_for_sqlite(sql: str) -> str:
    """Translate the PG-isms used by InsightsEngine detectors to SQLite."""
    import re as _re

    sql = _re.sub(
        r"date_trunc\(\s*'month'\s*,\s*(.*?)\)",
        r"strftime('%Y-%m', \1)",
        sql,
        flags=_re.IGNORECASE,
    )
    return sql.replace("%s", "?")
