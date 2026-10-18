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
               r"\bdaily\b", r"\byearly\b", r"\btime series\b", r"\bhistory\b",
               r"\bhistorical\b", r"\bchanged?\b", r"\bchange\b.*\bover\b"],
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

# "Why did X drop?" phrasing: the causal question must outrank incidental
# signals like "last month" (a filtering pattern). A cause-question word
# plus a change word is a strong explanation/root-cause signal.
_WHY_RE = re.compile(
    r"\b(why|explain|what happened|what caused|reason for|root cause)\b",
    re.IGNORECASE)
_CHANGE_WORD_RE = re.compile(
    r"\b(drop|dropped|drops|dropping|fall|fell|falls|falling|decline|"
    r"declined|declines|declining|decrease|decreased|decreases|decreasing|"
    r"increase|increased|increases|increasing|rise|rose|rises|rising|"
    r"grew|grow|growth|change|changed|changes|shift|shifted|moved)\b",
    re.IGNORECASE)


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

    # "Why did it drop?" is a cause question, not a time filter. The phrase
    # "last month" also matches the filtering signal, so without this the
    # question classifies as filtering and no causal analysis runs.
    if _WHY_RE.search(ql) and _CHANGE_WORD_RE.search(ql):
        scores["explanation"] = scores.get("explanation", 0) + 1
        scores["root_cause"] = scores.get("root_cause", 0) + 1

    # Schema grounding boost: data-backed intents get +1 when the question
    # names real schema content (table/column words). This keeps generic
    # chit-chat ("hello") from scoring as analytics.
    if grounded:
        for intent in ("aggregation", "comparison", "trend", "ranking",
                       "segmentation", "distribution", "filtering",
                       "descriptive_summary", "explanation", "root_cause",
                       "hypothesis"):
            if intent in scores:
                scores[intent] += 1

    if not scores:
        # No signal at all: descriptive_summary is the universal fallback
        # (with low confidence when nothing grounds) — there is no separate
        # "no-match" primary; callers judge ambiguity via `grounded` /
        # `confidence` / schema_overlap.
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
    # Schema-qualified keys quote per segment ("sales"."employee"), so the
    # dot stays a schema separator. Bare names are unchanged.
    try:
        segs = [s for s in str(name or "").split(".") if s]
        if len(segs) > 1:
            if (dialect or "") == "mysql":
                return ".".join(f"`{s.replace('`', '``')}`" for s in segs)
            return ".".join(f'"{s.replace(chr(34), chr(34) + chr(34))}"'
                            for s in segs)
    except Exception:
        pass
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
# Period-over-period change decomposition ("why did X drop?")
# ---------------------------------------------------------------------------

_CLAUSE_WORDS = ("FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT")

_FALL_WORD_RE = re.compile(
    r"\b(drop|dropped|drops|dropping|fall|fell|falls|falling|decline|"
    r"declined|declines|declining|decrease|decreased|decreases|decreasing|"
    r"loss|lost|down)\b", re.IGNORECASE)
_RISE_WORD_RE = re.compile(
    r"\b(rise|rose|rises|rising|grew|grow|growth|increase|increased|"
    r"increases|increasing|jump|jumped|gain|gained|up)\b", re.IGNORECASE)

# A change decomposition only makes sense over a real time axis — reject
# category labels ("Chai") pretending to be periods.
_PERIOD_LABEL_RE = re.compile(
    r"^(?:\d{4}(?:[-/]\d{1,2}){0,2}"
    r"|\d{4}[- ]?q[1-4]"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    r"(?:\s+\d{2,4})?)$",
    re.IGNORECASE)

_MONTH_NAMES_FULL = ("January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November",
                     "December")


def _display_period(label: Any) -> str:
    """'1998-05' -> 'May 1998'; anything else stays as-is."""
    try:
        from datetime import datetime as _dt
        s = str(label or "").strip()
        for fmt, cut in (("%Y-%m-%d", 10), ("%Y/%m/%d", 10),
                         ("%Y-%m", 7), ("%Y/%m", 7)):
            try:
                dt = _dt.strptime(s[:cut], fmt)
                return f"{_MONTH_NAMES_FULL[dt.month - 1]} {dt.year}"
            except ValueError:
                continue
    except Exception:
        pass
    return str(label or "")


def _human_col(name: Any) -> str:
    """'last_name' -> 'Last name' (display label for a raw column)."""
    toks = [t for t in re.split(r"[^a-zA-Z0-9]+", str(name or "")) if t]
    if not toks:
        return str(name or "")
    first = toks[0][:1].upper() + toks[0][1:].lower()
    rest = [t.lower() for t in toks[1:]]
    return " ".join([first] + rest)


def _fmt_compact(v: Any) -> str:
    """Human-scale magnitude: 12345 -> '12.3K', 4.5 -> '4.5'."""
    n = _hyp_num(v)
    if n is None:
        return ""
    a = abs(n)
    if a >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"{n / 1_000:.1f}K"
    if a >= 10:
        return f"{n:.0f}"
    return f"{n:.1f}"


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split on `sep` only at paren depth 0 (quote-aware)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i, n = 0, len(str(s or ""))
    text = str(s or "")
    in_s = in_d = in_b = False
    while i < n:
        ch = text[i]
        if in_s:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    buf.append(text[i + 1]); i += 2; continue
                in_s = False
        elif in_d:
            buf.append(ch)
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    buf.append(text[i + 1]); i += 2; continue
                in_d = False
        elif in_b:
            buf.append(ch)
            if ch == "`":
                if i + 1 < n and text[i + 1] == "`":
                    buf.append(text[i + 1]); i += 2; continue
                in_b = False
        else:
            if ch == "'":
                in_s = True; buf.append(ch)
            elif ch == '"':
                in_d = True; buf.append(ch)
            elif ch == "`":
                in_b = True; buf.append(ch)
            elif ch == "(":
                depth += 1; buf.append(ch)
            elif ch == ")":
                depth = max(0, depth - 1); buf.append(ch)
            elif depth == 0 and text.startswith(sep, i):
                parts.append("".join(buf)); buf = []; i += len(sep); continue
            else:
                buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _normalize_sql(sql: str) -> str:
    """Collapse whitespace outside string/quoted identifiers, strip ';'."""
    text = str(sql or "").strip().rstrip(";").strip()
    out: list[str] = []
    in_s = in_d = in_b = False
    ws = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_s:
            out.append(ch)
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    out.append(text[i + 1]); i += 2; continue
                in_s = False
        elif in_d:
            out.append(ch)
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    out.append(text[i + 1]); i += 2; continue
                in_d = False
        elif in_b:
            out.append(ch)
            if ch == "`":
                if i + 1 < n and text[i + 1] == "`":
                    out.append(text[i + 1]); i += 2; continue
                in_b = False
        else:
            if ch == "'":
                in_s = True; out.append(ch)
            elif ch == '"':
                in_d = True; out.append(ch)
            elif ch == "`":
                in_b = True; out.append(ch)
            elif ch.isspace():
                if not ws and out:
                    out.append(" ")
                ws = True
                i += 1
                continue
            else:
                out.append(ch)
        ws = False
        i += 1
    return "".join(out).strip()


def _sql_sections(sql: str) -> dict:
    """Top-level clause slices of a single SELECT statement."""
    s = _normalize_sql(sql)
    su = s.upper()
    depth = 0
    in_s = in_d = in_b = False
    found: list[tuple[int, str]] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if in_s:
            if ch == "'" and not (i + 1 < n and s[i + 1] == "'"):
                in_s = False
            elif ch == "'" and i + 1 < n and s[i + 1] == "'":
                i += 2; continue
        elif in_d:
            if ch == '"' and not (i + 1 < n and s[i + 1] == '"'):
                in_d = False
            elif ch == '"' and i + 1 < n and s[i + 1] == '"':
                i += 2; continue
        elif in_b:
            if ch == "`" and not (i + 1 < n and s[i + 1] == "`"):
                in_b = False
            elif ch == "`" and i + 1 < n and s[i + 1] == "`":
                i += 2; continue
        else:
            if ch == "'":
                in_s = True
            elif ch == '"':
                in_d = True
            elif ch == "`":
                in_b = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and ch.isalpha():
                matched = False
                for w in _CLAUSE_WORDS:
                    if su.startswith(w, i):
                        before = su[i - 1] if i > 0 else " "
                        end = i + len(w)
                        after = su[end] if end < n else " "
                        if (before.isalnum() or before == "_") or \
                           (after.isalnum() or after == "_"):
                            continue
                        found.append((i, w))
                        i = end
                        matched = True
                        break
                if matched:
                    continue
        i += 1
    found.sort()
    sections: dict[str, str] = {}
    first = found[0][0] if found else n
    sections["select"] = s[len("SELECT"):first] if su.startswith("SELECT") else s[:first]
    for idx, (pos, word) in enumerate(found):
        start = pos + len(word)
        end = found[idx + 1][0] if idx + 1 < len(found) else n
        sections[word.lower().replace(" ", "_")] = s[start:end]
    return sections


_AGG_WRAP_RE = re.compile(
    r"^\s*(SUM|AVG|COUNT|MIN|MAX)\s*\((.*)\)\s*$",
    re.DOTALL | re.IGNORECASE)


def _split_agg(expr: str) -> tuple[str, str]:
    """'SUM(a * b) AS x' style already stripped -> ('SUM', 'a * b')."""
    m = _AGG_WRAP_RE.match(str(expr or ""))
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return "SUM", str(expr or "").strip()


def _pick_period_value(per: dict, label: str) -> float | None:
    """Value for a period label, tolerating date-vs-string key shapes."""
    if label in per:
        return per[label]
    for k, v in per.items():
        ks = str(k)
        if ks == label or (len(ks) >= 4 and (ks.startswith(label[:7])
                                             or label.startswith(ks))):
            return v
    return None


def compute_change_drivers(engine: Any, dialect: str, sql_used: str,
                           series: list, dims: list | None = None,
                           measure_alias: str | None = None,
                           time_alias: str | None = None,
                           question: str = "",
                           metric_label: str = "",
                           limit_rows: int = 6,
                           max_dims: int = 4,
                           row_cap: int = 500) -> dict:
    """Decompose a period-over-period *change* by real segment breakdowns.

    Reuses the executed query's FROM clause and time expression, so the
    numbers reconcile with the result the user already sees, then pivots
    each segment's current vs previous period value. Returns::

        {"drivers": [...], "change": {...} | None}

    Every entry is an association in the data — never a proven cause.
    """
    out: dict = {"drivers": [], "change": None}
    try:
        pairs: list[tuple[str, float]] = []
        for item in (series or []):
            try:
                lb, v = item
                fv = float(v)
                if fv != fv:
                    continue
                pairs.append((str(lb), fv))
            except (TypeError, ValueError):
                continue
        if engine is None or len(pairs) < 2:
            return out
        if sum(1 for lb, _ in pairs if _PERIOD_LABEL_RE.match(lb)) < 2:
            return out
        sections = _sql_sections(sql_used)
        select_items = _split_top_level(sections.get("select", ""))
        measure_expr = None
        time_expr = None
        alias_re = re.compile(r"\bAS\s+[\w\".`\[\]]+\s*$", re.IGNORECASE)
        for item in select_items:
            m = alias_re.search(item)
            if not m:
                continue
            expr = item[:m.start()].strip()
            alias = item[m.start():].strip()[2:].strip().strip('"`[]')
            if measure_alias and alias.lower() == str(measure_alias).lower():
                measure_expr = expr
            elif time_alias and alias.lower() == str(time_alias).lower():
                time_expr = expr
        if not measure_expr or not time_expr:
            return out
        agg, inner = _split_agg(measure_expr)
        if inner == "*":
            value_expr = "COUNT(*)"
        elif agg == "COUNT":
            value_expr = f"COUNT({inner})"
        else:
            value_expr = f"{agg}({inner})"
        from_clause = str(sections.get("from", "") or "").strip()
        if not from_clause:
            return out

        diffs: list[tuple[int, float, str, str]] = []
        for i in range(1, len(pairs)):
            plab, pv = pairs[i - 1]
            clab, cv = pairs[i]
            diffs.append((i, cv - pv, plab, clab))
        if not diffs:
            return out
        q = str(question or "")
        if _RISE_WORD_RE.search(q) and not _FALL_WORD_RE.search(q):
            idx, delta, plab, clab = max(diffs, key=lambda t: t[1])
            direction = "rise"
        else:
            neg = [t for t in diffs if t[1] < 0]
            if neg:
                idx, delta, plab, clab = min(neg, key=lambda t: t[1])
                direction = "drop"
            else:
                idx, delta, plab, clab = max(diffs, key=lambda t: abs(t[1]))
                direction = "rise" if delta > 0 else "drop"
        cur_v, prev_v = pairs[idx][1], pairs[idx - 1][1]
        total_delta = cur_v - prev_v
        change = {
            "direction": direction,
            "current": _display_period(clab),
            "previous": _display_period(plab),
            "current_label": clab,
            "previous_label": plab,
            "current_total": round(cur_v, 2),
            "previous_total": round(prev_v, 2),
            "delta": round(total_delta, 2),
            "change_pct": (round(total_delta / abs(prev_v) * 100.0, 1)
                           if prev_v else None),
        }
        out["change"] = change
        if not total_delta:
            return out
        try:
            from sqlalchemy import text as _text
        except Exception:
            return out
        word = "fall" if direction == "drop" else "rise"
        drivers: list[dict] = []
        for dim in (dims or [])[:max_dims]:
            if isinstance(dim, (tuple, list)) and len(dim) >= 2:
                tbl, col = str(dim[0] or "").strip(), str(dim[1] or "").strip()
            else:
                tbl, col = "", str(dim or "").strip()
            if not col or _followup_is_id_like(col):
                continue
            qcol = _quote_ident(f"{tbl}.{col}" if tbl else col,
                                dialect or "postgresql")
            sql_dim = (
                f"SELECT {qcol} AS dim, {time_expr} AS p, {value_expr} AS v "
                f"FROM {from_clause} GROUP BY 1, 2 LIMIT {int(row_cap)}")
            try:
                with engine.connect() as conn:
                    rows = conn.execute(_text(sql_dim)).fetchall()
            except Exception:
                continue
            by_seg: dict[str, dict[str, float]] = {}
            for r in rows or []:
                try:
                    seg = str(r[0])
                    p = str(r[1])
                    v = float(r[2] or 0.0)
                except (TypeError, ValueError, IndexError):
                    continue
                d = by_seg.setdefault(seg, {})
                d[p] = d.get(p, 0.0) + v
            for seg, per in by_seg.items():
                cv = _pick_period_value(per, clab)
                pv = _pick_period_value(per, plab)
                if cv is None and pv is None:
                    continue
                cv = float(cv or 0.0)
                pv = float(pv or 0.0)
                dseg = cv - pv
                if not dseg:
                    continue
                contrib = dseg / total_delta * 100.0
                a = abs(contrib)
                if a >= 40:
                    conf = "high"
                elif a >= 20:
                    conf = "medium"
                else:
                    conf = "low"
                dim_label = _human_col(col)
                verb = "down" if dseg < 0 else "up"
                drivers.append({
                    "driver": (
                        f"{seg} ({dim_label}): {verb} {_fmt_compact(dseg)} — "
                        f"about {a:.0f}% of the {word} in "
                        f"{change['current']} vs {change['previous']}"),
                    "dimension": dim_label,
                    "value": seg,
                    "metric": str(metric_label or ""),
                    "total": round(cv, 2),
                    "previous": round(pv, 2),
                    "delta": round(dseg, 2),
                    "contribution_pct": round(contrib, 1),
                    "basis": "change",
                    "confidence": conf,
                    "period": f"{change['current']} vs {change['previous']}",
                    "evidence": {
                        "table": f"{tbl}.{col}" if tbl else col,
                        "sql": sql_dim,
                        "values": [{
                            "dimension": seg,
                            "current": round(cv, 2),
                            "previous": round(pv, 2),
                            "delta": round(dseg, 2),
                            "contribution_pct": round(contrib, 1),
                        }],
                    },
                    "note": ("Statistical association in this dataset, "
                             "not proven cause."),
                })
        if direction == "drop":
            drivers.sort(key=lambda d: d.get("delta", 0))
        else:
            drivers.sort(key=lambda d: d.get("delta", 0), reverse=True)
        out["drivers"] = drivers[:max(1, int(limit_rows))]
        return out
    except Exception:
        return out


# ---------------------------------------------------------------------------
# Hypothesis builder (evidence-shaped, generic — no hardcoded names)
# ---------------------------------------------------------------------------

def _hyp_num(v: Any) -> float | None:
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _hyp_grade(sample_n: int, gap: float | None, top_conf: str) -> tuple[str, str]:
    """Evidence grade from sample size + consistency, in plain words.

    Never mentions r/p/slope or any statistician numbers — only everyday
    words about how much was seen and how clear the gap is.
    """
    conf = str(top_conf or "").lower()
    clear = (conf == "high" and gap is not None and gap >= 15) or (
        gap is not None and gap >= 25
    )
    partly = (
        conf in ("high", "medium")
        and gap is not None
        and gap >= 8
    )
    if sample_n >= 30 and clear:
        return ("strong",
                "Strong — seen across many observations with a clear gap "
                "between the leader and the rest.")
    if sample_n >= 30 and partly:
        return ("mixed",
                "Mixed — seen across many observations, but the gap is "
                "modest so the lead could change with more data.")
    if sample_n >= 10 and clear:
        return ("mixed",
                "Mixed — the gap looks clear, but it rests on a moderate "
                "number of observations so treat it as a lead to check.")
    if sample_n >= 10 and partly:
        return ("mixed",
                "Mixed — a middling number of observations with a modest "
                "gap, worth checking further.")
    if sample_n >= 10:
        return ("weak",
                "Weak — only a middling number of observations and no clear "
                "gap, so this is an early hint at best.")
    return ("weak",
            "Weak — based on only a few observations, so treat this as a "
            "question to explore, not an answer.")


def build_hypothesis(
    drivers: list[dict] | None,
    metric_label: str | None = None,
    metric_col: str | None = None,
    period_label: str = "",
    observation_count: int = 0,
    dimensions: list[str] | None = None,
) -> dict:
    """Build an evidence-shaped hypothesis from real driver aggregates.

    Returns a backward-compatible dict (``text``/``confidence``/``drivers``)
    plus additive fields: ``evidence_grade``, ``evidence_reason``,
    ``rivals`` ([{text}]), ``data_needed``, ``explore_handoff`` and
    ``prescription_handoff``. Everything is derived from the passed
    drivers/metric/period/counts — nothing is hardcoded to a domain, and
    the prose never contains r/p/slope statistics.
    """
    metric = str(metric_label or metric_col or "the metric").strip() or "the metric"
    period = str(period_label or "the selected period").strip() or "the selected period"
    try:
        n = int(observation_count or 0)
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    items = [d for d in (drivers or []) if isinstance(d, dict)]
    tops = sorted(items, key=lambda d: _hyp_num(d.get("contribution_pct")) or 0,
                  reverse=True)
    driver_names = [str(d.get("driver") or "") for d in tops[:3] if d.get("driver")]

    if not tops:
        obs = f" across {n} observations" if n > 0 else ""
        text = (
            f"No single segment dominates {metric} in {period}{obs} — "
            f"the data looks spread out. "
            f"Treat any single-factor story as weak until more of the data "
            f"is checked. This is a pattern in the data, "
            f"not proof of what causes it."
        )
        grade, reason = _hyp_grade(n, None, "low")
        noun = "breakdown" if not (dimensions or []) else str((dimensions or [])[0])
        return {
            "text": text,
            "confidence": "low",
            "drivers": [],
            "evidence_grade": grade,
            "evidence_reason": reason,
            "rivals": [
                {"text": (
                    "One rival explanation is that the total is spread across "
                    "many small segments, so no single one drives it."
                )},
                {"text": (
                    "Another is a mix or timing effect not visible in this "
                    f"breakdown — checked only against {noun}, so it stays open."
                )},
            ][:2],
            "data_needed": (
                "A finer breakdown, or a longer period with more observations, "
                "would settle whether any single factor emerges."
            ),
            "explore_handoff": {
                **({"metric": str(metric_col or metric)} if (metric_col or metric) else {}),
                **({"breakdown": str((dimensions or [])[0])} if (dimensions or []) else {}),
            },
            "prescription_handoff": {
                **({"metric": str(metric_col or metric)} if (metric_col or metric) else {}),
            },
        }

    top = tops[0]
    top_val = str(top.get("value") or "").strip() or "the leading segment"
    # Prefer the segment's own dimension label, else the first requested
    # dimension (explicit if/else: keeps the precedence readable).
    if dimensions:
        top_dim = str(top.get("dimension") or dimensions[0] or "").strip()
    else:
        top_dim = str(top.get("dimension") or "").strip()
    top_share = _hyp_num(top.get("contribution_pct"))
    top_conf = str(top.get("confidence") or "low")
    second = tops[1] if len(tops) > 1 else None
    second_val = str((second or {}).get("value") or "").strip() if second else ""
    second_share = _hyp_num((second or {}).get("contribution_pct")) if second else None
    gap: float | None = None
    if top_share is not None and second_share is not None:
        gap = round(top_share - second_share, 1)

    share_txt = f"about {round(top_share)}%" if top_share is not None else "a large portion"
    obs_txt = f" across {n} observations" if n > 0 else ""
    where = f" in {period}" if period else ""
    seg_txt = f" ({top_dim})" if top_dim else ""

    # Evidence-shaped sentences: shape chosen by evidence type.
    if top_share is not None and (top_share >= 40 or (gap is not None and gap >= 20)):
        gap_txt = f" — well ahead of the next largest at about {round(second_share)}%" \
            if second and second_val and second_share is not None else ""
        text = (
            f"{top_val}{seg_txt} stands out in {metric}{where}: "
            f"{share_txt} of the total{obs_txt}{gap_txt}. "
            f"The size of the gap makes it the leading pattern to check. "
            f"This is a pattern in the data, not proof of what causes it."
        )
    elif second and second_val and gap is not None and gap < 12 and (top_share or 0) >= 15:
        text = (
            f"{top_val}{seg_txt} leads {metric}{where} with {share_txt}, "
            f"just ahead of {second_val} at about {round(second_share or 0)}%{obs_txt}. "
            f"With the top two close, either could matter most on a rerun. "
            f"This is a pattern in the data, not proof of what causes it."
        )
    else:
        runner_txt = f" The next largest, {second_val}, is not far behind." \
            if second and second_val else ""
        text = (
            f"{top_val}{seg_txt} holds {share_txt} of {metric}{where}{obs_txt}."
            f"{runner_txt} "
            f"The picture is suggestive rather than firm. "
            f"This is a pattern in the data, not proof of what causes it."
        )

    grade, reason = _hyp_grade(n, gap, top_conf)

    rivals: list[dict] = []
    if second and second_val:
        s_txt = f"about {round(second_share)}%" if second_share is not None else "a smaller portion"
        rivals.append({"text": (
            f"Another possibility is {second_val} at {s_txt} — checked against "
            f"the same breakdown, it explains less on its own because its "
            f"portion is smaller."
        )})
    else:
        rivals.append({"text": (
            "Another possibility is that the rest is spread across many small "
            "segments, so the lead flatters a single name — checked only "
            "against the top of the breakdown."
        )})
    if len(tops) > 2:
        third = tops[2]
        third_val = str(third.get("value") or "").strip()
        if third_val:
            third_share = _hyp_num(third.get("contribution_pct"))
            t_txt = f"about {round(third_share)}%" if third_share is not None else "a smaller portion"
            rivals.append({"text": (
                f"A further rival is {third_val} at {t_txt} — smaller still, "
                f"so it would need a different cut of the data to overtake."
            )})
    else:
        rivals.append({"text": (
            "A further rival is a mix or timing effect not visible in this "
            "breakdown — nothing in this cut rules it out."
        )})
    rivals = rivals[:2]

    if second and gap is not None and gap < 12:
        data_needed = (
            "Comparing another period, or breaking the numbers down over "
            "time, would settle which segment holds the lead."
        )
    elif top_dim:
        data_needed = (
            f"Breaking down {top_val} further, or comparing another period, "
            f"would settle whether the lead persists or fades."
        )
    else:
        data_needed = (
            "Comparing another period with more observations would settle "
            "whether this pattern holds."
        )

    metric_ref = str(metric_col or metric)
    dim_ref = str(top.get("dimension") or ((dimensions or [""])[0] if (dimensions or []) else ""))
    explore_handoff: dict = {}
    if metric_ref:
        explore_handoff["metric"] = metric_ref
    if dim_ref:
        explore_handoff["breakdown"] = dim_ref
    if top_val and top_val != "the leading segment":
        explore_handoff["segment"] = top_val
    prescription_handoff: dict = {}
    if metric_ref:
        prescription_handoff["metric"] = metric_ref
    if dim_ref:
        prescription_handoff["driver"] = dim_ref
        prescription_handoff["segmentField"] = dim_ref
    if top_val and top_val != "the leading segment":
        prescription_handoff["segmentValue"] = top_val

    return {
        "text": text,
        "confidence": top_conf,
        "drivers": driver_names,
        "evidence_grade": grade,
        "evidence_reason": reason,
        "rivals": rivals,
        "data_needed": data_needed,
        "explore_handoff": explore_handoff,
        "prescription_handoff": prescription_handoff,
    }


def build_change_hypothesis(change: dict | None,
                            drivers: list[dict] | None,
                            metric_label: str | None = None,
                            metric_col: str | None = None,
                            observation_count: int = 0,
                            dimensions: list | None = None) -> dict:
    """Hypothesis for a period-over-period change question ("why did X drop?").

    Same backward-compatible shape as :func:`build_hypothesis` (plus a
    ``change`` block). Wording attributes the movement to the segments that
    moved most, always as an association in the data — never a proven cause.
    """
    metric = str(metric_label or metric_col or "the metric").strip() or "the metric"
    ch = change if isinstance(change, dict) else {}
    try:
        n = int(observation_count or 0)
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    direction = str(ch.get("direction") or "change")
    cur = str(ch.get("current") or "the latest period")
    prev = str(ch.get("previous") or "the previous period")
    pct = _hyp_num(ch.get("change_pct"))
    move = "fell" if direction == "drop" else ("rose" if direction == "rise" else "moved")
    word = "fall" if direction == "drop" else "rise"
    pct_txt = f" {abs(round(pct))}%" if pct is not None else ""
    metric_txt = metric[:1].upper() + metric[1:] if metric else metric
    head = f"{metric_txt} {move}{pct_txt} in {cur} vs {prev}"
    items = [d for d in (drivers or []) if isinstance(d, dict)]
    tops = [d for d in items
            if _hyp_num(d.get("contribution_pct")) is not None][:3]

    if tops:
        bits = []
        for d in tops:
            share = abs(_hyp_num(d.get("contribution_pct")) or 0)
            seg = str(d.get("value") or "").strip() or "a segment"
            dim = str(d.get("dimension") or "").strip()
            seg_txt = f"{seg} ({dim})" if dim else seg
            bits.append(f"{seg_txt} — about {round(share)}% of the {word}")
        text = (
            f"{head}. Most of the movement is concentrated in: "
            + "; ".join(bits)
            + ". These are patterns in the data, not proof of what caused "
              "the change."
        )
        top_share = abs(_hyp_num(tops[0].get("contribution_pct")) or 0)
        second_share = (abs(_hyp_num(tops[1].get("contribution_pct")) or 0)
                        if len(tops) > 1 else None)
        gap = round(top_share - second_share, 1) if second_share is not None else None
        top_conf = str(tops[0].get("confidence") or "low")
    else:
        obs = f" across {n} observations" if n > 0 else ""
        text = (
            f"{head}. No single segment stands out in the checked "
            f"breakdowns{obs} — the change looks spread across many "
            f"segments. This is a pattern in the data, not proof of what "
            f"causes it."
        )
        top_share = second_share = gap = None
        top_conf = "low"

    grade, reason = _hyp_grade(n, gap, top_conf)

    rivals: list[dict] = []
    if tops:
        rivals.append({"text": (
            "Part of the change can come from segments that moved the other "
            "way — only the biggest movers were ranked, not the whole mix."
        )})
    rivals.append({"text": (
        f"A mix or timing effect outside this cut (checked against the "
        f"connected tables only) could explain part of the {word} in {cur}."
    )})
    rivals = rivals[:2]

    if tops:
        data_needed = (
            f"Checking the top movers against another period, or splitting "
            f"them further, would show whether the {word} concentrates the "
            f"same way again."
        )
    else:
        data_needed = (
            "A finer breakdown with more observations would settle whether "
            "any single segment emerges from this spread."
        )

    metric_ref = str(metric_col or metric)
    top0 = tops[0] if tops else {}
    dim_ref = str(top0.get("dimension") or "").strip()
    explore_handoff: dict = {}
    if metric_ref:
        explore_handoff["metric"] = metric_ref
    if dim_ref:
        explore_handoff["breakdown"] = dim_ref
    top_val = str(top0.get("value") or "").strip()
    if top_val:
        explore_handoff["segment"] = top_val
    prescription_handoff: dict = {}
    if metric_ref:
        prescription_handoff["metric"] = metric_ref
    if dim_ref:
        prescription_handoff["driver"] = dim_ref
        prescription_handoff["segmentField"] = dim_ref
    if top_val:
        prescription_handoff["segmentValue"] = top_val

    return {
        "text": text,
        "confidence": top_conf,
        "drivers": [str(d.get("driver") or "") for d in items[:3]
                    if d.get("driver")],
        "evidence_grade": grade,
        "evidence_reason": reason,
        "rivals": rivals,
        "data_needed": data_needed,
        "explore_handoff": explore_handoff,
        "prescription_handoff": prescription_handoff,
        "change": ch,
    }


# ---------------------------------------------------------------------------
# Follow-ups generated from the result (never generic)
# ---------------------------------------------------------------------------

def _followup_is_id_like(name: str) -> bool:
    """Local ID-like check (mirrors core.schema_intel._is_id_like).

    Token equality — never substrings — so "country" is not an ID.
    Kept local so the analytics layer never imports API modules.
    """
    toks = [t for t in re.split(r"[^a-z0-9]+", re.sub(
        r"(?<=[a-z])(?=[A-Z])", "_", str(name or "")).lower()) if t]
    if not toks:
        return False
    if toks == ["id"]:
        return True
    return toks[-1] in ("id", "uuid", "guid", "key", "code")


def build_followups(question: str, primary_intent: str, metric: str | None,
                    dimensions: list[str], period_label: str = "",
                    drivers: list[dict] | None = None,
                    limit: int = 6, has_datetime: bool = False) -> list[str]:
    """Follow-up questions built from actual result content.

    Only plain-ask answerable questions are emitted here: rankings,
    breakdowns, averages and (when ``has_datetime`` is True) trends.
    Outlier / correlation / forecast / what-if questions need drivers or
    history and live on their own tabs — they are never suggested here.
    """
    m = (metric or "the metric").strip() or "the metric"
    # Never suggest an ID-like dimension as a breakdown segment.
    dims = [d for d in (dimensions or [])
            if d and "(" not in str(d) and "*" not in str(d)
            and not _followup_is_id_like(str(d))]
    # Natural-English wording (generic): humanize raw identifiers to bare
    # lowercase words so follow-ups read like typed questions, never like
    # schema paths (sales.totaldue -> "total due", never "sales.totaldue").
    try:
        from core.semantic import humanize as _hum

        def _nl(v):
            try:
                return _hum(str(v or "").split(".")[-1]).lower().strip() or str(v or "")
            except Exception:
                return str(v or "")
    except Exception:
        def _nl(v):
            return str(v or "")
    m = _nl(m) if m != "the metric" else m
    dims = [_nl(d) for d in dims]
    try:
        drivers = [{**t, "dimension": _nl(t.get("dimension")),
                    "value": str(t.get("value"))} for t in (drivers or [])]
    except Exception:
        pass
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
    if primary_intent in ("ranking", "segmentation", "distribution",
                          "contribution"):
        cands.append(f"Which {d0} has the lowest {m}?")
    if drivers:
        top = drivers[0]
        cands.append(
            f"How much of {m} comes from {top.get('value')} ({top.get('dimension')})?")
    if primary_intent in ("recommendation",):
        cands.append(f"What should we do about {m} in {period}?")
    # Deduplicate, keep order, cap (4-8 window enforced by caller limit).
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) >= limit:
            break
    # Honest fallback when nothing could be grounded (still result-derived:
    # it references the metric that was actually analyzed). Trend is only
    # offered when a real datetime column was verified upstream.
    if not out:
        out = [f"Show {m} breakdown by {d0}"]
        if has_datetime:
            out.append(f"How has {m} changed over time?")
        else:
            out.append(f"Which {d0} has the highest {m}?")
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
