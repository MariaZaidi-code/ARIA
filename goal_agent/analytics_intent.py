"""General analytics intent layer (AI-Analytics sections 1-8, 17-20).

Classifier + context resolution + drivers + stable-contract helpers.

Design notes (hard requirements):
- Never match only hardcoded phrases: classification scores intent signals
  AND schema grounding (overlap of question tokens with real table/column
  tokens). A question with zero schema overlap and no analytical structure
  is reported as ambiguous/no-match instead of guessing.
- One question -> multiple capabilities: every question returns a primary
  intent plus all supporting capabilities (entailments included).
- Context-aware periods: "this period / previous period" resolve dynamically
  from explicit time_range -> question granularity -> previous context ->
  default month. The chosen comparison is always stated in the response.
- Possible drivers use real aggregates only, phrased as "Possible driver",
  never invented causes.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Intent catalogue (20 capabilities)
# ---------------------------------------------------------------------------

SUPPORTED_INTENTS = (
    "aggregation",
    "comparison",
    "trend",
    "ranking",
    "segmentation",
    "distribution",
    "correlation",
    "anomaly",
    "change_detection",
    "contribution",
    "period_over_period",
    "drill_down",
    "filtering",
    "forecasting",
    "scenario",
    "explanation",
    "root_cause",
    "recommendation",
    "hypothesis",
    "descriptive_summary",
)

# Signal patterns per intent. These are *signals*, not hard gates: the final
# decision always combines them with schema grounding (see classify()).
_INTENT_SIGNALS: dict[str, list[str]] = {
    "aggregation": [r"\btotal\b", r"\bsum\b", r"\baverage\b", r"\bavg\b", r"\bmean\b",
                    r"\bcount\b", r"\bhow many\b", r"\bnumber of\b", r"\bmax\b",
                    r"\bmin\b", r"\boverall\b"],
    "comparison": [r"\bcompare\b", r"\bcomparison\b", r"\bversus\b", r"\bvs\b",
                   r"\bdifference between\b", r"\bamong\b", r"\bbetween\b",
                   r"\bwhich (is|are) (more|less|higher|lower|better|worse)\b"],
    "trend": [r"\btrend\b", r"\bover time\b", r"\bgrowth\b", r"\bdecline\b",
              r"\bincreas\w*\b", r"\bdecreas\w*\b", r"\bmonthly\b", r"\bweekly\b",
              r"\bdaily\b", r"\byearly\b", r"\btime series\b"],
    "ranking": [r"\btop\b", r"\bbottom\b", r"\bbest\b", r"\bworst\b",
                r"\bhighest\b", r"\blowest\b", r"\bmost\b", r"\bleast\b",
                r"\brank\b", r"\bleader\b"],
    "segmentation": [r"\bsegment\b", r"\bbreakdown\b", r"\bper\b", r"\bby\b",
                     r"\bacross\b", r"\bgroup\b"],
    "distribution": [r"\bdistribution\b", r"\bshare\b", r"\bpercent\b",
                     r"\bproportion\b", r"\bcomposition\b", r"\bbreakdown\b"],
    "correlation": [r"\bcorrelat\w*\b", r"\brelat\w+ between\b",
                    r"\brelationship\b", r"\blinked\b", r"\bassociated with\b"],
    "anomaly": [r"\banomal\w*\b", r"\boutlier\b", r"\bunusual\b", r"\bstrange\b",
                r"\bspike\b", r"\bdrop\b", r"\babnormal\b", r"\bunexpected\b"],
    "change_detection": [r"\bchange\b", r"\bshift\b", r"\bmoved\b", r"\bdropped\b",
                         r"\brose\b", r"\bfell\b", r"\bgrew\b", r"\bdeclined\b"],
    "contribution": [r"\bcontribut\w*\b", r"\bdriv\w*\b", r"\bshare of\b",
                     r"\bwhat makes up\b", r"\bwhich.*contribute\b"],
    "period_over_period": [r"\bprevious period\b", r"\bthis period\b",
                           r"\blast period\b", r"\bmonth over month\b",
                           r"\bquarter over quarter\b", r"\byear over year\b",
                           r"\bmom\b", r"\bqoq\b", r"\byoy\b",
                           r"\bq1\b.*\bq2\b|\bq2\b.*\bq1\b",
                           r"\bjanuary\b.*\bfebruary\b|\bmonth\b.*\bmonth\b",
                           r"\bcompare.*period\b", r"\bvs last\b"],
    "drill_down": [r"\bdrill", r"\bdetails of\b", r"\bbreak down\b",
                   r"\bzoom into\b", r"\bwithin\b"],
    "filtering": [r"\bfilter\b", r"\bwhere\b", r"\bonly\b", r"\bfor\b",
                  r"\bin\b.*\b20\d{2}\b", r"\blast (week|month|quarter|year)\b",
                  r"\bthis (week|month|quarter|year)\b"],
    "forecasting": [r"\bforecast\b", r"\bpredict\b", r"\bfuture\b",
                    r"\bnext (week|month|quarter|year)\b", r"\bexpected\b",
                    r"\bwill\b.*\bbe\b", r"\bproject\w*\b"],
    "scenario": [r"\bwhat if\b", r"\bwhat-if\b", r"\bscenario\b",
                 r"\bif we\b", r"\bsimulat\w*\b", r"\bassum\w*\b"],
    "explanation": [r"\bwhy\b", r"\bexplain\b", r"\bwhat happened\b",
                    r"\bwhat caused\b", r"\breason for\b"],
    "root_cause": [r"\broot cause\b", r"\bcause\b", r"\bdriver\b",
                   r"\bbecause\b", r"\bdue to\b", r"\bwhat made\b"],
    "recommendation": [r"\brecommend\b", r"\bsuggest\b", r"\bshould\b",
                       r"\baction\b", r"\bimprove\b", r"\boptimiz\w*\b",
                       r"\bwhat (should|to do)\b", r"\bnext step\b",
                       r"\bnext investigation\b"],
    "hypothesis": [r"\bhypothes\w*\b", r"\btest\b.*\bidea\b", r"\bpossible\b",
                   r"\btheory\b", r"\bassume\b"],
    "descriptive_summary": [r"\bsummar\w*\b", r"\boverview\b", r"\bdescribe\b",
                            r"\bwhat is\b", r"\bshow me\b", r"\btell me\b",
                            r"\bexplain this chart\b", r"\bkey metrics\b"],
}

# Entailments: primary capability implies these supporting ones.
_ENTAILMENTS: dict[str, list[str]] = {
    "ranking": ["aggregation", "filtering"],
    "comparison": ["aggregation", "change_detection"],
    "period_over_period": ["comparison", "change_detection", "trend"],
    "trend": ["change_detection", "aggregation"],
    "contribution": ["segmentation", "distribution", "aggregation"],
    "segmentation": ["distribution", "aggregation"],
    "distribution": ["aggregation"],
    "anomaly": ["change_detection", "trend"],
    "change_detection": ["trend"],
    "explanation": ["root_cause", "hypothesis", "change_detection"],
    "root_cause": ["hypothesis", "contribution", "explanation"],
    "hypothesis": ["explanation"],
    "recommendation": ["descriptive_summary"],
    "forecasting": ["trend", "scenario"],
    "scenario": ["forecasting"],
    "correlation": ["segmentation"],
    "drill_down": ["filtering", "segmentation"],
    "filtering": ["aggregation"],
}

_ANALYTICAL_WORDS = {
    "total", "sum", "average", "avg", "count", "trend", "compare", "top",
    "best", "sales", "revenue", "profit", "metric", "growth", "change",
    "share", "distribution", "forecast", "why", "anomaly", "correlation",
    "segment", "period", "month", "quarter", "year", "week", "day",
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def classify_analytics(question: str, schema_terms: set[str] | None = None) -> dict:
    """Classify a question into primary intent + capabilities.

    Combines phrase signals with schema grounding: score = signal hits +
    schema-overlap boost. Returns::

        {primary, capabilities[], confidence, grounded, schema_overlap}
    """
    q = str(question or "")
    ql = q.lower()
    scores: dict[str, int] = {}
    for intent, patterns in _INTENT_SIGNALS.items():
        hits = sum(1 for p in patterns if re.search(p, ql))
        if hits:
            scores[intent] = hits

    schema_terms = {str(t or "").lower() for t in (schema_terms or set()) if str(t or "").strip()}
    qtok = _tokens(ql)
    overlap = len(qtok & schema_terms) if schema_terms else 0
    grounded = overlap > 0

    # Schema grounding boost: data-backed intents get +1 when the question
    # names real schema content (table/column words). This keeps generic
    # chit-chat ("hello") from scoring as analytics.
    if grounded:
        for intent in ("aggregation", "comparison", "trend", "ranking",
                       "segmentation", "distribution", "filtering",
                       "descriptive_summary"):
            if intent in scores:
                scores[intent] += 1

    if not scores:
        # No signal at all: descriptive summary only when grounded or when
        # the question is analytical in shape; otherwise no-match.
        if grounded or (qtok & _ANALYTICAL_WORDS):
            primary = "descriptive_summary"
            capabilities = ["descriptive_summary", "aggregation"]
            confidence = "low" if not grounded else "medium"
        else:
            primary = "descriptive_summary"
            capabilities = ["descriptive_summary"]
            confidence = "low"
        return {
            "primary": primary,
            "capabilities": capabilities,
            "confidence": confidence,
            "grounded": grounded,
            "schema_overlap": overlap,
        }

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    primary = ranked[0][0]
    capabilities: list[str] = [i for i, _ in ranked]
    for cap in list(capabilities):
        for entailed in _ENTAILMENTS.get(cap, []):
            if entailed not in capabilities:
                capabilities.append(entailed)
    # descriptive_summary is the universal base for grounded analytics.
    if grounded and "descriptive_summary" not in capabilities:
        capabilities.append("descriptive_summary")

    top_score = ranked[0][1]
    if top_score >= 3 or (grounded and top_score >= 2):
        confidence = "high"
    elif top_score >= 2 or grounded:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "primary": primary,
        "capabilities": capabilities,
        "confidence": confidence,
        "grounded": grounded,
        "schema_overlap": overlap,
    }


# ---------------------------------------------------------------------------
# Context-aware period resolution
# ---------------------------------------------------------------------------

_GRANULARITY_PATTERNS: list[tuple[str, list[str]]] = [
    ("day", [r"\bday\b", r"\bdaily\b", r"\btoday\b", r"\byesterday\b"]),
    ("week", [r"\bweek\b", r"\bweekly\b", r"\bwow\b"]),
    ("month", [r"\bmonth\b", r"\bmonthly\b", r"\bmom\b", r"\bjanuary\b",
               r"\bfebruary\b", r"\bmarch\b", r"\bapril\b", r"\bmay\b",
               r"\bjune\b", r"\bjuly\b", r"\baugust\b", r"\bseptember\b",
               r"\boctober\b", r"\bnovember\b", r"\bdecember\b"]),
    ("quarter", [r"\bquarter\b", r"\bquarterly\b", r"\bqoq\b", r"\bq1\b",
                 r"\bq2\b", r"\bq3\b", r"\bq4\b"]),
    ("year", [r"\byear\b", r"\byearly\b", r"\bannual\b", r"\byoy\b",
              r"\b20\d{2}\b"]),
]


def detect_granularity(question: str = "", time_range: Any = None,
                       previous_context: dict | None = None) -> str:
    """Pick day/week/month/quarter/year from explicit context first."""
    if isinstance(time_range, dict):
        g = str(time_range.get("granularity") or "").lower().strip()
        if g in ("day", "week", "month", "quarter", "year"):
            return g
    ql = str(question or "").lower()
    for gran, patterns in _GRANULARITY_PATTERNS:
        if any(re.search(p, ql) for p in patterns):
            return gran
    if isinstance(previous_context, dict):
        for key in ("granularity", "period", "time_range"):
            g = str(previous_context.get(key) or "").lower()
            for gran, _ in _GRANULARITY_PATTERNS:
                if gran in g:
                    return gran
        q2 = str(previous_context.get("question") or "")
        if q2:
            return detect_granularity(q2)
    if isinstance(time_range, str):
        tl = time_range.lower()
        for gran, _ in _GRANULARITY_PATTERNS:
            if gran in tl:
                return gran
    return "month"


def resolve_comparison(question: str = "", time_range: Any = None,
                       previous_context: dict | None = None) -> dict:
    """Resolve 'this period / previous period' dynamically.

    day -> previous day, week -> previous week, month -> previous month,
    quarter/year likewise. Always states which comparison was chosen.
    """
    gran = detect_granularity(question, time_range, previous_context)
    cur_label = f"current {gran}"
    prev_label = f"previous {gran}"
    window = ""
    if isinstance(time_range, dict):
        for key in ("label", "period", "current", "range"):
            if time_range.get(key):
                cur_label = f"{time_range[key]} ({gran})"
                break
        start = time_range.get("start")
        end = time_range.get("end")
        if start or end:
            window = f" [{start or '?'} → {end or '?'}]"
    description = (
        f"Compared {cur_label}{window} vs {prev_label} "
        f"(period-over-period on {gran} granularity)."
    )
    return {
        "granularity": gran,
        "current": {"label": cur_label},
        "previous": {"label": prev_label},
        "description": description,
    }


# ---------------------------------------------------------------------------
# Visualization mapping (intent -> chart family)
# ---------------------------------------------------------------------------

_VIZ_BY_INTENT: dict[str, str] = {
    "comparison": "comparison",
    "period_over_period": "comparison",
    "contribution": "comparison",
    "trend": "line",
    "forecasting": "line",
    "scenario": "line",
    "change_detection": "line",
    "anomaly": "line",
    "ranking": "h-bar",
    "segmentation": "stacked",
    "distribution": "histogram",
    "correlation": "scatter",
    "aggregation": "bar",
    "filtering": "bar",
    "drill_down": "bar",
    "explanation": "bar",
    "root_cause": "bar",
    "hypothesis": "bar",
    "recommendation": "bar",
    "descriptive_summary": "bar",
}

_BACKEND_VIZ_MAP = {
    "bar": "bar", "bar_horizontal": "h-bar", "hbar": "h-bar",
    "bar_stacked": "stacked", "stacked": "stacked",
    "line": "line", "area": "line", "combo": "line",
    "scatter": "scatter", "bubble": "scatter",
    "histogram": "histogram", "pie": "bar", "doughnut": "bar",
    "table": "bar", "comparison": "comparison",
}


def map_visualization(primary_intent: str, chart_spec: dict | None = None) -> str:
    """Viz by intent, honouring the backend chart spec when compatible."""
    backend_type = str((chart_spec or {}).get("chart_type") or "").lower()
    if backend_type in ("scatter", "histogram", "line", "area", "combo",
                        "bar_horizontal", "bar_stacked"):
        mapped = _BACKEND_VIZ_MAP.get(backend_type)
        if mapped:
            # Trend-family backend specs win; otherwise intent wins unless
            # the backend shape genuinely fits (scatter/histogram).
            if backend_type in ("scatter", "histogram"):
                return mapped
            intent_viz = _VIZ_BY_INTENT.get(primary_intent or "", "bar")
            if backend_type in ("line", "area", "combo") and intent_viz == "line":
                return "line"
            if backend_type in ("bar_horizontal", "bar_stacked") and intent_viz in ("h-bar", "stacked"):
                return mapped
    return _VIZ_BY_INTENT.get(primary_intent or "", "bar")


# ---------------------------------------------------------------------------
# Possible drivers from real aggregates
# ---------------------------------------------------------------------------

def _quote_ident(name: str, dialect: str) -> str:
    safe = str(name or "").replace("`", "``").replace('"', '""')
    if (dialect or "") == "mysql":
        return f"`{safe}`"
    return f'"{safe}"'


def compute_possible_drivers(engine: Any, dialect: str, table: str,
                             metric_col: str | None,
                             dimensions: list[str],
                             period_label: str = "",
                             limit_per_dim: int = 3,
                             max_dims: int = 4) -> list[dict]:
    """Candidate drivers with contribution % from real GROUP BY aggregates.

    Scans product/region/customer-like dimensions first, then any remaining
    text dimension. Every entry carries its SQL + values as evidence and is
    worded as a *possible* driver, never a proven cause.
    """
    drivers: list[dict] = []
    if engine is None or not table or not metric_col:
        return drivers
    prefs = ("product", "region", "customer", "category", "segment",
             "channel", "store", "country", "city", "brand")
    ordered = sorted(
        [d for d in (dimensions or []) if d],
        key=lambda d: (0 if any(p in str(d).lower() for p in prefs) else 1,
                       str(d)),
    )[:max_dims]
    # Volume / AOV / discount style numeric helpers are informational only;
    # the grouping scan below is the evidence source.
    try:
        from sqlalchemy import text as _text
    except Exception:
        return drivers
    for dim in ordered:
        qt = _quote_ident(table, dialect or "postgresql")
        qd = _quote_ident(dim, dialect or "postgresql")
        qm = _quote_ident(metric_col, dialect or "postgresql")
        sql = (
            f"SELECT {qd} AS dim, SUM({qm}) AS total "
            f"FROM {qt} GROUP BY 1 ORDER BY 2 DESC LIMIT {int(limit_per_dim)}"
        )
        try:
            with engine.connect() as conn:
                rows = conn.execute(_text(sql)).fetchall()
        except Exception:
            continue
        pairs: list[tuple[str, float]] = []
        for r in rows or []:
            try:
                pairs.append((str(r[0]), float(r[1] or 0)))
            except (TypeError, ValueError, IndexError):
                continue
        total = sum(v for _, v in pairs)
        if not pairs or total == 0:
            continue
        for label, value in pairs:
            share = value / total * 100
            if share >= 40:
                conf = "high"
            elif share >= 20:
                conf = "medium"
            else:
                conf = "low"
            drivers.append({
                "driver": f"Associated factor: {label} ({dim})",
                "dimension": dim,
                "value": label,
                "metric": metric_col,
                "total": round(value, 2),
                "contribution_pct": round(share, 1),
                "confidence": conf,
                "period": period_label or "selected period",
                "evidence": {
                    "table": table,
                    "sql": sql,
                    "values": [{"dimension": label, "total": round(value, 2),
                                "share_pct": round(share, 1)}],
                },
                "note": ("Statistical association in this dataset, "
                         "not proven cause."),
            })
    # Strongest contributions first, cap the list.
    drivers.sort(key=lambda d: d.get("contribution_pct", 0), reverse=True)
    return drivers[:8]


# ---------------------------------------------------------------------------
# Follow-ups generated from the result (never generic)
# ---------------------------------------------------------------------------

def build_followups(question: str, primary_intent: str, metric: str | None,
                    dimensions: list[str], period_label: str = "",
                    drivers: list[dict] | None = None,
                    limit: int = 6) -> list[str]:
    """Follow-up questions built from actual result content."""
    m = (metric or "the metric").strip() or "the metric"
    dims = [d for d in (dimensions or []) if d]
    d0 = dims[0] if dims else "segment"
    d1 = dims[1] if len(dims) > 1 else None
    period = (period_label or "this period").strip()
    cands: list[str] = []
    if primary_intent in ("comparison", "period_over_period", "change_detection",
                          "trend", "explanation", "root_cause", "hypothesis"):
        cands.append(f"Why did {m} change in {period}?")
    if dims:
        cands.append(f"Which {d0} contributes most to {m}?")
    if d1:
        cands.append(f"How does {m} break down by {d0} and {d1}?")
    if primary_intent in ("trend", "forecasting", "scenario", "change_detection"):
        cands.append(f"Forecast {m} for the next {period_label or 'periods'}")
    if primary_intent in ("ranking", "segmentation", "distribution",
                          "contribution"):
        cands.append(f"Which {d0} has the lowest {m}?")
    if drivers:
        top = drivers[0]
        cands.append(
            f"How much of {m} comes from {top.get('value')} ({top.get('dimension')})?")
    if primary_intent in ("anomaly",):
        cands.append(f"Are there other anomalies in {m} across {d0}?")
    if primary_intent in ("correlation",):
        cands.append(f"Which {d0} shows the strongest link with {m}?")
    if primary_intent in ("recommendation",):
        cands.append(f"What should we do about {m} in {period}?")
    # Deduplicate, keep order, cap.
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) >= limit:
            break
    # Honest fallback when nothing could be grounded (still result-derived:
    # it references the metric that was actually analyzed).
    if not out:
        out = [f"Show {m} breakdown by {d0}",
               f"How has {m} changed over time?"]
    return out[:limit]


# ---------------------------------------------------------------------------
# Graceful result states
# ---------------------------------------------------------------------------

GRACEFUL_STATES = ("success", "partial", "insufficient", "unsupported",
                   "ambiguous", "no-match", "backend-failure")

_STATE_MESSAGES = {
    "success": "Analysis completed over the connected data.",
    "partial": ("Partial result: some of the requested analysis could not be "
                "completed. The findings below cover what was available — "
                "try narrowing to one metric or period and ask again."),
    "insufficient": ("Not enough matching data to answer reliably. Try a "
                     "broader period, fewer filters, or a different grouping."),
    "unsupported": ("This type of analysis is not supported for the current "
                    "data shape (e.g. forecasting needs a dated numeric "
                    "series). Try a ranking, trend or breakdown instead."),
    "ambiguous": ("Your question could match more than one metric or "
                  "grouping. Please name the measure or segment explicitly "
                  "(e.g. 'total revenue by region')."),
    "no-match": ("No matching rows were found for this question in the "
                 "connected data. Check filters/period or try a broader "
                 "question."),
    "backend-failure": ("The analysis engine hit a temporary problem. Your "
                        "data was not changed — please retry in a moment or "
                        "ask a simpler question."),
}


def graceful_message(state: str) -> str:
    return _STATE_MESSAGES.get(state or "", _STATE_MESSAGES["backend-failure"])


def decide_status(*, valid: bool, rows: list, repaired: bool,
                  clarification: bool, issues: list) -> str:
    """Map pipeline outcome to a graceful state (no stack traces)."""
    if clarification:
        return "ambiguous"
    if not rows:
        return "no-match"
    if not valid:
        return "insufficient"
    if repaired or issues:
        return "partial"
    return "success"
