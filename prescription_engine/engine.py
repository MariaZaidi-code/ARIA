"""Prescription Engine: evidence -> problem -> driver -> controllability ->
candidates -> scenarios -> rank. Self-contained statistics (numpy/scipy);
reuses only SchemaIntelligence for schema discovery. All data access is
bounded and read-only. The LLM never computes numbers — it may only polish
wording built deterministically from the evidence.
"""

import logging
import math

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


def classify_driver(name, col_category):
    """Return (level, reason) with level in controllable / potentially /
    segmentation / not_controllable."""
    low = (name or "").lower()
    tail = low.split("_")[-1] if low else ""
    if col_category == "datetime" or any(h in low for h in _TIME_HINTS):
        return "not_controllable", "Time cannot be changed — ARIA can only prepare for it."
    if tail in ("id", "key", "code", "no") or low in ("id", "key", "code"):
        return "not_controllable", "Identifiers cannot be intervened on."
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
    """Assume higher metric is better unless the name says otherwise."""
    low = (metric or "").lower()
    if any(h in low for h in _LOWER_BETTER_HINTS):
        return False, "assumes lower values of this metric are preferable"
    return True, "assumes higher values of this metric are preferable"


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
    return _exec(engine,
                 f"SELECT {_safe_name(col_a, dialect)}, {_safe_name(col_b, dialect)} "
                 f"FROM {_safe_name(table, dialect)} WHERE {where} "
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
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    r = float(np.corrcoef(rx, ry)[0, 1]) if len(x) > 2 else 0.0
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
# Orchestrator (§4 pipeline)
# --------------------------------------------------------------------------
def _usable_measures(intel, table):
    fks = {f[0].lower() for f in intel.get_fks(table)}
    pks = {p.lower() for p in intel.get_pk(table)}
    out = []
    for c in intel.get_numeric_cols(table):
        low = c.lower()
        if low in fks or low in pks:
            continue
        if low.endswith(("_id", "_key", "_no", "_code")) or low in ("id", "key", "code"):
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
                        f"Something about these groups drives the difference — find it before acting."),
            "action_type": "investigate", "scenario_label": "investigate",
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
    story = (f"No adjustable lever for {m_h} cleared the evidence bar, but "
             f"{m_h} differs meaningfully across {top['evidence']['driver']} "
             f"({top['evidence']['effect_gap_pct']:+.1f}% gap). "
             f"Investigation is warranted before any intervention.")
    return {"ok": True, "success": True, "status": "completed",
            "analysis_id": f"rxa_{table}_{metric}_investigate",
            "metric": metric, "driver": top["evidence"]["driver"],
            "table": table, "driver_table": table, "join": None, "join_ref": None,
            "control": {"level": "investigation",
                        "reason": "No intervention modeled — evidence directs investigation."},
            "auto_note": None, "fit": None, "evidence_viz": None,
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


def _plain_summary(m_h, d_h, fit, rec, join_label=None):
    """Plain-English summary of the whole analysis — a normal person reads
    only this and understands what was tested, found, and recommended."""
    if rec.get("action_type") == "investigate":
        ev = rec.get("evidence", {})
        gs = ev.get("groups", [])
        top_mean = gs[0]["mean"] if gs else "?"
        bot_mean = gs[-1]["mean"] if gs else "?"
        return (
            f"We looked for an adjustable lever for {m_h.lower()} across "
            f"{ev.get('n', 0):,} rows but found no strong one. What we did find: "
            f"{ev.get('top')} averages {top_mean} vs "
            f"{ev.get('bottom')} at {bot_mean} "
            f"— a {ev.get('effect_gap_pct'):+.1f}% gap across {ev.get('driver')}. "
            f"Our recommendation: {rec['title']}. Start by finding what drives the "
            f"difference — a gap shows where to look, not what to change."
        )
    direction = "go up together" if fit["slope"] > 0 else "move in opposite directions"
    strength = ("strong" if abs(fit["r"]) >= 0.7 else "moderate" if abs(fit["r"]) >= 0.5 else "noticeable")
    r_imp = rec["impact"]
    m, d = m_h.lower(), d_h.lower()
    return (
        f"We tested whether changing {d} moves {m}, using {fit['n']:,} rows of your data. "
        f"It does: the two {direction} ({strength} link, r={fit['r']:+.2f})"
        + (f", measured across the {join_label} link" if join_label else "")
        + ". "
        f"Our recommendation: {rec['title']}: "
        f"{m} would go from about {r_imp['baseline']:,.1f} to about {r_imp['scenario']:,.1f} "
        f"({r_imp['rel_pct']:+.1f}%), within a range of {r_imp['range'][0]:,.1f} to {r_imp['range'][1]:,.1f}. "
        f"Confidence is {rec['confidence']}, risk is {rec['risk']} — and this is an association in past data, not proof it will work."
    )


def analyze(engine, dialect, intel, table, metric, driver=None,
            dimensions=None, segment=None, question=None, priors=None):
    """Full prescription pipeline. Returns ranked prescriptions or a
    no_prescription refusal (§23) — never an invented action."""
    from core.semantic import humanize
    priors = priors or {}

    # 1) Validate metric (§34/§35: schema-discovered, never assumed).
    measures = _usable_measures(intel, table)
    if metric not in measures:
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
                     f"'{metric}' can't be both the target and the lever. Pick a different driver.")
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
                         f"{metric}.")
        f = fit_relationship(nights, ys)
        if not (f and abs(f["r"]) >= MIN_ABS_R and f["p_value"] < 0.05):
            return {"ok": True, "success": True, "status": "no_prescription",
                    "reason": (f"ARIA measured stay length against {metric} but the link "
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
            reason = (f"'{metric}' is the only measurable column reachable from {table} — "
                      f"there are no other numbers in your data to test as drivers.")
        else:
            reason = (f"ARIA tested {', '.join(numeric_tested[:6])} against {metric} "
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
        auto_note = (f"ARIA selected {driver_used} automatically as the strongest evidence-backed driver"
                     + (f" (across the {join_label} link)." if join_label else "."))
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
                "reason": (f"ARIA found a {control_level} pattern involving {driver_used}, "
                           f"but the available data does not contain a controllable factor that can be "
                           f"reliably evaluated as an intervention. {control_reason}"),
                "alternatives": ["Investigate Driver", "Test Hypothesis", "Explore Data", "Ask ARIA"],
                "metric": metric, "driver": driver_used, "table": table,
                "evidence": {"r": fit["r"], "p_value": fit["p_value"], "n": fit["n"]}}

    # 4) Improvement direction + candidates (§9).
    up_better, up_assump = improvement_up(metric)
    # Move the driver so the metric improves: sign = +1 means increase driver.
    move = 1 if ((fit["slope"] > 0) == up_better) else -1
    verb = "increase" if move > 0 else "reduction"
    pcts = [5 * move, 10 * move, 15 * move]
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
        label = ("conservative" if abs(pct) == 5 else
                 "recommended" if abs(pct) == 10 else "aggressive")
        title = (f"Test a {abs(pct)}% {verb} in {d_h}"
                 + (f" for {targeted['value']}" if targeted and abs(pct) == 10 else ""))
        why = (f"{m_h} is associated with {d_h} (r={fit['r']:+.2f}, n={fit['n']:,}); "
               f"moving {d_h} {'up' if move > 0 else 'down'} points the metric toward improvement "
               f"({up_assump}).")
        cands_out.append({
            "id": f"rx_{metric}_{driver_used}_{abs(pct)}",
            "rank": 0, "title": title, "summary": why,
            "action_type": "scenario", "scenario_label": label,
            "confidence": ("high" if fit["p_value"] < 0.01 and fit["n"] >= 100 else
                           "moderate" if fit["p_value"] < 0.05 else "low"),
            "risk": rlvl.lower(), "risk_reasons": rreasons,
            "score": score, "score_breakdown": comps,
            "evidence": {"metric": metric, "driver": driver_used, "table": table,
                         "driver_table": driver_table, "join": join_label,
                         "effect_r": fit["r"], "spearman_r": fit["spearman_r"],
                         "p_value": fit["p_value"], "n": fit["n"],
                         "slope": round(fit["slope"], 4),
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
    # highest-scoring candidate without HIGH risk.
    rec = next((c for c in cands_out if c["risk"] in ("low", "medium")), cands_out[0])
    for c in cands_out:
        ap = abs(c["impact"]["driver_pct"])
        c["scenario_label"] = ("recommended" if c["id"] == rec["id"]
                               else "conservative" if ap <= 5 else "aggressive")
    # Investigate-type follow-ons round out the shortlist (max 5 total).
    if len(cands_out) < 5:
        inv = _investigate_cands(engine, dialect, intel, table, metric, m_h,
                                 review=review, review_basis=review_basis)
        for c in inv[:5 - len(cands_out)]:
            c["rank"] = len(cands_out) + 1
            cands_out.append(c)

    story = (f"{m_h} moves with {d_h} (r={fit['r']:+.2f} over {fit['n']:,} observations"
             + (f", across the {join_label} link" if join_label else "")
             + f"). A tested {verb} in {d_h} is the most evidence-backed lever available.")
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
           "prescriptions": cands_out[:5],
           "signals": {"supporting": 1 + (1 if (priors.get("evidence")) else 0),
                       "priors_origin": priors.get("origin")},
           "story": story,
           "summary_plain": _plain_summary(m_h, d_h, fit, rec, join_label)}
    return out


def run_scenario(engine, dialect, intel, table, metric, driver, changes, filt=None,
                 join=None):
    """Scenario engine (§27): read-only recompute. changes=[{field, operation,
    value}], filt=(field, value) equals on a dimension. join=(other_table,
    self_col, other_col) across one declared edge for cross-table drivers."""
    measures = _usable_measures(intel, table)
    if metric not in measures:
        return _fail(CODE_INVALID_METRIC, f"'{metric}' is not a measurable metric here.")
    derived_stay = (driver == "length_of_stay")
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
