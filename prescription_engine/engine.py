"""Prescription Engine: evidence -> problem -> driver -> controllability ->
candidates -> scenarios -> rank. Self-contained statistics (numpy/scipy);
reuses only SchemaIntelligence for schema discovery. All data access is
bounded and read-only. The LLM never computes numbers — it may only polish
wording built deterministically from the evidence.
"""

import logging
import math
import re

import numpy as np

log = logging.getLogger("aria.prescription_engine")

try:
    from scipy import stats as _st
    _SCIPY_OK = True
except Exception:
    _SCIPY_OK = False

MIN_N = 10
SAMPLE_LIMIT = 5000
MIN_ABS_R = 0.30

# --------------------------------------------------------------------------
# Structured error codes (§29)
# --------------------------------------------------------------------------
CODE_NO_CONNECTION = "NO_CONNECTION"
CODE_INVALID_METRIC = "INVALID_METRIC"
CODE_INVALID_DRIVER = "INVALID_DRIVER"
CODE_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
CODE_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
CODE_SCENARIO_UNSUPPORTED = "SCENARIO_UNSUPPORTED"
CODE_ANALYSIS_FAILED = "ANALYSIS_FAILED"
CODE_MODEL_FAILED = "MODEL_FAILED"
CODE_LLM_FAILED = "LLM_FAILED"
CODE_TIMEOUT = "TIMEOUT"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"


def _fail(code, detail, **extra):
    out = {"ok": False, "success": False, "code": code,
           "detail": detail, "recoverable": True}
    out.update(extra)
    return out


# --------------------------------------------------------------------------
# Controllability (§8): name + type heuristics, never hardcoded schema
# --------------------------------------------------------------------------
_CONTROLLABLE_HINTS = ("price", "pricing", "discount", "promo", "spend",
                       "spending", "budget", "bid", "fee", "cost_per",
                       "inventory", "stock", "reorder", "staff", "hours")
_MAYBE_CONTROLLABLE = ("market", "advert", "campaign", "channel_spend",
                       "quantity_ordered", "supply", "stay", "nights", "duration",
                       "length_of_stay")
_SEGMENT_HINTS = ("region", "area", "city", "state", "country", "zone",
                  "territory", "category", "product", "brand", "sku",
                  "segment", "channel", "store", "department", "division",
                  "gender", "cohort", "tier", "payment", "ship")
_TIME_HINTS = ("date", "time", "day", "month", "year", "created", "updated",
               "timestamp", "period", "week", "quarter")
_LOWER_BETTER_HINTS = ("cost", "expense", "churn", "loss", "debt", "risk",
                       "complaint", "return_rate", "defect", "delay")


# --------------------------------------------------------------------------
# Semantic roles + actionability (hyp.txt Response §§5-6). Generalized name
# signals only — NEVER a hardcoded per-column check. Association is
# evidence of association: only a lever passing semantic-role +
# actionability validation may become a recommendation/scenario variable.
# Reuses core/semantic.py and core/relational.py where they exist.
# --------------------------------------------------------------------------

# Recognized business-outcome vocabulary: higher values indicate
# improvement. Generalized semantics (never lever→outcome pairs).
_HIGHER_BETTER_HINTS = ("revenue", "revenues", "profit", "profits", "margin",
                        "margins", "income", "sales", "conversion",
                        "conversions", "retention", "satisfaction", "growth",
                        "gain", "gains", "yield", "booking", "bookings",
                        "demand", "attendance", "enrollment", "signup",
                        "signups", "subscription", "subscriptions")

# Telemetry/system measurement vocabulary: analytic signal, never a lever.
_TECHNICAL_MEASURE_HINTS = (
    "bytes", "byte_size", "millisecond", "milliseconds", "millisec",
    "microsecond", "microseconds", "nanosecond", "nanoseconds",
    "latency", "ping", "ttl", "cpu", "gpu", "memory", "heap",
    "disk", "iops", "cache", "page_fault", "packet", "packets",
    "bandwidth", "throughput", "payload", "query_time", "query_duration",
    "execution_time", "exec_time", "response_time", "elapsed",
    "duration_ms", "duration_sec", "duration_seconds", "wait_time",
    "load_avg", "thread", "threads", "kernel", "uptime", "file_size",
    "filesize", "memory_mb", "cpu_time", "io_wait", "network_io",
)

# Counters / storage internals: analytic metadata, never a lever.
_SYSTEM_METADATA_HINTS = (
    "row_count", "rowcount", "record_count", "num_rows", "counter",
    "counters", "sequence", "seq_no", "seqno", "checksum", "encoding",
    "encoded", "partition_key",
)

# Recognized business-measure vocabulary (generic, schema-agnostic).
_BUSINESS_MEASURE_HINTS = (
    "price", "pricing", "cost", "amount", "revenue", "profit", "margin",
    "sales", "total", "payment", "spend", "spending", "budget", "discount",
    "quantity", "qty", "inventory", "stock", "wage", "salary", "fee",
    "rate", "pct", "percent", "ratio", "conversion", "retention",
    "order", "orders", "booking", "demand", "supply", "volume", "traffic",
    "freight", "fare", "tuition", "premium", "warranty",
)

# Roles that may (subject to the 8-point actionability check) become levers.
LEVER_ROLES = frozenset({"BUSINESS_MEASURE", "MEASURE"})
# Roles that can never be a recommendation outcome.
NON_OUTCOME_ROLES = frozenset({"TECHNICAL_MEASURE", "SYSTEM_METADATA",
                               "IDENTIFIER", "FOREIGN_KEY", "DATE_TIME",
                               "UNKNOWN"})
# Roles that can never be a lever/scenario variable.
NON_LEVER_ROLES = frozenset({"TECHNICAL_MEASURE", "SYSTEM_METADATA",
                             "IDENTIFIER", "FOREIGN_KEY", "DATE_TIME",
                             "DIMENSION", "CATEGORY", "TEXT", "UNKNOWN"})

# Canonical honest state when no legitimate business lever exists (§9).
NO_SUPPORTED_SCENARIO = "No supported actionable scenario"


def _name_tokens(name) -> list:
    """Lowercase alphanumeric tokens of a column name (snake/camel safe)."""
    parts = re.split(r"[^a-z0-9]+", str(name or "").lower())
    toks: list = []
    for p in parts:
        toks.extend(re.findall(r"[a-z]+|[0-9]+", p))
    return [t for t in toks if t]


def _has_hint(name, hints) -> bool:
    """Generalized vocabulary match: token equality for short hints,
    substring for compound/long hints (len>=8 or containing '_').

    Token equality keeps short signals precise (``ram`` never matches
    ``program``; ``counter`` never matches ``encounter``).
    """
    low = str(name or "").lower()
    toks = set(_name_tokens(low))
    for h in hints:
        h = str(h).lower()
        if not h:
            continue
        if h in toks:
            return True
        if len(h) >= 8 or "_" in h:
            if h in low:
                return True
    return False


def classify_semantic_role(name, col_category="", *, is_pk=False,
                           is_fk=False, is_join_key=False) -> str:
    """Semantic role of a field (hyp.txt §5) — generalized, data-aware.

    Returns one of: IDENTIFIER / FOREIGN_KEY / DATE_TIME / MEASURE /
    BUSINESS_MEASURE / TECHNICAL_MEASURE / DIMENSION / CATEGORY / TEXT /
    SYSTEM_METADATA / UNKNOWN. Reuses core/semantic.py and
    core/relational.py signals where available; never a per-column check.
    """
    low = str(name or "")
    cat = str(col_category or "").lower()
    try:
        from core.relational import is_ref_flavored as _is_ref
        _ref = bool(_is_ref(name))
    except Exception:
        _ref = False
    tail = low.lower().split("_")[-1] if low else ""
    id_like = (_ref or tail in ("id", "key", "code", "no", "num", "uuid",
                               "guid", "pk", "fk")
               or low.lower() in ("id", "key", "code"))
    if is_fk:
        return "FOREIGN_KEY"
    if is_pk or is_join_key and id_like:
        return "IDENTIFIER"
    if id_like:
        return "IDENTIFIER"
    if cat == "datetime" or any(h in low.lower() for h in _TIME_HINTS):
        return "DATE_TIME"
    if _has_hint(low, _TECHNICAL_MEASURE_HINTS):
        return "TECHNICAL_MEASURE" if cat in ("numeric", "", "unknown",
                                              "other") else "SYSTEM_METADATA"
    if _has_hint(low, _SYSTEM_METADATA_HINTS):
        return "SYSTEM_METADATA"
    if cat == "numeric":
        try:
            from core.semantic import classify_semantic_type as _cst
            _st = _cst(low, "")
        except Exception:
            _st = "measure"
        if _st == "identifier":
            return "IDENTIFIER"
        if _has_hint(low, _BUSINESS_MEASURE_HINTS):
            return "BUSINESS_MEASURE"
        return "MEASURE"
    if cat in ("text", "binary", "other", "", "unknown"):
        try:
            from core.semantic import classify_semantic_type as _cst2
            _st2 = _cst2(low, "")
        except Exception:
            _st2 = "text"
        if _st2 == "identifier":
            return "IDENTIFIER"
        if _st2 == "date":
            return "DATE_TIME"
        if _st2 == "category":
            return "CATEGORY"
        if _st2 == "geography":
            return "DIMENSION"
        return "TEXT"
    return "UNKNOWN"


def assess_actionability(lever_name, lever_role, control_level, *,
                         metric_role=None, direction_known=False,
                         has_evidence=False) -> dict:
    """8-point business-actionability check (hyp.txt §6).

    A variable becomes a recommendation/scenario lever ONLY if every
    applicable check passes. Correlation alone (has_evidence without the
    other gates) can never carry a lever.
    """
    failed, notes = [], []

    def _need(ok: bool, code: str, note: str):
        if not ok:
            failed.append(code)
            notes.append(note)

    _need(lever_role in LEVER_ROLES, "business_concept",
          f"'{lever_name}' is a {lever_role}, not a meaningful business concept.")
    _need(control_level in ("controllable", "potentially_controllable"),
          "controllable",
          f"'{lever_name}' is not controllable or influenceable ({control_level}).")
    _need(lever_role not in NON_LEVER_ROLES, "plausible_action",
          f"Changing '{lever_name}' is not a plausible business action.")
    if metric_role is not None:
        _need(metric_role not in NON_OUTCOME_ROLES, "outcome_metric",
              "No meaningful business outcome metric is attached to this driver.")
    _need(bool(has_evidence), "evidence",
          "No statistical evidence supports the driver→outcome relationship.")
    _need(bool(direction_known), "justified_direction",
          "The proposed direction of change is not justified.")
    _need(bool(has_evidence and direction_known
               and control_level in ("controllable", "potentially_controllable")
               and (metric_role is None or metric_role not in NON_OUTCOME_ROLES)),
          "not_correlation_only",
          "Correlation alone cannot justify an intervention.")
    # Check 8 (no invented assumption) holds structurally: direction is only
    # ever 'known' via recognized outcome semantics or an explicitly
    # recorded modeling assumption — never a silent generic rule.
    return {"actionable": not failed, "failed": failed, "notes": notes}


def _disp(raw):
    """User-facing 'Human (raw)' label for refusal/diagnostic strings.

    The humanized name is the primary label; the raw column name follows
    in parentheses so logs, tests and technical readers can still match
    the physical field. Findings prose uses humanize() alone instead.
    """
    from core.semantic import humanize as _h
    h = _h(raw)
    return f"{h} ({raw})" if h != str(raw) else str(raw)


def _join_phrase(join_used) -> str | None:
    """User-facing join provenance in business words.

    Generic over any declared edge ("linked X records"); the raw
    table.column path stays in the structured join/join_ref fields and
    server logs, never as the primary label.
    """
    if not join_used:
        return None
    try:
        from core.semantic import humanize as _h
        return f"linked {_h(join_used[0])} records"
    except Exception:
        return "linked records"


def classify_driver(name, col_category):
    """Return (level, reason) with level in controllable / potentially /
    segmentation / not_controllable."""
    low = (name or "").lower()
    tail = low.split("_")[-1] if low else ""
    if col_category == "datetime" or any(h in low for h in _TIME_HINTS):
        return "not_controllable", "Time cannot be changed — ARIA can only prepare for it."
    if tail in ("id", "key", "code", "no") or low in ("id", "key", "code"):
        return "not_controllable", "Identifiers cannot be intervened on."
    # Technical/system measurements and storage metadata describe the
    # machinery, not the business — association only, never a lever (§§4-6).
    # Generalized vocabulary (never per-column); checked BEFORE the
    # controllable hints so e.g. an inventory-flavored cache counter can
    # never slip through as actionable.
    if _has_hint(name, _TECHNICAL_MEASURE_HINTS) or _has_hint(name, _SYSTEM_METADATA_HINTS):
        return ("not_controllable",
                "Technical/system measurements cannot be intervened on — association only, never a driver.")
    if any(h in low for h in _CONTROLLABLE_HINTS):
        return "controllable", "This driver can be set directly as an intervention."
    if any(h in low for h in _MAYBE_CONTROLLABLE):
        if "stay" in low or "night" in low or "duration" in low:
            return ("potentially_controllable",
                    "Length of stay can be influenced (offers, minimum-stay rules) but not set directly.")
        return "potentially_controllable", "This driver may be adjustable; treat estimates cautiously."
    if col_category != "numeric" or any(h in low for h in _SEGMENT_HINTS):
        return "segmentation", "This field segments the business — target an intervention at a group, don't change the field itself."
    return "potentially_controllable", "No evidence this driver is directly settable; estimates are exploratory."


def improvement_up(metric):
    """Validated improvement direction (hyp.txt §12) — never a silent
    generic assumption.

    Returns (up_better_or_None, basis). Direction is established ONLY from
    recognized outcome semantics (higher-better / lower-better vocabulary)
    or, for business-plausible metrics without recognized semantics, an
    EXPLICITLY recorded modeling assumption (confidence is capped
    downstream when the fallback is used). Technical/system fields have
    unknown direction → None, which refuses the recommendation at the
    call site instead of inventing one.
    """
    role = classify_semantic_role(metric, "numeric")
    if role in NON_OUTCOME_ROLES:
        return None, ("direction cannot be established for this field — it is "
                      "not a business outcome, so no recommendation basis exists")
    low = (metric or "").lower()
    if any(h in low for h in _LOWER_BETTER_HINTS):
        return False, "lower values indicate improvement for this outcome (recognized cost/risk semantics)"
    if _has_hint(metric, _HIGHER_BETTER_HINTS):
        return True, "higher values indicate improvement for this outcome (recognized outcome semantics)"
    from core.semantic import humanize as _h
    return True, (f"no outcome semantics recognized for {_h(metric)} — treating higher values as "
                  "improvement as an explicit modeling assumption; confirm this matches your objective")


# --------------------------------------------------------------------------
# Bounded read-only data access (dialect-aware, no raw frontend SQL)
# --------------------------------------------------------------------------
def _exec(engine, sql, params=None):
    from sqlalchemy import text as _t
    with engine.connect() as conn:
        return conn.execute(_t(sql), params or {}).fetchall()


def _fetch_pairs(engine, dialect, table, col_a, col_b, filt=None, limit=SAMPLE_LIMIT):
    from api.schema_intel import _safe_name
    where = (f"{_safe_name(col_a, dialect)} IS NOT NULL AND "
             f"{_safe_name(col_b, dialect)} IS NOT NULL")
    params = {}
    if filt:
        where += f" AND {_safe_name(filt[0], dialect)} = :flt"
        params["flt"] = filt[1]
    # Deterministic sample: ORDER BY the sampled columns so identical
    # requests analyze identical rows (bare LIMIT is return-order dependent).
    return _exec(engine,
                 f"SELECT {_safe_name(col_a, dialect)}, {_safe_name(col_b, dialect)} "
                 f"FROM {_safe_name(table, dialect)} WHERE {where} "
                 f"ORDER BY {_safe_name(col_a, dialect)}, {_safe_name(col_b, dialect)} "
                 f"LIMIT {int(limit)}", params)


# --------------------------------------------------------------------------
# Statistics (deterministic; scipy when present, documented fallbacks)
# --------------------------------------------------------------------------
def _pearson_p(r, n):
    if n < 3 or abs(r) >= 1.0:
        return 0.0 if abs(r) >= 1.0 else 1.0
    if _SCIPY_OK:
        try:
            from scipy import stats as _s
            t = r * math.sqrt((n - 2) / max(1e-12, 1 - r * r))
            return float(2 * (1 - _s.t.cdf(abs(t), n - 2)))
        except Exception:
            pass
    # Normal approximation fallback (documented, conservative).
    try:
        z = 0.5 * math.log((1 + r) / (1 - r)) * math.sqrt(n - 3)
        return float(2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2)))))
    except Exception:
        return 1.0


def _spearman(x, y):
    if len(x) < 3:
        return 0.0, 1.0
    if _SCIPY_OK:
        rx = _st.rankdata(x, method='average')
        ry = _st.rankdata(y, method='average')
    else:
        # numpy-only fallback: average ranks with tie-breaking
        def _avg_rank(arr):
            order = arr.argsort()
            ranks = np.empty_like(order, dtype=float)
            ranks[order] = np.arange(1, len(arr) + 1, dtype=float)
            # average tied ranks
            sorted_arr = arr[order]
            i = 0
            while i < len(sorted_arr):
                j = i + 1
                while j < len(sorted_arr) and sorted_arr[j] == sorted_arr[i]:
                    j += 1
                if j > i + 1:
                    avg = np.arange(i + 1, j + 1, dtype=float).mean()
                    for k in range(i, j):
                        ranks[order[k]] = avg
                i = j
            return ranks
        rx = _avg_rank(np.asarray(x, dtype=float))
        ry = _avg_rank(np.asarray(y, dtype=float))
    r = float(np.corrcoef(rx, ry)[0, 1])
    return r, _pearson_p(r, len(x))


def fit_relationship(x, y):
    """OLS of y on x with slope SE, residual sigma, CIs. Returns None if unfit."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < MIN_N or float(x.std()) == 0 or float(y.std()) == 0:
        return None
    r = float(np.corrcoef(x, y)[0, 1])
    p = _pearson_p(r, n)
    rs, ps = _spearman(x, y)
    slope, intercept = (float(v) for v in np.polyfit(x, y, 1))
    pred = slope * x + intercept
    resid = y - pred
    sigma = float(resid.std(ddof=1)) if n > 2 else 0.0
    sxx = float(np.sum((x - x.mean()) ** 2))
    se_slope = sigma / math.sqrt(sxx) if sxx > 0 else 0.0
    z = 0.5 * math.log((1 + r) / (1 - r)) if abs(r) < 1 else 0.0
    se = 1.0 / math.sqrt(max(1, n - 3))
    ci = [round(math.tanh(z - 1.96 * se), 3), round(math.tanh(z + 1.96 * se), 3)]
    return {"n": n, "r": round(r, 3), "p_value": p,
            "spearman_r": round(rs, 3), "spearman_p": ps,
            "slope": slope, "intercept": intercept,
            "se_slope": se_slope, "sigma": sigma, "ci": ci,
            "x_mean": float(x.mean()), "y_mean": float(y.mean()),
            "x_min": float(x.min()), "x_max": float(x.max())}


# --------------------------------------------------------------------------
# Scenario math (§11): pure functions of the fitted model — SIMULATED labels
# --------------------------------------------------------------------------
def scenario_for_pct(fit, pct):
    """Scenario KPIs for a driver change of pct/100. All values SIMULATED."""
    base = fit["intercept"] + fit["slope"] * fit["x_mean"]
    dx = fit["x_mean"] * (pct / 100.0)
    scen = base + fit["slope"] * dx
    delta = scen - base
    # Uncertainty: slope CI propagated (±1.96·se·|dx|) plus residual noise.
    half = 1.96 * fit["se_slope"] * abs(dx)
    lo = scen - half - fit["sigma"] * 0.1
    hi = scen + half + fit["sigma"] * 0.1
    new_x = fit["x_mean"] + dx
    in_range = fit["x_min"] <= new_x <= fit["x_max"]
    return {"driver_pct": pct, "driver_value": new_x,
            "baseline": base, "scenario": scen, "delta": delta,
            "rel_pct": (delta / abs(base) * 100) if base else 0.0,
            "range": [lo, hi], "in_historical_range": in_range}


def risk_level(fit, pct, strength):
    """LOW/MEDIUM/HIGH + reasons (§20)."""
    reasons = ["Historical data shows an association; it does not establish "
               "that changing this variable will directly cause the predicted result."]
    level = 1  # 0 low, 1 medium, 2 high
    scen = scenario_for_pct(fit, pct)
    if not scen["in_historical_range"]:
        level = max(level, 2)
        reasons.append("Scenario moves the driver outside its observed historical range.")
    if abs(fit["r"]) < 0.5:
        level = max(level, 1)
        reasons.append("Moderate relationship strength — estimates carry real uncertainty.")
    if fit["n"] < 50:
        level = max(level, 1)
        reasons.append(f"Modest sample ({fit['n']} observations).")
    if fit["p_value"] < 0.01 and fit["n"] >= 100 and scen["in_historical_range"] and abs(fit["r"]) >= 0.5:
        level = 0
    if abs(pct) > 15:
        level = max(level, 2)
        reasons.append("Large intervention size relative to observed variation.")
    return (["LOW", "MEDIUM", "HIGH"][level], reasons)


def _score(fit, pct, control_level):
    """Transparent 0–100 ranking (§14): components, never a mystery number."""
    comps = {
        "evidence_strength": round(abs(fit["r"]) * 30, 1),          # 0–30
        "expected_impact": round(min(20.0, abs(scenario_for_pct(fit, pct)["rel_pct"]) * 2), 1),  # 0–20
        "confidence": round((15 if fit["p_value"] < 0.01 else 8 if fit["p_value"] < 0.05 else 0)
                            + min(10.0, fit["n"] / 20), 1),          # 0–25
        "controllability": {"controllable": 15, "potentially_controllable": 9,
                            "segmentation": 5, "not_controllable": 0}[control_level],  # 0–15
        "data_quality": round(min(10.0, fit["n"] / 50), 1),          # 0–10
    }
    total = round(sum(comps.values()), 1)
    return total, comps


# --------------------------------------------------------------------------
# Canonical quality gate (§3): ONE function every decision surface uses.
# Thresholds reuse the module's own bars (MIN_N, MIN_ABS_R); the two extra
# effect floors are documented here, never invented per-call.
# --------------------------------------------------------------------------
MIN_REL_PCT = 5.0    # negligible-effect floor: |rel_pct| below this is noise
MIN_COHENS_D = 0.2   # Cohen's "small" boundary: below this is NOT_ACTIONABLE
CAUSATION_WARNING = ("Historical data shows an association; it does not establish "
                     "that changing this variable will directly cause the predicted result.")


def quality_gate(evidence: dict | None, *, require_baseline: bool = False) -> dict:
    """Reject/downgrade weak evidence. Returns a code + reason, never a Decision.

    Codes: OK | INSUFFICIENT_DATA | WEAK_SIGNAL | NOT_ACTIONABLE.
    `evidence` is a plain dict (engine prescription evidence + impact +
    confidence merged by the caller via gate_input_from_prescription).
    """
    ev = evidence if isinstance(evidence, dict) else {}

    def _num(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f != f:  # NaN-safe
            return None
        return f

    metric = ev.get("metric")
    n = ev.get("n")
    try:
        n = int(n) if n is not None else None
    except (TypeError, ValueError):
        n = None
    p = _num(ev.get("p_value"))
    r = _num(ev.get("r") if ev.get("r") is not None else ev.get("effect_r"))
    rel = _num(ev.get("rel_pct") if ev.get("rel_pct") is not None
               else ev.get("effect_gap_pct"))
    d = _num(ev.get("cohens_d"))
    conf = str(ev.get("confidence") or "").strip().lower()
    baseline = ev.get("baseline")
    delta = ev.get("delta")
    control = str(ev.get("control_level") or ev.get("control") or "").lower()

    def _refuse(code, reason):
        try:
            from core.evidence import quality_gate_status as _qgs
            _status = _qgs(code)
        except Exception:
            _status = "insufficient_evidence"
        return {"pass": False, "code": code, "reason": reason,
                "status": _status,
                "evidence_quality": "Limited",
                "confidence": ev.get("confidence") if ev.get("confidence") else "Limited"}

    if not ev:
        return _refuse("INSUFFICIENT_DATA", "No evidence was computed for this driver.")
    if not metric:
        return _refuse("INSUFFICIENT_DATA", "No measurable target metric is attached to this evidence.")
    if ev.get("metric_reliable") is False:
        return _refuse("INSUFFICIENT_DATA", "The target metric failed the reliability check.")
    if n is None or n < MIN_N:
        return _refuse("INSUFFICIENT_DATA",
                       f"Only {n if n is not None else 0} usable observations — "
                       f"at least {MIN_N} are needed.")
    if p is None:
        return _refuse("INSUFFICIENT_DATA", "No significance test supports this driver yet.")
    if p >= 0.05:
        return _refuse("WEAK_SIGNAL", f"Not statistically significant (p={p:.3f} ≥ 0.05).")
    if r is not None and abs(r) < MIN_ABS_R:
        return _refuse("WEAK_SIGNAL",
                       f"Negligible association (|r|={abs(r):.2f} < {MIN_ABS_R:.2f}).")
    if rel is not None and abs(rel) < MIN_REL_PCT:
        return _refuse("NOT_ACTIONABLE",
                       f"Negligible effect ({rel:+.1f}% < ±{MIN_REL_PCT:g}% materiality floor).")
    if d is not None and abs(d) < MIN_COHENS_D:
        return _refuse("NOT_ACTIONABLE",
                       f"Tiny effect size (Cohen's d={d:.2f} < {MIN_COHENS_D:g}).")
    if conf in ("", "unknown", "none"):
        return _refuse("INSUFFICIENT_DATA",
                       "Confidence is unquantified — no validated decision can be made.")
    if ev.get("rank_consistent") is False:
        return _refuse("WEAK_SIGNAL",
                       "Unstable link — rank-based check disagrees with the linear fit.")
    _sp = _num(ev.get("spearman_r"))
    if r is not None and _sp is not None and abs(r - _sp) > 0.4:
        return _refuse("WEAK_SIGNAL",
                       f"Unstable link (Pearson {r:+.2f} vs Spearman {_sp:+.2f}).")
    if control in ("not_controllable", "segmentation"):
        return _refuse("NOT_ACTIONABLE",
                       "This field describes groups; it cannot be moved as an intervention.")
    if require_baseline:
        try:
            b = float(baseline) if baseline is not None else None
        except (TypeError, ValueError):
            b = None
        try:
            dl = float(delta) if delta is not None else None
        except (TypeError, ValueError):
            dl = None
        if b is None:
            return _refuse("INSUFFICIENT_DATA",
                           "No measured baseline — the impact cannot be quantified.")
        if dl is None and rel is None:
            return _refuse("INSUFFICIENT_DATA",
                           "Impact is unquantifiable — no modeled delta or relative change.")

    quality = "Moderate"
    try:
        strong = (p < 0.01 and n >= 100 and
                  ((r is not None and abs(r) >= 0.5) or (d is not None and abs(d) >= 0.8)))
    except TypeError:
        strong = False
    if strong:
        quality = "Strong"
    try:
        from core.evidence import quality_gate_status as _qgs2
        _ok_status = _qgs2("OK")
    except Exception:
        _ok_status = "supported"
    return {"pass": True, "code": "OK", "reason": None,
            "status": _ok_status,
            "evidence_quality": quality, "confidence": ev.get("confidence")}


def gate_input_from_prescription(rec: dict, *, require_baseline: bool = True) -> dict:
    """Merge one engine prescription into a quality_gate input dict."""
    rec = rec if isinstance(rec, dict) else {}
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    imp = rec.get("impact") if isinstance(rec.get("impact"), dict) else {}
    return {
        "metric": rec.get("metric") or ev.get("metric"),
        "n": ev.get("n"),
        "p_value": ev.get("p_value"),
        "r": ev.get("effect_r", ev.get("r")),
        "effect_r": ev.get("effect_r", ev.get("r")),
        "spearman_r": ev.get("spearman_r"),
        "rank_consistent": ev.get("rank_consistent"),
        "rel_pct": imp.get("rel_pct"),
        "effect_gap_pct": ev.get("effect_gap_pct"),
        "cohens_d": ev.get("cohens_d"),
        "baseline": imp.get("baseline"),
        "delta": imp.get("delta"),
        "confidence": rec.get("confidence"),
        "control_level": rec.get("control_level"),
        "validation_method": ev.get("validation_method") or rec.get("validation_method"),
    }


def priority_score(rec: dict) -> tuple:
    """Transparent Priority (0–100): Impact × Confidence × Urgency ×
    Actionability × EvidenceQuality. Reuses this module's _score
    components plus impact rel% + p/n. Returns (total, breakdown)."""
    rec = rec if isinstance(rec, dict) else {}
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    imp = rec.get("impact") if isinstance(rec.get("impact"), dict) else {}
    comps_in = rec.get("score_breakdown") if isinstance(rec.get("score_breakdown"), dict) else {}

    def _num(v, default=0.0):
        try:
            f = float(v)
            return f if f == f else default
        except (TypeError, ValueError):
            return default

    rel = imp.get("rel_pct")
    if rel is None:
        rel = ev.get("effect_gap_pct")
    impact_c = round(min(30.0, abs(_num(rel)) * 1.5), 1)                      # 0–30
    conf = str(rec.get("confidence") or "").lower()
    base = {"high": 20.0, "moderate": 12.0, "medium": 12.0, "low": 4.0}.get(conf, 0.0)
    p = _num(ev.get("p_value"), 1.0)
    bonus = 5.0 if p < 0.01 else (2.0 if p < 0.05 else 0.0)
    confidence_c = round(min(25.0, base + bonus), 1)                          # 0–25
    rp = str(rec.get("review_period") or "").lower()
    if "2 week" in rp:
        urgency_c = 10.0
    elif "4 week" in rp:
        urgency_c = 8.0
    elif "quarter" in rp or "month" in rp:
        urgency_c = 7.0
    else:
        urgency_c = 5.0                                                      # 0–10
    atype = str(rec.get("action_type") or "").lower()
    ctrl = _num(comps_in.get("controllability"), -1)
    if atype == "scenario":
        action_c = 20.0 if ctrl >= 15 else (14.0 if ctrl >= 9 else 10.0) if ctrl >= 0 else 12.0
    elif atype == "investigate":
        action_c = 10.0
    elif atype == "qualitative":
        action_c = 6.0
    else:
        action_c = 8.0                                                       # 0–20
    try:
        nn = int(ev.get("n")) if ev.get("n") is not None else 0
    except (TypeError, ValueError):
        nn = 0
    evidence_c = round(min(15.0, min(10.0, nn / 50.0)
                           + (5.0 if ev.get("rank_consistent") else 0.0)), 1)  # 0–15
    comps = {"impact": impact_c, "confidence": confidence_c, "urgency": urgency_c,
             "actionability": round(action_c, 1), "evidence_quality": evidence_c}
    return min(100.0, round(sum(comps.values()), 1)), comps


# ---------------------------------------------------------------------------
# Model-layer deduplication (hyp §§16-17 + §22): finding + unordered
# metric pair + scope + direction + analytical-basis identity — NEVER title
# string matching.
# "Test a 20% increase in Milliseconds" vs "Test a 45% increase in
# Milliseconds" vs "Test a 45% increase in Bytes (other table, same story)"
# share one key when the underlying finding is the same and collapse to the
# highest-scoring card. Scenario variants (+20/+30/+45%) belong INSIDE the
# surviving decision (`scenario_options`), not as cards. ONE finding → ONE
# decision context.
# §22: the pair is UNORDERED — "Milliseconds → Bytes" and
# "Bytes → Milliseconds" are the same bidirectional correlation evaluated
# in both directions and must collapse to one decision, never two cards.
# ---------------------------------------------------------------------------
def dedupe_key(rec: dict) -> tuple:
    """Duplicate identity for one prescription/decision card."""
    rec = rec if isinstance(rec, dict) else {}
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    imp = rec.get("impact") if isinstance(rec.get("impact"), dict) else {}
    metric = rec.get("metric") or ev.get("metric")
    driver = rec.get("driver") or ev.get("driver")
    scope = rec.get("table") or ev.get("table")
    try:
        _pct = imp.get("driver_pct")
        _pct = float(_pct) if _pct is not None else 0.0
        direction = "up" if _pct > 0 else "down" if _pct < 0 else "flat"
    except (TypeError, ValueError):
        direction = "flat"
    r = ev.get("effect_r", ev.get("r"))
    try:
        _r = float(r) if r is not None else None
    except (TypeError, ValueError):
        _r = None
    gap = ev.get("effect_gap_pct")
    try:
        _gap = float(gap) if gap is not None else None
    except (TypeError, ValueError):
        _gap = None
    if _r is not None:
        basis = "pos" if _r > 0 else "neg" if _r < 0 else "none"
    elif _gap is not None:
        basis = "gap"
    else:
        basis = "none"
    finding = rec.get("action_type") or rec.get("scenario_label") or ""
    _m = str(metric or "").lower().strip()
    _d = str(driver or "").lower().strip()
    _pair = tuple(sorted([_m, _d]))
    return (_pair,
            str(scope or "").lower(), direction, basis,
            str(finding or "").lower())


def dedupe_prescriptions(recs: list) -> list:
    """Collapse model-layer duplicates, keeping the highest score each."""
    best, order = {}, []

    def _score_of(r):
        try:
            return float((r or {}).get("priority_score",
                                       (r or {}).get("score", 0)) or 0)
        except (TypeError, ValueError):
            return 0.0

    for r in (recs or []):
        k = dedupe_key(r if isinstance(r, dict) else {})
        if k not in best:
            best[k] = r
            order.append(k)
        elif _score_of(r) > _score_of(best[k]):
            best[k] = r
    return [best[k] for k in order]


# --------------------------------------------------------------------------
# Orchestrator (§4 pipeline)
# --------------------------------------------------------------------------
def _join_key_cols(intel, table):
    """Lowercased join-key columns touching `table` (declared edges + FKs).

    Generalized: derived from the schema mapping, never column literals.
    Join keys relate records; they are not business levers (§4).
    """
    keys = set()
    try:
        for e in ((intel.mapping or {}).get("relationship_edges") or []):
            s, sc = e.get("source_table"), e.get("source_column")
            t, tc = e.get("target_table"), e.get("target_column")
            if s == table and sc:
                keys.add(str(sc).lower())
            if t == table and tc:
                keys.add(str(tc).lower())
    except Exception:
        pass
    try:
        for c, _rt, _rc in intel.get_fks(table):
            keys.add(str(c).lower())
    except Exception:
        pass
    return keys


def _usable_measures(intel, table):
    """Numeric columns eligible as metric/lever candidates (§4).

    Excludes, by generalized rule (never per-column literals): PKs, FKs,
    join keys, identifier-like names, datetime-like names, technical
    measurements, system metadata/counters/encodings. A numeric column
    that merely CAN be increased/decreased is not automatically actionable
    — semantic-role + actionability gates decide downstream.
    """
    fks = {f[0].lower() for f in intel.get_fks(table)}
    pks = {p.lower() for p in intel.get_pk(table)}
    join_keys = _join_key_cols(intel, table)
    out = []
    for c in intel.get_numeric_cols(table):
        low = c.lower()
        if low in fks or low in pks or low in join_keys:
            continue
        if low.endswith(("_id", "_key", "_no", "_code")) or low in ("id", "key", "code"):
            continue
        role = classify_semantic_role(
            c, "numeric", is_pk=(low in pks), is_fk=(low in fks),
            is_join_key=(low in join_keys))
        if role in NON_OUTCOME_ROLES or role in NON_LEVER_ROLES:
            continue
        out.append(c)
    return out


def _edge_neighbors(intel, table):
    """1-hop declared FK neighbors: (other_table, self_col, other_col).

    Only declared/inferred edges from the schema mapping — never guessed
    joins. Self-table edges and duplicate pairs are skipped.
    """
    out, seen = [], set()
    for e in (intel.mapping.get("relationship_edges") or []):
        s, sc = e.get("source_table"), e.get("source_column")
        t, tc = e.get("target_table"), e.get("target_column")
        if not (s and sc and t and tc):
            continue
        if s == table and t != table:
            key, row = (t, sc, tc), (t, sc, tc)
        elif t == table and s != table:
            key, row = (s, tc, sc), (s, tc, sc)
        else:
            continue
        if key not in seen:
            seen.add(key)
            out.append(row)
    for c, rt, rc in intel.get_fks(table):
        key = (rt, c, rc)
        if rt != table and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _stay_lengths(engine, dialect, table, c1, c2, metric, limit=SAMPLE_LIMIT):
    """Derived driver: days between two date columns vs the metric.

    Fully data-based (any table with 2+ dates + a numeric metric). Date
    parsing happens in Python so PG/MySQL/SQLite all behave identically.
    Returns (nights_list, metric_list) or (None, None) when unusable.
    """
    import pandas as pd
    from api.schema_intel import _safe_name
    try:
        rows = _exec(engine,
                     f"SELECT {_safe_name(c1, dialect)}, {_safe_name(c2, dialect)}, "
                     f"{_safe_name(metric, dialect)} FROM {_safe_name(table, dialect)} "
                     f"WHERE {_safe_name(c1, dialect)} IS NOT NULL "
                     f"AND {_safe_name(c2, dialect)} IS NOT NULL "
                     f"AND {_safe_name(metric, dialect)} IS NOT NULL "
                     f"LIMIT {int(limit)}")
    except Exception:
        return None, None
    if len(rows) < MIN_N:
        return None, None
    t1 = pd.Series(pd.to_datetime([r[0] for r in rows], errors="coerce"))
    t2 = pd.Series(pd.to_datetime([r[1] for r in rows], errors="coerce"))
    vals = pd.Series(pd.to_numeric([r[2] for r in rows], errors="coerce"))
    ok = t1.notna() & t2.notna() & vals.notna()
    if int(ok.sum()) < MIN_N:
        return None, None
    nights = ((t2[ok] - t1[ok]).dt.total_seconds() / 86400.0).to_numpy()
    ys = vals[ok].to_numpy(dtype=float)
    # Negative or absurd durations are data errors, not stays.
    mask = (nights >= 0) & (nights <= 365)
    if int(mask.sum()) < MIN_N:
        return None, None
    return nights[mask].tolist(), ys[mask].tolist()


def _kruskal_p(groups):
    """Kruskal-Wallis p across group arrays; None when scipy is absent."""
    if not _SCIPY_OK:
        return None
    try:
        _, p = _st.kruskal(*groups)
        return float(p)
    except Exception:
        return None


def _investigate_cands(engine, dialect, intel, table, metric, m_h,
                       review=None, review_basis=None):
    """Investigate-type prescriptions (§10/§22) from real segment gaps.

    For dimensions with 2–12 well-populated groups: Kruskal-Wallis + the
    top-vs-bottom gap. No simulated impact — the gap is OBSERVED evidence
    that names where to look next, never an invented intervention.
    """
    from core.semantic import humanize
    out = []
    for dim in intel.find_all_dimensions(table)[:3]:
        try:
            rows = _fetch_pairs(engine, dialect, table, dim, metric)
        except Exception:
            continue
        groups = {}
        for g, v in rows:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            groups.setdefault(str(g), []).append(fv)
        groups = {g: vs for g, vs in groups.items() if len(vs) >= 5}
        if not (2 <= len(groups) <= 12):
            continue
        arrs = [np.asarray(vs, dtype=float) for vs in groups.values()]
        p = _kruskal_p(arrs)
        if p is None or p >= 0.05:
            continue
        means = {g: sum(vs) / len(vs) for g, vs in groups.items()}
        overall = sum(means.values()) / len(means) if means else 0.0
        top = max(means, key=means.get)
        bottom = min(means, key=means.get)
        gap = ((means[top] - means[bottom]) / abs(overall)) if overall else 0.0
        if abs(gap) < 0.10:
            continue
        n = sum(len(vs) for vs in groups.values())
        d_h = humanize(dim)
        segs = sorted(((g, means[g], len(groups[g])) for g in groups),
                      key=lambda t: t[1], reverse=True)[:6]
        conf = ("high" if p < 0.01 and n >= 50 else "moderate")
        out.append({
            "id": f"rxinv_{table}_{metric}_{dim}",
            "rank": 0, "title": f"Investigate {d_h} performance for {m_h}: {top} vs {bottom}",
            "summary": (f"{m_h} differs across {d_h} ({top} averages {means[top]:,.1f} vs "
                        f"{bottom} at {means[bottom]:,.1f}, a {gap * 100:+.1f}% gap, p={p:.3f}). "
                        f"These groups are observed alongside the difference — association only, "
                        f"so investigate the cause before acting."),
            "action_type": "investigate", "scenario_label": "investigate",
            # hyp §13: a segment gap with no modeled intervention is an
            # Insight (a meaningful interpretation), never an Opportunity.
            "decision_type": "insight",
            "confidence": conf, "risk": "low",
            "risk_reasons": ["No intervention is modeled — this only directs investigation."],
            "score": round(min(60.0, abs(gap) * 100) + (15 if p < 0.01 else 8)
                           + min(10.0, n / 50), 1),
            "score_breakdown": {"observed_gap": round(min(30.0, abs(gap) * 100), 1),
                                "confidence": round(15 if p < 0.01 else 8, 1),
                                "data_quality": round(min(10.0, n / 50), 1)},
            "evidence": {"metric": metric, "driver": dim, "table": table,
                         "effect_gap_pct": round(gap * 100, 1), "p_value": p, "n": n,
                         "groups": [{"label": g, "mean": round(mn, 2), "n": cn}
                                    for g, mn, cn in segs],
                         "top": top, "bottom": bottom, "segment": None},
            "success_metric": {"metric": metric,
                               "direction": f"lift {bottom} toward {top} levels",
                               "target_pct": None,
                               "baseline": round(means[bottom], 2),
                               "note": "No modeled target yet — set one once investigation names the driver."},
            "review_period": review,
            "review_basis": review_basis,
            "impact": {"baseline": round(means[bottom], 2),
                       "scenario": round(means[top], 2),
                       "delta": round(means[top] - means[bottom], 2),
                       "rel_pct": round(gap * 100, 1),
                       "range": [round(means[bottom], 2), round(means[top], 2)],
                       "driver_pct": 0, "driver_value": None,
                       "labels": {"baseline": "OBSERVED", "scenario": "OBSERVED"}},
            "assumptions": ["Groups observed as-is; mix and other factors not separated."],
            "limitations": [
                f"Gap computed over {n} rows; smaller groups ({min(len(v) for v in groups.values())} rows) are noisier.",
                "A gap shows where to look — it does not say what to change.",
                "Historical data shows an association; it does not establish causality.",
            ],
            "recommended_next_analysis": {
                "type": "hypothesis",
                "label": f"Test whether {m_h} truly differs across {d_h} and what drives it."},
        })
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:2]


def _investigate_response(inv, metric, table, m_h, priors):
    """Completed response carrying only investigate prescriptions (no
    scenarios exist, but real segment evidence does)."""
    for i, c in enumerate(inv):
        c["rank"] = i + 1
    top = inv[0]
    from core.semantic import humanize as _hh
    story = (f"No adjustable driver for {m_h} cleared the evidence bar, but "
             f"{m_h} differs meaningfully across {_hh(top['evidence']['driver'])} "
             f"({top['evidence']['effect_gap_pct']:+.1f}% gap). "
             f"Investigation is warranted before any intervention.")
    # hyp.txt §10-11: investigate path carries real group evidence, so it
    # must also carry a chart-ready spec (bar of group means). Never None
    # when groups exist — _build_visual renders this without re-querying.
    _viz = None
    try:
        _groups = top.get("evidence", {}).get("groups") or []
        _rows = []
        for g in _groups:
            if not isinstance(g, dict):
                continue
            if g.get("label") is None or g.get("mean") is None:
                continue
            try:
                _val = float(g.get("mean"))
            except (TypeError, ValueError):
                continue
            if _val != _val:  # NaN-safe
                continue
            _rows.append({"name": str(g.get("label")), "value": _val})
        if len(_rows) >= 2:
            _title = f"{m_h} by {_hh(top['evidence']['driver'])}"
            try:
                from api.insights_routes import _normalize_chart_spec as _norm
                _spec = _norm("bar", _rows[:200], _title)
                if isinstance(_spec, dict) and not _spec.get("unsupported") \
                        and not _spec.get("insufficient") and _spec.get("data"):
                    _viz = {"type": "bar", "data": _spec["data"],
                            "title": _spec.get("title") or _title,
                            "x": _spec.get("x") or "name",
                            "y": _spec.get("y") or "value"}
                else:
                    _viz = {"type": "bar", "data": _rows[:200],
                            "title": _title, "x": "name", "y": "value"}
            except Exception:
                _viz = {"type": "bar", "data": _rows[:200],
                        "title": _title, "x": "name", "y": "value"}
    except (TypeError, ValueError):
        _viz = None
    return {"ok": True, "success": True, "status": "completed",
            "analysis_id": f"rxa_{table}_{metric}_investigate",
            "metric": metric, "driver": top["evidence"]["driver"],
            "table": table, "driver_table": table, "join": None, "join_ref": None,
            "control": {"level": "investigation",
                        "reason": "No intervention modeled — evidence directs investigation."},
            "auto_note": None, "fit": None, "evidence_viz": _viz,
            "prescriptions": inv,
            "signals": {"supporting": 1,
                        "priors_origin": (priors or {}).get("origin")},
            "story": story,
            "summary_plain": _plain_summary(m_h, top["evidence"]["driver"], None, top)}


def _date_like_cols(intel, table):
    """Datetime columns plus date-hinted text columns (CSV dates arrive as
    TEXT in SQLite — same fallback rule as the schema layer)."""
    cols = list(intel.get_datetime_cols(table) or [])
    for c in intel.get_text_cols(table) or []:
        low = c.lower()
        if c not in cols and any(h in low for h in ("date", "time", "day", "month",
                                                   "year", "created", "updated",
                                                   "timestamp", "period")):
            cols.append(c)
    return cols


def _review_period(engine, dialect, table, intel):
    """Review cadence from the data's own time span — never a guess.

    Returns (period_label, basis). No date column → one business cycle.
    """
    dts = (intel.get_datetime_cols(table) or [])[:1]
    if not dts:
        for c in intel.get_text_cols(table):
            low = c.lower()
            if any(h in low for h in ("date", "time", "day", "month", "year", "period")):
                dts = [c]
                break
    if dts:
        try:
            from api.schema_intel import _safe_name
            rows = _exec(engine,
                         f"SELECT MIN({_safe_name(dts[0], dialect)}), "
                         f"MAX({_safe_name(dts[0], dialect)}) "
                         f"FROM {_safe_name(table, dialect)}")
            if rows and rows[0][0] is not None and rows[0][1] is not None:
                import pandas as pd
                lo = pd.to_datetime(rows[0][0], errors="coerce")
                hi = pd.to_datetime(rows[0][1], errors="coerce")
                if pd.notna(lo) and pd.notna(hi):
                    span = max(0, (hi - lo).days)
                    if span <= 14:
                        return "2 weeks", f"data spans {span} days"
                    if span <= 62:
                        return "4 weeks", f"data spans {span} days"
                    if span <= 200:
                        return "one quarter", f"data spans {span} days"
                    return "6 months", f"data spans {span} days"
        except Exception:
            pass
    return "one full business cycle", "no usable time span in this data"


def _col_kind(intel, table, col):
    return intel._col_category.get(table, {}).get(col, "")


def _qi(name, dialect="postgresql"):
    """Quote one identifier part (table aliases qualify every column, so
    shared names like room_id never go ambiguous)."""
    if dialect == "mysql":
        return "`" + str(name).replace("`", "``") + "`"
    return '"' + str(name).replace('"', '""') + '"'


def _fetch_joined(engine, dialect, mtable, mcol, otable, ocol, self_col, other_col,
                  limit=SAMPLE_LIMIT):
    """Read-only joined driver/metric pairs across one declared edge."""
    mt, ot = _qi(mtable, dialect), _qi(otable, dialect)
    return _exec(engine,
                 f"SELECT o.{_qi(ocol, dialect)}, m.{_qi(mcol, dialect)} "
                 f"FROM {mt} m JOIN {ot} o ON "
                 f"m.{_qi(self_col, dialect)} = o.{_qi(other_col, dialect)} "
                 f"WHERE o.{_qi(ocol, dialect)} IS NOT NULL "
                 f"AND m.{_qi(mcol, dialect)} IS NOT NULL "
                 f"ORDER BY 1, 2 "
                 f"LIMIT {int(limit)}")


def _segment_extreme(engine, dialect, table, dim, metric):
    """Weakest group by mean(metric) — headroom target. Returns (value, mean)."""
    rows = _fetch_pairs(engine, dialect, table, dim, metric, limit=SAMPLE_LIMIT)
    groups = {}
    for g, v in rows:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        groups.setdefault(str(g), []).append(fv)
    groups = {g: vs for g, vs in groups.items() if len(vs) >= 5}
    if len(groups) < 2:
        return None
    means = {g: sum(vs) / len(vs) for g, vs in groups.items()}
    weak = min(means, key=means.get)
    return {"field": dim, "value": weak, "mean": means[weak],
            "overall": sum(means.values()) / len(means)}


def _dynamic_limitations(fit, scen, targeted, driver_h):
    """Limitations computed from THIS evidence — never boilerplate (§20).

    Each entry names the actual numbers behind it, so two datasets never
    get the same list unless their evidence matches.
    """
    lim = []
    n = fit["n"]
    if n < 30:
        lim.append(f"Small sample: only {n} usable observations — treat every estimate as rough.")
    elif n < 100:
        lim.append(f"Modest sample of {n} observations — direction is informative, exact sizes less so.")
    r = abs(fit["r"])
    if r < 0.5:
        lim.append(f"Relationship strength is moderate (r={fit['r']:+.2f}) — {driver_h} explains only part of the movement.")
    if abs(fit["r"] - fit["spearman_r"]) > 0.25 or (fit["r"] > 0) != (fit["spearman_r"] > 0):
        lim.append(f"Rank-based check disagrees (Pearson {fit['r']:+.2f} vs Spearman {fit['spearman_r']:+.2f}) — a few extreme rows may drive the result.")
    if not scen["in_historical_range"]:
        lim.append(f"This scenario pushes the driver to {scen['driver_value']:,.2f}, outside its observed range "
                   f"({fit['x_min']:,.2f}–{fit['x_max']:,.2f}) — extrapolation, not interpolation.")
    if targeted:
        lim.append(f"Targeted at '{targeted['value']}' ({targeted['field']}) — segment estimates rest on fewer rows than the full table.")
    lim.append("Historical data shows an association; it does not establish "
               "that changing this variable will directly cause the predicted result.")
    return lim


def _plain_summary(m_h, d_h, fit, rec, join_phrase=None):
    """Plain-English summary of the whole analysis — a normal person reads
    only this and understands what was tested, found, and recommended."""
    if rec.get("action_type") == "investigate":
        ev = rec.get("evidence", {})
        gs = ev.get("groups", [])
        top_mean = gs[0]["mean"] if gs else "?"
        bot_mean = gs[-1]["mean"] if gs else "?"
        return (
            f"We looked for an adjustable driver for {m_h.lower()} across "
            f"{ev.get('n', 0):,} rows but found no strong one. What we did find: "
            f"{ev.get('top')} averages {top_mean} vs "
            f"{ev.get('bottom')} at {bot_mean} "
            f"— a {ev.get('effect_gap_pct'):+.1f}% gap across {ev.get('driver')}. "
            f"Our recommendation: {rec['title']}. Start by finding what is "
            f"associated with the difference — a gap shows where to look, not what to change."
        )
    direction = "go up together" if fit["slope"] > 0 else "move in opposite directions"
    strength = ("strong" if abs(fit["r"]) >= 0.7 else "moderate" if abs(fit["r"]) >= 0.5 else "noticeable")
    r_imp = rec["impact"]
    m, d = m_h.lower(), d_h.lower()
    return (
        f"We tested whether {d} is associated with {m}, using {fit['n']:,} rows of your data. "
        f"The two {direction} ({strength} association, r={fit['r']:+.2f})"
        + (f", measured {join_phrase}" if join_phrase else "")
        + ". "
        f"Our recommendation: {rec['title']}: "
        f"{m} would go from about {r_imp['baseline']:,.1f} to about {r_imp['scenario']:,.1f} "
        f"({r_imp['rel_pct']:+.1f}%), within a range of {r_imp['range'][0]:,.1f} to {r_imp['range'][1]:,.1f}. "
        f"Confidence is {rec['confidence']}, risk is {rec['risk']} — and this is an association in past data, not a promise of future results."
    )


def analyze(engine, dialect, intel, table, metric, driver=None,
            dimensions=None, segment=None, question=None, priors=None):
    """Full prescription pipeline. Returns ranked prescriptions or a
    no_prescription refusal (§23) — never an invented action."""
    from core.semantic import humanize
    priors = priors or {}

    # 1) Validate metric (§34/§35: schema-discovered, never assumed).
    # hyp.txt §10-11: the metric must be a genuine business outcome,
    # determined semantically (never hardcoded lever→outcome mappings). A
    # technical/system measurement is analytic signal — strong correlations
    # stay evidence, but no actionable recommendation is generated.
    measures = _usable_measures(intel, table)
    if metric not in measures:
        if metric in intel.get_numeric_cols(table):
            _mpks = {p.lower() for p in intel.get_pk(table)}
            _mfks = {f[0].lower() for f in intel.get_fks(table)}
            _mrole = classify_semantic_role(
                metric, "numeric", is_pk=(metric.lower() in _mpks),
                is_fk=(metric.lower() in _mfks),
                is_join_key=(metric.lower() in _join_key_cols(intel, table)))
            if _mrole in NON_OUTCOME_ROLES:
                return {"ok": True, "success": True, "status": "no_prescription",
                        "reason": (f"{_disp(metric)} is a {_mrole.lower().replace('_', ' ')} — useful for "
                                   f"analysis, but ARIA does not turn associations involving technical/system "
                                   f"measurements into actionable recommendations. Association is evidence of "
                                   f"association, not evidence of an actionable driver."),
                        "alternatives": ["Investigate Driver", "Test Hypothesis", "Explore Data", "Ask ARIA"],
                        "metric": metric, "table": table}
        return _fail(CODE_INVALID_METRIC,
                     f"ARIA couldn't find a measurable '{metric}' in this data.",
                     available_metrics=[{"table": table, "column": c} for c in measures[:8]])
    dims = [d for d in (dimensions or [])
            if d in (intel.get_text_cols(table) + intel.get_datetime_cols(table)
                     + intel.get_numeric_cols(table))]
    # Review cadence from the data's own time span (one bounded query).
    review, review_basis = _review_period(engine, dialect, table, intel)

    # 2) Driver: explicit > prior > auto-strongest-evidence (§7).
    # Candidates are (column, join) with join=None for same-table or
    # (other_table, self_col, other_col) across ONE declared FK edge.
    # Guards fail loudly with the reason — never a silent wrong-pair analysis.
    if driver and driver == metric:
        return _fail(CODE_INVALID_DRIVER,
                     f"'{metric}' can't be both the target and the driver. Pick a different driver.")
    # hyp.txt §§4-6: an explicitly requested driver still needs semantic
    # actionability. A correlation with a technical/system field is supporting
    # evidence ONLY — it never becomes a "Test X% increase" lever, no matter
    # how strong the correlation is.
    if driver and driver != "length_of_stay":
        _dpks = {p.lower() for p in intel.get_pk(table)}
        _dfks = {f[0].lower() for f in intel.get_fks(table)}
        _dkeys = _join_key_cols(intel, table)
        _dkind = _col_kind(intel, table, driver)
        _drole = classify_semantic_role(
            driver, _dkind or "numeric", is_pk=(str(driver).lower() in _dpks),
            is_fk=(str(driver).lower() in _dfks),
            is_join_key=(str(driver).lower() in _dkeys))
        if _drole in NON_LEVER_ROLES:
            return {"ok": True, "success": True, "status": "no_prescription",
                    "reason": (f"{_disp(driver)} is a {_drole.lower().replace('_', ' ')} — ARIA keeps the "
                               f"association with {_disp(metric)} as supporting evidence, but it cannot be "
                               f"moved as an intervention. Association is evidence of association, not evidence "
                               f"of an actionable driver."),
                    "alternatives": ["Investigate Driver", "Test Hypothesis", "Explore Data", "Ask ARIA"],
                    "metric": metric, "driver": driver, "table": table}
    neighbors = _edge_neighbors(intel, table)
    auto_note = None
    if driver == "length_of_stay":
        dts = _date_like_cols(intel, table)[:3]
        if len(dts) < 2:
            return _fail(CODE_INVALID_DRIVER,
                         "Stay length needs two date columns, which this table doesn't have.")
        nights, ys = _stay_lengths(engine, dialect, table, dts[0], dts[1], metric)
        if nights is None:
            return _fail(CODE_INSUFFICIENT_DATA,
                         "Not enough dated rows to measure stay length against "
                         f"{_disp(metric)}.")
        f = fit_relationship(nights, ys)
        if not (f and abs(f["r"]) >= MIN_ABS_R and f["p_value"] < 0.05):
            return {"ok": True, "success": True, "status": "no_prescription",
                    "reason": (f"ARIA measured stay length against {_disp(metric)} but the link "
                               f"is too weak to justify an intervention."),
                    "alternatives": ["Investigate Driver", "Test Hypothesis", "Explore Data", "Ask ARIA"],
                    "metric": metric, "table": table}
        best, best_fit, best_xy, best_join = "length_of_stay", f, (nights, ys), None
        cands = []
    elif driver:
        table_cols = (intel.get_numeric_cols(table) + intel.get_text_cols(table)
                      + intel.get_datetime_cols(table))
        if driver in table_cols:
            cands = [(driver, None)]
        else:
            cands = []
            for ot, sc, oc in neighbors:
                if driver in _usable_measures(intel, ot):
                    cands = [(driver, (ot, sc, oc))]
                    break
            if not cands:
                elsewhere = [t for t in intel.tables if t != table and driver in (
                    intel.get_numeric_cols(t) + intel.get_text_cols(t)
                    + intel.get_datetime_cols(t))]
                if elsewhere:
                    return _fail(CODE_INVALID_DRIVER,
                                 f"'{driver}' lives in {elsewhere[0]}, which has no declared link to "
                                 f"{table}. ARIA only joins tables over declared relationships. "
                                 f"Usable drivers here: {', '.join(_usable_measures(intel, table)[:5]) or 'none'}.")
                return _fail(CODE_INVALID_DRIVER,
                             f"ARIA couldn't find a usable '{driver}' field in this data.")
    else:
        cands = []
        for c in intel.get_numeric_cols(table):
            if c != metric and c in measures:
                cands.append((c, None))
        # Cross-table levers over declared joins (e.g. rooms.price_per_night
        # for bookings.total_amt) — discovered, never assumed.
        for ot, sc, oc in neighbors:
            for c in _usable_measures(intel, ot)[:4]:
                cands.append((c, (ot, sc, oc)))
        for c in intel.find_all_dimensions(table)[:4]:
            if all(c != cc for cc, _ in cands):
                cands.append((c, None))
    if driver != "length_of_stay":
        best, best_fit, best_xy, best_join = None, None, None, None
    tried_stay = False
    if not driver:
        # Derived stay-length driver: days between the first two date columns
        # vs the metric (booking-style tables). Data-derived, never assumed.
        dts = _date_like_cols(intel, table)[:3]
        if len(dts) >= 2:
            nights, ys = _stay_lengths(engine, dialect, table, dts[0], dts[1], metric)
            tried_stay = nights is not None
            if nights:
                f = fit_relationship(nights, ys)
                if f and abs(f["r"]) >= MIN_ABS_R and f["p_value"] < 0.05:
                    best, best_fit, best_xy = "length_of_stay", f, (nights, ys)
    for c, join in cands:
        # Self-correlation guard: a driver with the same name as the metric
        # (even across a join, e.g. rooms.price vs bookings.price) correlates
        # ~1.0 with itself and would render as "X moves with X". Never a lever.
        if str(c).lower() == str(metric).lower():
            continue
        if join is None and _col_kind(intel, table, c) != "numeric":
            continue
        try:
            if join is None:
                rows = _fetch_pairs(engine, dialect, table, c, metric)
            else:
                ot, sc, oc = join
                rows = _fetch_joined(engine, dialect, table, metric, ot, c, sc, oc)
            xs = [float(r[0]) for r in rows]
            ys = [float(r[1]) for r in rows]
        except (TypeError, ValueError):
            continue
        except Exception:
            continue
        f = fit_relationship(xs, ys)
        # Perfect correlation is a self-join/constant-column artifact, not a
        # discovery (|r|>=0.999 cannot be a controllable lever).
        if f and abs(f["r"]) >= 0.999:
            continue
        if f and abs(f["r"]) >= MIN_ABS_R and f["p_value"] < 0.05:
            if best_fit is None or abs(f["r"]) > abs(best_fit["r"]):
                best, best_fit, best_xy, best_join = c, f, (xs, ys), join
    if best_fit is None:
        # No evidence-backed driver — refuse (§3/§23), don't invent.
        # Name exactly what was testable so the refusal is data-specific.
        try:
            fit_n_total = len(_fetch_pairs(engine, dialect, table, metric, metric))
        except Exception:
            fit_n_total = 0
        numeric_tested = sorted({(c if j is None else f"{c} ({j[0]})")
                                 for c, j in cands
                                 if (j is not None or _col_kind(intel, table, c) == "numeric")})
        if not numeric_tested:
            reason = (f"{_disp(metric)} is the only measurable column reachable from {table} — "
                      f"there are no other numbers in your data to test as drivers.")
        else:
            reason = (f"ARIA tested {', '.join(numeric_tested[:6])} against {_disp(metric)} "
                      f"({fit_n_total} usable rows) but found no relationship strong enough "
                      f"(need |r|≥0.30, p<0.05) to justify an intervention.")
        from core.semantic import humanize as _hz
        inv = _investigate_cands(engine, dialect, intel, table, metric, _hz(metric),
                                 review=review, review_basis=review_basis)
        if inv:
            return _investigate_response(inv, metric, table, _hz(metric), priors)
        return {"ok": True, "success": True, "status": "no_prescription",
                "reason": reason,
                "alternatives": ["Investigate Driver", "Test Hypothesis", "Explore Data", "Ask ARIA"],
                "metric": metric, "table": table}
    driver_used, fit = best, best_fit
    join_used = best_join
    join_label = (f"{table}.{join_used[1]} → {join_used[0]}.{join_used[2]}"
                  if join_used else None)
    driver_table = join_used[0] if join_used else table
    if not driver:
        auto_note = (f"ARIA selected {humanize(driver_used)} automatically as the strongest evidence-backed driver"
                     + (f" (measured {_join_phrase(join_used)})." if join_used else "."))
    # Controllability is judged on the driver wherever it lives.

    # 3) Controllability gate (§8) — typed by the DRIVER's own table,
    # which differs for cross-table drivers reached over a join. The derived
    # stay-length driver is numeric by construction.
    _driver_kind = ("numeric" if driver_used == "length_of_stay"
                    else _col_kind(intel, driver_table, driver_used))
    control_level, control_reason = classify_driver(driver_used, _driver_kind)
    if control_level in ("not_controllable", "segmentation"):
        from core.semantic import humanize as _hg
        inv0 = _investigate_cands(engine, dialect, intel, table, metric, _hg(metric),
                                  review=review, review_basis=review_basis)
        if inv0:
            return _investigate_response(inv0, metric, table, _hg(metric), priors)
        return {"ok": True, "success": True, "status": "no_prescription",
                "reason": (f"ARIA found a {control_level} pattern involving {_disp(driver_used)}, "
                           f"but the available data does not contain a controllable factor that can be "
                           f"reliably evaluated as an intervention. {control_reason}"),
                "alternatives": ["Investigate Driver", "Test Hypothesis", "Explore Data", "Ask ARIA"],
                "metric": metric, "driver": driver_used, "table": table,
                "evidence": {"r": fit["r"], "p_value": fit["p_value"], "n": fit["n"]}}

    # 4) Improvement direction + candidates (§9, hyp.txt §12).
    # Directionality is validated, never generically assumed: unknown
    # direction → no recommendation. The metric gate above already refuses
    # technical/system outcomes; this is the structural backstop.
    up_better, up_assump = improvement_up(metric)
    if up_better is None:
        return {"ok": True, "success": True, "status": "no_prescription",
                "reason": (f"ARIA cannot establish whether higher or lower values of {_disp(metric)} "
                           f"are desirable ({up_assump}). Without a justified direction, no actionable "
                           f"recommendation can be generated — the association stays supporting evidence only."),
                "alternatives": ["Investigate Driver", "Test Hypothesis", "Explore Data", "Ask ARIA"],
                "metric": metric, "driver": driver_used, "table": table,
                "evidence": {"r": fit["r"], "p_value": fit["p_value"], "n": fit["n"]}}
    # Explicit fallback assumption (no recognized outcome semantics): the
    # recommendation is allowed for business-plausible metrics but carries
    # capped confidence — the assumption is recorded, never silent.
    _dir_fallback = up_assump.startswith("no outcome semantics")
    # Full actionability verdict (§6): correlation + controllability +
    # outcome + justified direction. Correlation alone never suffices.
    _metric_role = classify_semantic_role(metric, "numeric")
    _lever_role = classify_semantic_role(driver_used, _driver_kind or "numeric")
    _gate = assess_actionability(driver_used, _lever_role, control_level,
                                 metric_role=_metric_role,
                                 direction_known=(up_better is not None),
                                 has_evidence=True)
    if not _gate["actionable"]:
        from core.semantic import humanize as _hg2
        inv0b = _investigate_cands(engine, dialect, intel, table, metric, _hg2(metric),
                                   review=review, review_basis=review_basis)
        if inv0b:
            return _investigate_response(inv0b, metric, table, _hg2(metric), priors)
        return {"ok": True, "success": True, "status": "no_prescription",
                "reason": (f"{_disp(driver_used)} does not clear the actionability bar "
                           f"({'; '.join(_gate['notes']) or 'unmet conditions'}). The association with "
                           f"{_disp(metric)} stays supporting evidence only."),
                "alternatives": ["Investigate Driver", "Test Hypothesis", "Explore Data", "Ask ARIA"],
                "metric": metric, "driver": driver_used, "table": table,
                "evidence": {"r": fit["r"], "p_value": fit["p_value"], "n": fit["n"]}}
    # Move the driver so the metric improves: sign = +1 means increase driver.
    move = 1 if ((fit["slope"] > 0) == up_better) else -1
    verb = "increase" if move > 0 else "reduction"
    # Preset sizes from the driver's OWN typical movement — never fixed
    # percentages. Sized as fractions of one standard deviation of the
    # observed driver values (0.25σ / 0.5σ / 1σ), clamped to the observed
    # in-range maximum so conservative+recommended stay interpolations
    # (green) and only stretch may extrapolate (amber). Absolute ceilings
    # mirror the ±50% refusal boundary; they are safety rails, not findings.
    _xs = np.asarray(best_xy[0], dtype=float) if best_xy else np.asarray([], dtype=float)
    _xmean = float(_xs.mean()) if len(_xs) else fit["x_mean"]
    _xstd = float(_xs.std()) if len(_xs) > 1 else 0.0
    if not _xmean or not _xstd:
        return {"ok": True, "success": True, "status": "no_prescription",
                "reason": (f"Cannot compute scenario: driver '{humanize(driver_used)}' "
                           f"has zero mean or zero variance in the observed data."),
                "alternatives": ["Investigate Driver", "Test Hypothesis", "Explore Data", "Ask ARIA"],
                "metric": metric, "driver": driver_used, "table": table,
                "evidence": {"r": fit["r"], "p_value": fit["p_value"], "n": fit["n"]}}
    _typical = abs(_xstd / _xmean * 100) if _xmean else 10.0
    _edge = ((fit["x_max"] - _xmean) / abs(_xmean) * 100) if move > 0 else ((_xmean - fit["x_min"]) / abs(_xmean) * 100)
    _edge = max(0.0, min(50.0, _edge if _edge == _edge else 0.0))  # NaN-safe
    def _size(k, floor, ceil):
        raw = _typical * k
        raw = min(raw, _edge) if _edge > 0 else raw
        return round(min(ceil, max(floor, raw)), 1)
    pcts = [_size(0.25, 1.0, 10.0) * move, _size(0.5, 2.0, 20.0) * move,
            _size(1.0, 5.0, 45.0) * move]
    # Dedupe (flat data can collapse sizes) while preserving order.
    seen, _uniq = set(), []
    for _p in pcts:
        if abs(_p) not in seen:
            seen.add(abs(_p))
            _uniq.append(_p)
    while len(_uniq) < 3:
        _grow = min(45.0, abs(_uniq[-1]) * 1.5 + 1.0)
        _uniq.append(round(_grow, 1) * (1 if move > 0 else -1))
    pcts = _uniq[:3]
    m_h, d_h = humanize(metric), humanize(driver_used)

    # Targeted variant (§10 segment analysis): weakest group headroom.
    targeted = None
    seg_dim = (segment or {}).get("field") or (dims[0] if dims else None)
    if seg_dim:
        try:
            targeted = _segment_extreme(engine, dialect, table, seg_dim, metric)
        except Exception:
            targeted = None

    # 5) Build + score candidates (§§11–14).
    cands_out = []
    for i, pct in enumerate(pcts):
        scen = scenario_for_pct(fit, pct)
        rlvl, rreasons = risk_level(fit, pct, abs(fit["r"]))
        score, comps = _score(fit, pct, control_level)
        # Labels from evidence order, not fixed sizes: smallest supported
        # change, strongest-evidence change, largest (highest-uncertainty).
        ordered_idx = sorted(range(len(pcts)), key=lambda k: abs(pcts[k]))
        label = ("conservative" if i == ordered_idx[0]
                 else "stretch" if i == ordered_idx[-1] else "recommended")
        # NOTE (hyp.txt §8): this title template is emitted ONLY here —
        # after the engine explicitly established controllability (§8 gate),
        # a semantic business outcome (§10 gate), a justified direction
        # (§12 gate), a measured baseline (scen["baseline"] from the fit),
        # and a modeled calculation (OLS slope via scenario_for_pct). A
        # bare correlation can never reach this line (gates above refuse
        # first with "No supported actionable scenario" / no_prescription).
        title = (f"Test a {abs(pct):g}% {verb} in {d_h}"
                 + (f" for {targeted['value']}" if targeted and label == "recommended" else ""))
        # Association is supporting evidence: the r/n observation stands,
        # the direction basis is the validated one from improvement_up —
        # never a generic "higher is better" assumption.
        why = (f"{m_h} is associated with {d_h} (r={fit['r']:+.2f}, n={fit['n']:,}); "
               f"moving {d_h} {'up' if move > 0 else 'down'} is modeled to move the metric "
               f"toward improvement ({up_assump}). "
               f"An association in past data is not proof the change would produce the result.")
        _conf = ("moderate" if (fit["r"] > 0) != (fit["spearman_r"] > 0)
                 or abs(fit["r"] - fit["spearman_r"]) > 0.4 else
                 "high" if fit["p_value"] < 0.01 and fit["n"] >= 100 else
                 "moderate" if fit["p_value"] < 0.05 else "low")
        if _dir_fallback and _conf == "high":
            _conf = "moderate"
        cands_out.append({
            "id": f"rx_{metric}_{driver_used}_{abs(pct)}",
            "rank": 0, "title": title, "summary": why,
            "action_type": "scenario", "scenario_label": label,
            # hyp §13 decision type: a validated scenario lever is an
            # evidence-backed area worth considering (opportunity), unless
            # the modeled risk is HIGH — then it is a risk worth
            # considering. The supported action text is the
            # Recommendation; what_to_consider is the Consideration.
            # control_level is stamped so downstream quality/priority gates
            # reuse the judged value instead of re-deriving it.
            "decision_type": "risk" if rlvl.lower() == "high" else "opportunity",
            "control_level": control_level,
            # Rank/linear conflict caps confidence: when Pearson and Spearman
            # disagree on direction or strength, the link is fragile.
            # An explicit fallback direction assumption also caps at moderate.
            "confidence": _conf,
            "risk": rlvl.lower(), "risk_reasons": rreasons,
            "score": score, "score_breakdown": comps,
            "evidence": {"metric": metric, "driver": driver_used, "table": table,
                         "driver_table": driver_table, "join": join_label,
                         "effect_r": fit["r"], "spearman_r": fit["spearman_r"],
                         "p_value": fit["p_value"], "n": fit["n"],
                         "slope": round(fit["slope"], 4),
                         "rank_consistent": bool((fit["r"] > 0) == (fit["spearman_r"] > 0)
                                                 and abs(fit["r"] - fit["spearman_r"]) <= 0.4),
                         "segment": targeted},
            "success_metric": {"metric": metric,
                               "direction": "increase" if up_better else "decrease",
                               "target_pct": round(scen["rel_pct"], 1),
                               "baseline": round(scen["baseline"], 2),
                               "note": "Modeled estimate from the recommended scenario."},
            "review_period": review,
            "review_basis": review_basis,
            "impact": {"baseline": round(scen["baseline"], 2),
                       "scenario": round(scen["scenario"], 2),
                       "delta": round(scen["delta"], 2),
                       "rel_pct": round(scen["rel_pct"], 2),
                       "range": [round(scen["range"][0], 2), round(scen["range"][1], 2)],
                       "driver_pct": pct,
                       "driver_value": round(scen["driver_value"], 3),
                       # Observed-range evidence (generic: from this fit's data).
                       # supported = inside observed driver range (green),
                       # limited = outside it (amber). Refusal stays ±50%.
                       "in_historical_range": scen["in_historical_range"],
                       "range_status": ("supported" if scen["in_historical_range"] else "limited"),
                       "observed": {"min": fit["x_min"], "max": fit["x_max"],
                                    "mean": round(fit["x_mean"], 4)},
                       "labels": {"baseline": "OBSERVED", "scenario": "SIMULATED"}},
            "assumptions": [up_assump,
                            "Linear response estimated from historical data (slope "
                            f"{fit['slope']:.4f});",
                            "All other factors held constant."],
            "limitations": _dynamic_limitations(fit, scen, targeted, d_h),
            "recommended_next_analysis": {
                "type": "hypothesis",
                "label": "Run a controlled hypothesis test comparing driver and metric response."},
        })
    cands_out.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(cands_out):
        c["rank"] = i + 1
    # Recommended = best tradeoff, not the biggest number (§12): prefer the
    # highest-scoring candidate without HIGH risk. Labels are relative to
    # the evidence pick — never fixed percentages.
    rec = next((c for c in cands_out if c["risk"] in ("low", "medium")), cands_out[0])
    _rec_pct = abs(rec["impact"]["driver_pct"])
    for c in cands_out:
        ap = abs(c["impact"]["driver_pct"])
        c["scenario_label"] = ("recommended" if c["id"] == rec["id"]
                               else "conservative" if ap < _rec_pct else "stretch")
    # hyp §§16-17 ONE finding → ONE decision: the scenario variants computed
    # above (+conservative/+recommended/+stretch) are NOT Decision Center
    # cards. They travel INSIDE the single decision as `scenario_options`
    # for the detail What-If experience (downstream of the validated
    # decision, §32) — never as separate "Test 20% ..." / "Test 45% ..." cards.
    rec["scenario_options"] = [
        {"scenario_label": c["scenario_label"],
         "driver_pct": c["impact"]["driver_pct"],
         "driver_value": c["impact"]["driver_value"],
         "baseline": c["impact"]["baseline"],
         "scenario": c["impact"]["scenario"],
         "delta": c["impact"]["delta"],
         "rel_pct": c["impact"]["rel_pct"],
         "range": c["impact"]["range"],
         "risk": c["risk"],
         "in_historical_range": c["impact"]["in_historical_range"]}
        for c in cands_out[:3]
    ]
    pres = [rec]
    # Investigate-type follow-ons are different findings (different driver /
    # basis), so they may accompany the decision — capped, ranked after it.
    inv = _investigate_cands(engine, dialect, intel, table, metric, m_h,
                             review=review, review_basis=review_basis)
    for c in inv[:4]:
        c["rank"] = len(pres) + 1
        pres.append(c)
    for i, c in enumerate(pres):
        c["rank"] = i + 1

    story = (f"{m_h} is associated with {d_h} (r={fit['r']:+.2f} over {fit['n']:,} observations"
             + (f", measured {_join_phrase(join_used)}" if join_used else "")
             + f"). A tested {verb} in {d_h} is the most evidence-backed driver available. "
               f"An association in past data is not proof the change would produce the result.")
    # Bounded evidence sample for the scatter chart (never the full dump).
    _sxs, _sys = best_xy or ([], [])
    _idx = sorted(set(int(i) for i in np.linspace(0, max(0, len(_sxs) - 1), min(len(_sxs), 200))))
    scatter = [{"x": round(float(_sxs[i]), 3), "y": round(float(_sys[i]), 3)} for i in _idx]
    out = {"ok": True, "success": True, "status": "completed",
           "analysis_id": f"rxa_{table}_{metric}_{driver_used}",
           "metric": metric, "driver": driver_used, "table": table,
           "driver_table": driver_table, "join": join_label,
           "join_ref": ({"table": join_used[0], "self_col": join_used[1],
                         "other_col": join_used[2]} if join_used else None),
           "control": {"level": control_level, "reason": control_reason},
           "auto_note": auto_note,
           "fit": {"r": fit["r"], "spearman_r": fit["spearman_r"],
                   "p_value": fit["p_value"], "n": fit["n"],
                   "slope": fit["slope"], "intercept": fit["intercept"]},
           "evidence_viz": {"type": "scatter", "x": driver_used, "y": metric,
                            "points": scatter,
                            "trend": {"slope": round(fit["slope"], 4),
                                      "intercept": round(fit["intercept"], 3)}},
            "prescriptions": pres,
           "signals": {"supporting": 1 + (1 if (priors.get("evidence")) else 0),
                       "priors_origin": priors.get("origin")},
           "story": story,
            "summary_plain": _plain_summary(m_h, d_h, fit, rec, _join_phrase(join_used))}
    return out


def run_scenario(engine, dialect, intel, table, metric, driver, changes, filt=None,
                 join=None):
    """Scenario engine (§27, hyp.txt §9): read-only recompute. changes=[{field, operation,
    value}], filt=(field, value) equals on a dimension. join=(other_table,
    self_col, other_col) across one declared edge for cross-table drivers.

    Never invents levers: a driver/metric that fails semantic-role +
    actionability validation returns SCENARIO_UNSUPPORTED with the honest
    "No supported actionable scenario" state instead of fabricating a
    numeric projection."""
    # hyp.txt §§4-6, §9: scenario variables must be legitimate business
    # levers with a real outcome — determined semantically, never assumed
    # from "numeric therefore movable".
    _spks = {p.lower() for p in intel.get_pk(table)}
    _sfks = {f[0].lower() for f in intel.get_fks(table)}
    _skeys = _join_key_cols(intel, table)
    if metric in intel.get_numeric_cols(table):
        _smrole = classify_semantic_role(
            metric, "numeric", is_pk=(metric.lower() in _spks),
            is_fk=(metric.lower() in _sfks),
            is_join_key=(metric.lower() in _skeys))
        if _smrole in NON_OUTCOME_ROLES:
            return _fail(CODE_SCENARIO_UNSUPPORTED,
                         f"{NO_SUPPORTED_SCENARIO}: '{metric}' is a "
                         f"{_smrole.lower().replace('_', ' ')}, not a business outcome ARIA can model.")
    derived_stay = (driver == "length_of_stay")
    if not derived_stay and driver in intel.get_numeric_cols(table):
        _sdrole = classify_semantic_role(
            driver, "numeric", is_pk=(str(driver).lower() in _spks),
            is_fk=(str(driver).lower() in _sfks),
            is_join_key=(str(driver).lower() in _skeys))
        if _sdrole in NON_LEVER_ROLES:
            return _fail(CODE_SCENARIO_UNSUPPORTED,
                         f"{NO_SUPPORTED_SCENARIO}: '{driver}' is a "
                         f"{_sdrole.lower().replace('_', ' ')}, not a controllable business driver.")
        _slevel, _swhy = classify_driver(driver, "numeric")
        if _slevel in ("not_controllable", "segmentation"):
            return _fail(CODE_SCENARIO_UNSUPPORTED,
                         f"{NO_SUPPORTED_SCENARIO}: '{driver}' cannot be moved as an intervention. {_swhy}")
    measures = _usable_measures(intel, table)
    if metric not in measures:
        return _fail(CODE_INVALID_METRIC, f"'{metric}' is not a measurable metric here.")
    if join is not None:
        ot, sc, oc = join
        if (ot, sc, oc) not in _edge_neighbors(intel, table):
            return _fail(CODE_SCENARIO_UNSUPPORTED, "Unknown join for this scenario.")
        if driver not in _usable_measures(intel, ot):
            return _fail(CODE_SCENARIO_UNSUPPORTED, f"Scenario modeling needs a numeric driver; '{driver}' isn't one.")
    elif not derived_stay and driver not in intel.get_numeric_cols(table):
        return _fail(CODE_SCENARIO_UNSUPPORTED, f"Scenario modeling needs a numeric driver; '{driver}' isn't one.")
    filt_t = None
    if filt:
        f, v = filt.get("field"), filt.get("value")
        if f not in intel.find_all_dimensions(table):
            return _fail(CODE_SCENARIO_UNSUPPORTED, f"Filter field '{f}' is not a usable segment here.")
        if join is not None:
            return _fail(CODE_SCENARIO_UNSUPPORTED,
                         "Segment filters with cross-table drivers aren't supported yet — run the overall scenario instead.")
        filt_t = (f, v)
    try:
        if join is not None:
            ot, sc, oc = join
            rows = _fetch_joined(engine, dialect, table, metric, ot, driver, sc, oc)
            xs = [float(r[0]) for r in rows]
            ys = [float(r[1]) for r in rows]
        elif derived_stay:
            dts = _date_like_cols(intel, table)[:3]
            if len(dts) < 2:
                return _fail(CODE_SCENARIO_UNSUPPORTED, "Stay-length modeling needs two date columns.")
            xs, ys = _stay_lengths(engine, dialect, table, dts[0], dts[1], metric)
            if xs is None:
                return _fail(CODE_INSUFFICIENT_DATA, "Not enough dated rows to model stay length.")
        else:
            rows = _fetch_pairs(engine, dialect, table, driver, metric, filt=filt_t)
            xs = [float(r[0]) for r in rows]
            ys = [float(r[1]) for r in rows]
    except (TypeError, ValueError):
        return _fail(CODE_MODEL_FAILED, "Scenario fields contain non-numeric values that can't be modeled.")
    fit = fit_relationship(xs, ys)
    if fit is None:
        return _fail(CODE_INSUFFICIENT_DATA,
                     f"Only {len(xs)} usable observations — at least {MIN_N} are needed to model a scenario.")
    results = []
    for ch in changes or []:
        field, op, val = ch.get("field"), ch.get("operation"), ch.get("value")
        if field != driver:
            return _fail(CODE_SCENARIO_UNSUPPORTED, "Scenarios can only change the modeled driver.")
        try:
            val = float(val)
        except (TypeError, ValueError):
            return _fail(CODE_SCENARIO_UNSUPPORTED, "Scenario value must be numeric.")
        if op == "percent":
            pct = val
        elif op == "set":
            pct = ((val - fit["x_mean"]) / abs(fit["x_mean"]) * 100) if fit["x_mean"] else 0.0
        else:
            return _fail(CODE_SCENARIO_UNSUPPORTED, "Operation must be 'percent' or 'set'.")
        if abs(pct) > 50:
            return _fail(CODE_SCENARIO_UNSUPPORTED,
                         "Interventions beyond ±50% leave the evidence behind — narrow the scenario.")
        scen = scenario_for_pct(fit, pct)
        rlvl, rreasons = risk_level(fit, pct, abs(fit["r"]))
        results.append({"change": ch, "baseline": round(scen["baseline"], 2),
                        "scenario": round(scen["scenario"], 2),
                        "delta": round(scen["delta"], 2),
                        "rel_pct": round(scen["rel_pct"], 2),
                        "range": [round(scen["range"][0], 2), round(scen["range"][1], 2)],
                        "driver_value": round(scen["driver_value"], 3),
                        "in_historical_range": scen["in_historical_range"],
                        "range_status": ("supported" if scen["in_historical_range"] else "limited"),
                        "observed": {"min": fit["x_min"], "max": fit["x_max"],
                                     "mean": round(fit["x_mean"], 4)},
                        "risk": rlvl.lower(), "labels": {"baseline": "OBSERVED", "scenario": "SIMULATED"}})
    return {"ok": True, "success": True, "metric": metric, "driver": driver,
            "table": table, "segment": filt_t, "n": fit["n"],
            "scenarios": results,
            "assumptions": ["Linear response from historical slope; all else held constant."],
            "warning": ("Simulated estimates are not guaranteed outcomes."
                        if results else None)}


# --------------------------------------------------------------------------
# Document mode (§6): text-only PDFs — qualitative, source-cited, no numbers
# --------------------------------------------------------------------------
_DOC_STOPWORDS = frozenset(
    "the a an and or of to in on for with is are was were be been by as at "
    "from that this these those it its into over under between will would can "
    "could should have has had not no yes if then than so such only also very "
    "more most other some any each per via vs etc what which who when where how "
    "about against during after before".split()
)

_PROBLEM_WORDS = ("declin", "drop", "fall", "risk", "delay", "issue", "concern",
                  "loss", "fail", "bottleneck", "backlog", "shortage", "complaint",
                  "breach", "incident", "downtime", "overrun")
_OPPORTUNITY_WORDS = ("growth", "opportunit", "improv", "gain", "expansion",
                      "launch", "record", "strong", "success", "saving")


def _doc_terms(text):
    import re as _re
    return [t for t in _re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(t) > 2 and t not in _DOC_STOPWORDS]


def _doc_title(chunk):
    section = (chunk.get("section") or "").strip()
    if section:
        return section[:90]
    text = " ".join(str(chunk.get("content") or "").split())
    head = text.split(". ")[0].strip()
    return (head[:87] + "…") if len(head) > 90 else (head or "Untitled finding")


def analyze_document(chunks, question, doc_name):
    """Qualitative prescriptions from document passages (§6).

    Retrieval-free inside: chunks are pre-scored by the caller or scored
    here by deterministic term overlap. Every claim is a verbatim-bounded
    quote with a page citation. No numeric modeling is ever claimed.
    """
    qterms = set(_doc_terms(question))
    if not qterms:
        return {"ok": True, "success": True, "status": "no_prescription",
                "reason": ("Tell ARIA what decision the document should inform "
                           "— e.g. what risks need action?"),
                "alternatives": ["Ask ARIA", "Explore Data"],
                "document": doc_name}
    scored = []
    for ch in chunks or []:
        terms = set(_doc_terms(ch.get("content")))
        overlap = qterms & terms
        if overlap:
            scored.append((len(overlap), ch))
    scored.sort(key=lambda t: t[0], reverse=True)
    top = [ch for _, ch in scored[:5]]
    if not top:
        return {"ok": True, "success": True, "status": "no_prescription",
                "reason": (f"No passage in {doc_name} speaks to this question. "
                           f"Try different wording or ask ARIA to summarize the document first."),
                "alternatives": ["Ask ARIA", "Explore Data"],
                "document": doc_name}
    recs = []
    for ch in top[:3]:
        text = " ".join(str(ch.get("content") or "").split())
        low = text.lower()
        is_problem = any(w in low for w in _PROBLEM_WORDS)
        is_opp = any(w in low for w in _OPPORTUNITY_WORDS)
        page = ch.get("page_number")
        quote = text[:277] + "…" if len(text) > 280 else text
        if is_problem and not is_opp:
            title = f"Look into: {_doc_title(ch)}"
            action = "investigate"
        elif is_opp and not is_problem:
            title = f"Prepare for: {_doc_title(ch)}"
            action = "prepare"
        else:
            title = f"Consider: {_doc_title(ch)}"
            action = "review"
        recs.append({
            "id": f"rxdoc_{ch.get('id', len(recs))}",
            "rank": len(recs) + 1,
            "title": title,
            "summary": f"Passage from {doc_name}" + (f" (page {page})" if page else "") + " reads: “" + quote + "”",
            "action_type": "qualitative", "scenario_label": "qualitative",
            # hyp §13: a cited passage is a Finding (an observed pattern),
            # never an Opportunity — there is no measured lever behind it.
            "decision_type": "finding",
            "confidence": "low", "risk": "medium",
            "risk_reasons": ["Text evidence only — strength cannot be quantified."],
            "score": round(10 + len(set(_doc_terms(text)) & qterms), 1),
            "score_breakdown": {"passage_relevance": len(set(_doc_terms(text)) & qterms)},
            "evidence": {"document": doc_name, "page": page,
                         "n": len(top), "segment": None},
            "citations": [{"page": page, "quote": quote,
                           "chunk_id": ch.get("id")}],
            "impact": {"baseline": None, "scenario": None, "delta": None,
                       "rel_pct": None, "range": [None, None],
                       "driver_pct": None, "driver_value": None,
                       "labels": {"baseline": "OBSERVED", "scenario": "NOT MODELED"}},
            "success_metric": {"metric": "decision readiness",
                               "direction": "confirm or rule out with numbers",
                               "target_pct": None, "baseline": None,
                               "note": "Qualitative — confirm with data before acting."},
            "review_period": "after stakeholder review",
            "review_basis": "text evidence has no time series to pace reviews",
            "assumptions": ["Passages interpreted at face value."],
            "limitations": ["Text evidence only — no numbers were modeled.",
                            f"Based on {len(top)} cited passage(s) from {doc_name}; the rest of the document may add context.",
                            "Association in prose is not proof of cause or size."],
            "recommended_next_analysis": {"type": "copilot",
                                          "label": "Ask ARIA to dig into this passage further."},
        })
    story = (f"{doc_name} speaks to your question in {len(top)} passage(s). "
              f"These are qualitative leads with citations — confirm them with numbers before acting.")
    return {"ok": True, "success": True, "status": "completed",
            "analysis_id": f"rxd_{abs(hash(doc_name)) % 10**8}",
            "document": doc_name, "metric": None, "driver": None, "table": None,
            "prescriptions": recs,
            "signals": {"supporting": 1, "priors_origin": "document"},
            "story": story,
            "summary_plain": (
                f"We read {doc_name} for passages about your question and found "
                f"{len(top)} relevant one(s). The top lead is: {recs[0]['title']}. "
                f"Each card quotes its source passage — these are leads to verify, not measured effects.")}


# ---------------------------------------------------------------------------
# PHASE 10-11 Decision Center integration helpers (additive, no behavior change
# to analyze/run_scenario). Existing engine stays the single recommendation +
# scenario backend: these wrappers only validate + shape Decision payloads.
# ---------------------------------------------------------------------------
def recommendation_for_decision(decision: dict):
    """Supported recommendation text for a validated Decision, else None.

    Never returns the finding title. Never an LLM-only action: the text must
    already come from the engine-produced prescription; this wrapper only
    validates business_relevance + actionability + outcome + direction +
    evidence (via quality_gate + semantic roles) and returns None when
    unsupported.
    """
    d = decision if isinstance(decision, dict) else {}
    raw = d.get("recommendation")
    raw = raw.strip() if isinstance(raw, str) else None
    title = d.get("title") if isinstance(d.get("title"), str) else ""
    if raw and title and raw.strip().lower() == title.strip().lower():
        return None
    if not raw:
        return None
    ev = d.get("evidence")
    items = ev if isinstance(ev, list) else ([ev] if ev else [])
    stem = items[0] if items and isinstance(items[0], dict) else {}
    probe = gate_input_from_prescription(
        {"metric": d.get("metric"), "driver": d.get("driver"),
         "evidence": stem, "impact": d.get("impact") or {},
         "confidence": d.get("confidence"),
         "control_level": d.get("control_level"),
         "action_type": d.get("action_type")},
        require_baseline=(str(d.get("action_type") or "").lower() == "scenario"))
    gate = quality_gate(probe, require_baseline=(str(d.get("action_type") or "").lower() == "scenario"))
    if not gate.get("pass"):
        return None
    metric = d.get("metric") or ""
    driver = d.get("driver") or d.get("dimension") or ""
    try:
        if classify_semantic_role(metric, "numeric") in NON_OUTCOME_ROLES:
            return None
        if driver and classify_semantic_role(driver, "numeric") in NON_LEVER_ROLES:
            return None
    except Exception:
        return None
    if driver:
        try:
            level, _why = classify_driver(driver, "numeric")
        except Exception:
            return None
        if level in ("not_controllable", "segmentation"):
            return None
    try:
        up_better, _why = improvement_up(metric) if metric else (None, "no metric")
    except Exception:
        return None
    if str(d.get("action_type") or "").lower() == "scenario" and up_better is None:
        return None
    return raw


def scenario_supported_range(impact: dict | None):
    """Backend-derived supported range for What-If (never hardcoded ±%).

    Returns the observed {min, max, mean} frozen in the impact payload, or
    None when the backend never measured one.
    """
    imp = impact if isinstance(impact, dict) else {}
    obs = imp.get("observed")
    if not isinstance(obs, dict):
        return None
    try:
        lo = float(obs.get("min")) if obs.get("min") is not None else None
        hi = float(obs.get("max")) if obs.get("max") is not None else None
        mean = float(obs.get("mean")) if obs.get("mean") is not None else None
    except (TypeError, ValueError):
        return None
    if lo is None or hi is None:
        return None
    return {"min": lo, "max": hi, "mean": mean}
