"""Predictive analysis and prescription routes.

Provides standalone endpoints for forecasting and generating
actionable recommendations from the connected database.
"""

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.config import get_session
from core.deps import require_data, require_writable, get_current_user, reject_document_sql
from core.secret_box import decrypt as _decrypt_secret

log = logging.getLogger("aria.predictive_routes")
router = APIRouter()


class ForecastRequest(BaseModel):
    question: str = ""
    column: str | None = None
    time_dim: str | None = None
    # None = auto-suggest from frequency + history length (dynamic default);
    # any integer overrides the suggestion.
    horizon: int | None = None


class PrescriptionRequest(BaseModel):
    insight_id: str = ""


class ScenarioRequest(BaseModel):
    column: str | None = None
    pct_change: float = 10.0
    periods: int = 3


_DATE_NAME_HINTS = ("date", "time", "day", "month", "year", "created",
                    "updated", "timestamp", "period", "week", "quarter")


def _table_columns(tables, tname):
    tinfo = tables.get(tname, {})
    cols = tinfo.get("columns", []) if isinstance(tinfo, dict) else []
    if isinstance(cols, dict):
        return [(k, str((v or {}).get("data_type", ""))) for k, v in cols.items()]
    out = []
    for c in cols:
        if isinstance(c, dict):
            out.append((c.get("column") or c.get("name") or "", str(c.get("data_type", "") or "")))
        else:
            out.append((str(c), ""))
    return [(n, d) for n, d in out if n]


def _validate_time_dim(engine, dialect, table, column, dtype):
    """Check a candidate time column against REAL data.

    Returns dict with kind/distinct/null_pct/parse_ratio/span or None when
    the column cannot serve as a forecast axis. Never invents dates.
    """
    from sqlalchemy import text as _t
    from api.schema_intel import _safe_name
    try:
        with engine.connect() as conn:
            row = conn.execute(_t(
                f"SELECT COUNT(*) n, COUNT({_safe_name(column, dialect)}) nn, "
                f"COUNT(DISTINCT {_safe_name(column, dialect)}) nd "
                f"FROM {_safe_name(table, dialect)}"
            )).fetchone()
            n, nn, nd = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
            if n == 0 or nd < 2:
                return None
            vals = [r[0] for r in conn.execute(_t(
                f"SELECT DISTINCT {_safe_name(column, dialect)} "
                f"FROM {_safe_name(table, dialect)} "
                f"WHERE {_safe_name(column, dialect)} IS NOT NULL LIMIT 200"
            )).fetchall()]
    except Exception as exc:
        log.warning("Eligibility sampling failed for %s.%s: %s", table, column, exc)
        return None
    low_dtype = (dtype or "").lower()
    real_date = any(k in low_dtype for k in ("date", "time", "timestamp"))
    try:
        import pandas as _pd
        parsed = _pd.to_datetime([str(v) for v in vals], errors="coerce")
        ratio = float(parsed.notna().sum()) / max(1, len(vals))
    except Exception:
        ratio = 1.0 if real_date else 0.0
    if not real_date and ratio < 0.8:
        return None
    span = None
    try:
        import pandas as _pd2
        ts = _pd2.to_datetime([str(v) for v in vals], errors="coerce").dropna()
        if len(ts):
            span = [str(ts.min()), str(ts.max())]
    except Exception:
        span = None
    return {
        "column": column,
        "kind": "date" if real_date else "text",
        "distinct": nd,
        "null_pct": round((1 - nn / n) * 100, 1) if n else 100.0,
        "parse_ratio": round(ratio, 2),
        "span": span,
    }


def _evidence_state_for_forecast(forecast, table_rows, table):
    """Additive canonical state for forecast payloads (never overrides)."""
    try:
        from core.evidence import assess_evidence as _assess
        n_obs = (forecast or {}).get("n_obs")
        rows = table_rows if table_rows is not None else n_obs
        return _assess(rows if rows is not None else 0, "forecast",
                       history_points=n_obs, dataset_name=table)
    except Exception:
        return None


def _scenario_evidence_state(row_count, table, history_points=None):
    """Additive canonical state for scenario payloads."""
    try:
        from core.evidence import assess_evidence as _assess
        return _assess(row_count, "scenario", history_points=history_points,
                       dataset_name=table)
    except Exception:
        return None


@router.get("/api/predictive/eligibility")
def forecast_eligibility(request: Request, user: dict = Depends(get_current_user)):
    """Inspect the connected source and report what can actually be forecast.

    Dynamic across PostgreSQL/MySQL/CSV: discovers temporal columns from real
    data (dtype + value parsing, never invented), lists measurable metrics
    per table (numeric, non-key, non-FK via SchemaIntelligence), counts
    observations, and recommends a valid default target + time dimension.
    """
    from api.kpi_routes import _build_engine as _kb
    from api.schema_intel import SchemaIntelligence as _SI

    session = get_session(user["user_id"])
    reject_document_sql(session)
    schema_path = session.get("schema_path")
    if not schema_path or not Path(str(schema_path)).exists():
        return {"ok": True, "eligible": False, "connected": False,
                "tables": [], "recommended": None,
                "reasons": ["No data source is connected yet. Connect PostgreSQL, MySQL, CSV or PDF first."]}
    try:
        mapping = json.loads(Path(str(schema_path)).read_text(encoding="utf-8"))
    except Exception:
        return {"ok": True, "eligible": False, "connected": True,
                "tables": [], "recommended": None,
                "reasons": ["The schema description could not be read. Reconnect or rescan the schema, then try again."]}
    tables = mapping.get("tables", {})
    if not tables:
        return {"ok": True, "eligible": False, "connected": True,
                "tables": [], "recommended": None,
                "reasons": ["The connected source has no tables to analyze."]}
    intel = _SI(mapping)
    engine, dialect, _dbt = _kb(session)
    if engine is None:
        return {"ok": True, "eligible": False, "connected": True,
                "tables": [], "recommended": None,
                "reasons": ["This source type cannot be queried for forecasting yet."]}
    from sqlalchemy import text as _t
    from api.schema_intel import _safe_name
    out_tables = []
    reasons: list[str] = []
    for tname in list(tables)[:15]:
        cols = _table_columns(tables, tname)
        measures = [m for m in (intel.find_all_measures(tname) or [])]
        # Time candidates: real date dtypes first, then date-hinted text cols.
        date_cols = [n for n, d in cols
                     if any(k in d.lower() for k in ("date", "time", "timestamp"))]
        text_hints = [n for n, d in cols
                      if n not in date_cols and any(h in n.lower() for h in _DATE_NAME_HINTS)]
        time_dims = []
        for cand in (date_cols + text_hints)[:5]:
            dtype = next((d for n, d in cols if n == cand), "")
            checked = _validate_time_dim(engine, dialect, tname, cand, dtype)
            if checked:
                if checked["null_pct"] > 50:
                    reasons.append(
                        f"{tname}.{cand} looks like a date but is empty too often "
                        f"({checked['null_pct']}% missing), so it was skipped.")
                    continue
                time_dims.append(checked)
        try:
            with engine.connect() as conn:
                n_rows = int(conn.execute(_t(
                    f"SELECT COUNT(*) FROM {_safe_name(tname, dialect)}")).fetchone()[0] or 0)
        except Exception:
            n_rows = 0
        out_tables.append({
            "table": tname,
            "measures": measures,
            "time_dims": time_dims,
            "row_count": n_rows,
        })
    if not any(t["measures"] for t in out_tables):
        reasons.append("No measurable numeric metric was found (only ids, keys, codes or text). "
                       "Forecasting needs a number that changes over time, such as an amount, quantity or count.")
    if not any(t["time_dims"] for t in out_tables):
        reasons.append("No usable time dimension was found. ARIA looked for date/datetime columns "
                       "and date-like text (month, year, created …) with real parseable values, "
                       "but nothing had enough valid distinct dates.")
    recommended = None
    for t in out_tables:
        if t["measures"] and t["time_dims"]:
            best_td = max(t["time_dims"], key=lambda d: (d["kind"] == "date", d["distinct"]))
            if best_td["distinct"] >= 5:
                recommended = {
                    "table": t["table"],
                    "measure": t["measures"][0],
                    "time_dim": best_td["column"],
                    "history_points": best_td["distinct"],
                }
                break
    if recommended is None:
        for t in out_tables:
            if t["measures"] and t["time_dims"]:
                td = t["time_dims"][0]
                recommended = {
                    "table": t["table"],
                    "measure": t["measures"][0],
                    "time_dim": td["column"],
                    "history_points": td["distinct"],
                }
                reasons.append(
                    f"Only {td['distinct']} distinct time values were found — a reliable forecast "
                    f"needs at least 5. Results will be marked accordingly.")
                break
    try:
        engine.dispose()
    except Exception:
        pass
    # Per-target prediction validation (core/data_intelligence.py): cheap,
    # pure and generic — attached for transparency alongside the live
    # measure/time-dim discovery above. Never overrides it.
    try:
        from core.data_intelligence import (
            build_data_intelligence as _bdi,
            detect_capabilities as _dcaps,
        )
        _caps = _dcaps(_bdi(mapping))
        prediction_targets = _caps.get("prediction_targets", [])
    except Exception:
        prediction_targets = []
    # Additive canonical state: global rows<10 dominates (REUSED
    # GLOBAL_MIN_ROWS=10); per-table forecast minimum (min_points=5 history
    # periods) stays in the per-table time_dims/distinct checks above.
    try:
        from core.evidence import assess_evidence as _assess_el
        _max_rows = max([int(t.get("row_count") or 0) for t in out_tables] or [0])
        _ev_el = _assess_el(_max_rows, "forecast",
                           history_points=(recommended or {}).get("history_points"),
                           dataset_name=(recommended or {}).get("table"))
    except Exception:
        _ev_el = None
    _elig = {
        "ok": True,
        "eligible": recommended is not None,
        "connected": True,
        "tables": out_tables,
        "recommended": recommended,
        "reasons": reasons,
        "min_points": 5,
        "prediction_targets": prediction_targets,
    }
    if _ev_el is not None:
        _elig["evidence_state"] = _ev_el
        if _ev_el.get("status") != "supported":
            _elig["eligible"] = False
            if _ev_el.get("reason") and _ev_el["reason"] not in _elig["reasons"]:
                _elig["reasons"] = [_ev_el["reason"]] + list(_elig["reasons"])
    return _elig


@router.post("/api/predictive/scenario")
def run_scenario(req: ScenarioRequest, request: Request, user: dict = Depends(require_writable)):
    """Deterministic what-if analysis on real aggregates (spec §16).

    Applies a user-supplied percentage change to the trailing average of a
    measure. Pure arithmetic — labelled an estimate, never a forecast.
    """
    session = get_session(user["user_id"])
    reject_document_sql(session)
    schema_path = session.get("schema_path")
    if not schema_path or not Path(str(schema_path)).exists():
        raise HTTPException(status_code=400, detail="No database connected.")
    mapping = json.loads(Path(str(schema_path)).read_text(encoding="utf-8"))
    tables = mapping.get("tables", {})
    if not tables:
        raise HTTPException(status_code=400, detail="No tables found in schema.")

    from api.kpi_routes import _build_engine
    from api.schema_intel import SchemaIntelligence, _safe_name
    from sqlalchemy import text as _text

    intel = SchemaIntelligence(mapping)
    target_table, target_col = None, None

    def _holds_numbers(eng, dialect, tname, col, sample=20):
        """Runtime check: does this column actually hold numbers?"""
        try:
            with eng.connect() as _c:
                _rows = _c.execute(_text(
                    f"SELECT {_safe_name(col, dialect)} "
                    f"FROM {_safe_name(tname, dialect)} LIMIT {int(sample)}")).fetchall()
            _vals = [r[0] for r in _rows]
            if not _vals:
                return False
            _good = 0
            for _v in _vals:
                if isinstance(_v, bool):
                    continue
                try:
                    float(str(_v).replace(",", ""))
                    _good += 1
                except (TypeError, ValueError):
                    continue
            return _good >= max(1, len(_vals) // 2)
        except Exception:
            try:
                _c.rollback()
            except Exception:
                pass
            return False

    _eng_probe, _dial_probe, _ = _build_engine(session)

    def _verified_measure(tname):
        try:
            m = intel.find_best_measure(tname)
            if m and m in (intel.get_numeric_cols(tname) or []):
                if _eng_probe is not None and not _holds_numbers(_eng_probe, _dial_probe, tname, m):
                    return None
                return m
        except Exception:
            pass
        return None

    if req.column:
        want = req.column.split(" (")[0].strip().lower()
        for tname, tinfo in tables.items():
            cols = tinfo.get("columns", []) if isinstance(tinfo, dict) else []
            names = [(c.get("column") if isinstance(c, dict) else c) for c in cols]
            for n in names:
                if not (n and str(n).lower() == want):
                    continue
                try:
                    numeric = n in (intel.get_numeric_cols(tname) or [])
                except Exception:
                    numeric = False
                if not numeric:
                    continue
                if _eng_probe is not None and not _holds_numbers(_eng_probe, _dial_probe, tname, n):
                    continue
                target_table, target_col = tname, n
                break
            if target_table:
                break
            if target_table:
                break
    if not target_col:
        for tname in tables:
            m = _verified_measure(tname)
            if m:
                target_table, target_col = tname, m
                break
    if not target_col:
        raise HTTPException(status_code=400, detail="No numeric measure available for scenario analysis.")

    pct = max(-95.0, min(95.0, float(req.pct_change or 0.0)))
    n_periods = max(1, min(12, int(req.periods or 3)))

    engine, dialect, _dbt = _build_engine(session)
    if engine is None:
        raise HTTPException(status_code=400, detail="No queryable database for this source.")
    dt_col = intel.find_best_datetime(target_table)
    # TEXT time columns (e.g. CSV months stored as '2024-01') are not real
    # dates: date-format functions return NULL/raise on them. Group by the
    # raw value instead — fully generic, works on every dialect.
    dt_is_real_date = False
    if dt_col:
        try:
            _tinfo = tables.get(target_table, {})
            _cols = _tinfo.get("columns", []) if isinstance(_tinfo, dict) else []
            if isinstance(_cols, dict):
                _dtype = str((_cols.get(dt_col) or {}).get("data_type", "") or "").lower()
            else:
                _dtype = ""
                for _c in _cols:
                    _n = (_c.get("column") if isinstance(_c, dict) else _c)
                    if _n and str(_n) == dt_col:
                        _dtype = str((_c.get("data_type", "") if isinstance(_c, dict) else "") or "").lower()
                        break
            dt_is_real_date = any(k in _dtype for k in ("date", "time", "timestamp"))
        except Exception:
            dt_is_real_date = False
    try:
        with engine.connect() as conn:
            if dt_col and dt_is_real_date:
                if dialect == "sqlite":
                    gexpr = f"strftime('%Y-%m', {_safe_name(dt_col, dialect)})"
                elif dialect == "mysql":
                    gexpr = f"DATE_FORMAT({_safe_name(dt_col, dialect)}, '%Y-%m')"
                else:
                    gexpr = f"TO_CHAR({_safe_name(dt_col, dialect)}, 'YYYY-MM')"
                rows = conn.execute(_text(
                    f"SELECT {gexpr} AS p, SUM({_safe_name(target_col, dialect)}) AS v "
                    f"FROM {_safe_name(target_table, dialect)} "
                    f"WHERE {_safe_name(dt_col, dialect)} IS NOT NULL "
                    f"GROUP BY p ORDER BY p DESC LIMIT {n_periods}"
                )).fetchall()
                series = [{"period": str(r[0]), "actual": float(r[1])}
                          for r in rows if r[0] is not None and r[1] is not None]
                series.reverse()
            elif dt_col:
                rows = conn.execute(_text(
                    f"SELECT {_safe_name(dt_col, dialect)} AS p, SUM({_safe_name(target_col, dialect)}) AS v "
                    f"FROM {_safe_name(target_table, dialect)} "
                    f"WHERE {_safe_name(dt_col, dialect)} IS NOT NULL "
                    f"GROUP BY {_safe_name(dt_col, dialect)} "
                    f"ORDER BY {_safe_name(dt_col, dialect)} DESC LIMIT {n_periods}"
                )).fetchall()
                series = [{"period": str(r[0]), "actual": float(r[1])}
                          for r in rows if r[0] is not None and r[1] is not None]
                series.reverse()
            else:
                total_row = conn.execute(_text(
                    f"SELECT SUM({_safe_name(target_col, dialect)}) "
                    f"FROM {_safe_name(target_table, dialect)}")).fetchone()
                total = float(total_row[0]) if total_row and total_row[0] is not None else 0.0
                series = [{"period": "all data", "actual": total}]
    except HTTPException:
        raise
    except Exception as exc:
        from core.errors import sanitize_error as _san
        raise HTTPException(status_code=500, detail=f"Scenario data retrieval failed: {_san(exc)[:200]}")
    if not series:
        raise HTTPException(status_code=400, detail="Not enough data for scenario analysis.")
    # Centralized global gate: rows < 10 -> insufficient scenario state.
    # Consume the mapping row count first (csv_handler contract), else the
    # live COUNT(*). REUSES SCENARIO_MIN_OBS == 10 (prescription MIN_N).
    _sc_rows, _sc_known = None, False
    try:
        _ti_sc = (mapping.get("tables") or {}).get(target_table) or {}
        if isinstance(_ti_sc.get("row_count"), int):
            _sc_rows, _sc_known = max(0, int(_ti_sc["row_count"])), True
    except Exception:
        pass
    if not _sc_known:
        try:
            with engine.connect() as _cc:
                _sc_rows = int(_cc.execute(_text(
                    f"SELECT COUNT(*) FROM {_safe_name(target_table, dialect)}")).fetchone()[0] or 0)
            _sc_known = True
        except Exception:
            pass
    if _sc_known:
        _ev_sc = _scenario_evidence_state(_sc_rows, target_table, len(series))
        if _ev_sc is not None and _ev_sc.get("status") != "supported":
            raise HTTPException(status_code=400, detail=_ev_sc.get("reason") or
                                "Not enough data for scenario analysis.")
    baseline = sum(s["actual"] for s in series) / len(series)
    factor = 1.0 + pct / 100.0
    for s in series:
        s["scenario"] = round(s["actual"] * factor, 2)
    scenario_value = round(baseline * factor, 2)
    from insight_agent import sanitize_json
    _ev_sc_ok = None
    try:
        _ev_sc_ok = _scenario_evidence_state(
            _sc_rows if _sc_known else len(series), target_table, len(series))
    except Exception:
        pass
    _sc_payload = {
        "ok": True,
        "estimate": True,
        "table": target_table,
        "column": target_col,
        "pct_change": pct,
        "periods_used": len(series),
        "baseline": round(baseline, 2),
        "scenario_value": scenario_value,
        "delta": round(scenario_value - baseline, 2),
        "series": series,
        "assumptions": [
            f"Uniform {pct:+.1f}% change applied to {target_col} across the last {len(series)} period(s).",
            "No seasonality, trend, capacity, or cost effects modelled.",
            "Baseline is the trailing average, not a forecast.",
        ],
        "limitations": "Arithmetic estimate only. Combine with the validated forecast for a fuller picture.",
    }
    if _ev_sc_ok is not None:
        _sc_payload["evidence_state"] = _ev_sc_ok
    return sanitize_json(_sc_payload)


@router.post("/api/predictive/forecast")
def generate_forecast(req: ForecastRequest, request: Request, user: dict = Depends(require_writable)):
    """Generate a real forecast from the connected database."""
    import traceback as _tb
    session = get_session(user["user_id"])
    reject_document_sql(session)
    schema_path = session.get("schema_path")
    if not schema_path or not Path(str(schema_path)).exists():
        raise HTTPException(status_code=400, detail="No database connected.")

    db_config = dict(session.get("db") or {})
    if not db_config:
        raise HTTPException(status_code=400, detail="No database configuration found.")
    if db_config.get("password"):
        try:
            db_config["password"] = _decrypt_secret(db_config["password"])
        except Exception:
            pass

    db_uri = session.get("db_uri", "")
    db_type = session.get("db_type", "postgresql")
    dialect = "postgresql" if "postgres" in db_type else "mysql" if "mysql" in db_type else "sqlite"
    provider = session.get("provider")

    # Step 0: Validate the requested column against real measures. Keys,
    # FKs and id-like columns (e.g. reports_to) are not forecastable —
    # asking the GoalAgent to "forecast" one yields garbage like COUNT(*).
    # Anything that is not a genuine measure falls back to auto-select.
    from api.schema_intel import SchemaIntelligence as _SI0
    _mapping0 = json.loads(Path(str(schema_path)).read_text(encoding="utf-8"))
    _intel0 = _SI0(_mapping0)
    _want0 = ((req.column or "").split(" (")[0]).strip()
    _measure_tables: dict[str, str] = {}  # lower column -> table
    for _tn in _mapping0.get("tables", {}):
        for _m in (_intel0.find_all_measures(_tn) or []):
            _measure_tables.setdefault(str(_m).lower(), _tn)
    if _want0 and _want0.lower() in _measure_tables:
        valid_measure, valid_table = _want0, _measure_tables[_want0.lower()]
    else:
        valid_measure, valid_table = None, None
        for _tn in _mapping0.get("tables", {}):
            _m = _intel0.find_best_measure(_tn)
            if _m:
                valid_measure, valid_table = _m, _tn
                break
    if valid_measure is None:
        raise HTTPException(
            status_code=400,
            detail="No forecastable number found in this data. Forecasting needs a numeric measure (not ids, keys or codes).",
        )

    # Centralized global gate (core/evidence.py): rows < 10 -> refusal for
    # ALL substantive conclusions, BEFORE any GoalAgent/LLM work. Consume the
    # row counts the mapping exposes; fall back to a live COUNT(*) only when
    # the mapping has no counts. Per-capability forecast minimum
    # (min_points=5 history periods) is REUSED downstream in PredictionAgent.
    _fc_rows, _fc_known = None, False
    try:
        _tinfo0 = (_mapping0.get("tables") or {}).get(valid_table) or {}
        if isinstance(_tinfo0.get("row_count"), int):
            _fc_rows, _fc_known = max(0, int(_tinfo0["row_count"])), True
    except Exception:
        pass
    if not _fc_known:
        try:
            from api.kpi_routes import _build_engine as _kb0
            from api.schema_intel import _safe_name as _sn0
            from sqlalchemy import text as _t0
            _eng0, _dial0, _ = _kb0(session)
            if _eng0 is not None:
                with _eng0.connect() as _c0:
                    _fc_rows = int(_c0.execute(_t0(
                        f"SELECT COUNT(*) FROM {_sn0(valid_table, _dial0)}")).fetchone()[0] or 0)
                _fc_known = True
                try:
                    _eng0.dispose()
                except Exception:
                    pass
        except Exception:
            pass
    if _fc_known:
        try:
            from core.evidence import assess_evidence as _assess_fc
            _ev_fc = _assess_fc(_fc_rows, "forecast", dataset_name=valid_table)
        except Exception:
            _ev_fc = None
        if _ev_fc is not None and _ev_fc.get("status") != "supported":
            from insight_agent import sanitize_json as _sj_fc
            return _sj_fc({
                "ok": False,
                "question": req.question or f"Show {valid_measure} over time",
                "reason": _ev_fc.get("reason"),
                "missing_field": "history",
                "suggestion": "Connect at least 10 usable records, then try again.",
                "target": valid_measure,
                "selection": {"measure": valid_measure, "table": valid_table,
                              "time_dim": None},
                "info": {"rows_analyzed": _fc_rows, "fallback_used": False,
                         "goal_message": None},
                "evidence_state": _ev_fc,
                "reliability": "insufficient_data",
                "n_obs": _fc_rows,
            })

    # Validate the requested time dimension against the table's real
    # temporal candidates; fall back to the best-detected one.
    _tcols = _table_columns(_mapping0.get("tables", {}), valid_table)
    _time_cands = [n for n, d in _tcols
                   if any(k in d.lower() for k in ("date", "time", "timestamp"))
                   or any(h in n.lower() for h in _DATE_NAME_HINTS)]
    _want_t = ((req.time_dim or "").split(" (")[0]).strip()
    valid_time = next((n for n in _time_cands if n.lower() == _want_t.lower()),
                      None) if _want_t else None
    if valid_time is None:
        valid_time = _intel0.find_best_datetime(valid_table)

    # Step 1: Run GoalAgent to get time-series data. When the caller asked
    # for a non-measure column, ask about the validated measure instead —
    # the raw request would only produce garbage SQL.
    if req.question and _want0.lower() in _measure_tables:
        question = req.question
    else:
        question = f"Show {valid_measure} by {valid_time} over time" if valid_time \
            else f"Show {valid_measure} over time"
    output_dir = Path("artifacts/processed_data") / f"user_{user['user_id']}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"forecast_input_{int(time.time())}.json"
    try:
        from core.config import prune_regenerable_outputs as _prune
        _prune(output_dir)
    except Exception:
        pass
    goal_error = None
    try:
        from goal_agent.agent import GoalAgent
        from goal_agent.schema import load_user_overrides
        from core.config import resolve_provider_key

        api_key = resolve_provider_key(provider, session.get("api_keys", {}))
        agent = GoalAgent(
            schema_json_path=str(schema_path),
            db_uri=db_uri,
            provider=provider,
            api_key=api_key,
            dialect=dialect,
            overrides=load_user_overrides(user["user_id"], session.get("db_name", "")),
        )
        goal_result = agent.process_goal(question, output_path=str(output_path))
    except Exception as e:
        # No 500: fall through to the deterministic path, then return an
        # honest invalid forecast with the reason if nothing works.
        log.error("GoalAgent failed: %s\n%s", e, _tb.format_exc())
        goal_error = str(e)[:300]

    # Step 2: Run PredictionAgent
    try:
        from prediction.agent import PredictionAgent

        processed_data = {}
        if output_path.exists():
            processed_data = json.loads(output_path.read_text(encoding="utf-8"))

        # Deterministic fallback: builds the time series directly from the
        # schema — SELECT time, SUM(measure) GROUP BY time ORDER BY time —
        # using the validated measure/table. Fully generic, no hardcoded
        # tables or columns. Runs when the GoalAgent returned zero rows OR
        # when its rows carry no usable time dimension (e.g. a bare COUNT).
        def _deterministic_series():
            try:
                from api.kpi_routes import _build_engine as _kb
                from api.schema_intel import _safe_name as _sn
                from sqlalchemy import text as _t

                _eng, _dial, _dbt = _kb(session)
                _dt = valid_time or _intel0.find_best_datetime(valid_table)
                if _eng is None or not _dt:
                    return None
                with _eng.connect() as _conn:
                    _rows = _conn.execute(_t(
                        f"SELECT {_sn(_dt, _dial)} AS t, SUM({_sn(valid_measure, _dial)}) AS v "
                        f"FROM {_sn(valid_table, _dial)} "
                        f"WHERE {_sn(_dt, _dial)} IS NOT NULL "
                        f"GROUP BY {_sn(_dt, _dial)} "
                        f"ORDER BY {_sn(_dt, _dial)} LIMIT 500"
                    )).fetchall()
                _series = [{_dt: r[0], valid_measure: float(r[1])}
                           for r in _rows if r[0] is not None and r[1] is not None]
                if len(_series) >= 2:
                    return {
                        "user_goal": question,
                        "data": _series,
                        "sql_used": processed_data.get("sql_used") or processed_data.get("sql"),
                        "fallback": "deterministic time aggregation",
                    }
            except Exception as _fe:
                log.warning("Forecast deterministic fallback failed: %s", _fe)
            return None

        # The GoalAgent aggregates and aliases (e.g. amount -> total_amount),
        # so resolve the validated schema column against the ACTUAL result
        # columns (exact, case-insensitive, then substring either way).
        # No match -> auto-select (numeric_col=None) instead of a guaranteed
        # "column not found" failure.
        def _resolve_target(data):
            result_cols = list((data.get("data") or [{}])[0].keys()) \
                if data.get("data") else []
            low = {c.lower(): c for c in result_cols}
            if valid_measure in result_cols:
                return valid_measure
            if valid_measure.lower() in low:
                return low[valid_measure.lower()]
            sub = [c for c in result_cols
                   if valid_measure.lower() in c.lower() or c.lower() in valid_measure.lower()]
            return sub[0] if sub else None

        pred_agent = PredictionAgent(
            min_points=5,
            valid_threshold=70.0,
        )
        goal_sql = processed_data.get("sql_used") or processed_data.get("sql")
        if not (processed_data.get("data") or []):
            _fb = _deterministic_series()
            if _fb:
                processed_data = _fb
        # Pass the validated time dimension through only when it is really a
        # column of the result rows — otherwise the agent auto-detects the
        # time axis from the data (fully dynamic, never assumed).
        def _resolve_time(data):
            result_cols = list((data.get("data") or [{}])[0].keys()) \
                if data.get("data") else []
            if valid_time in result_cols:
                return valid_time
            low = {c.lower(): c for c in result_cols}
            if valid_time and valid_time.lower() in low:
                return low[valid_time.lower()]
            return None

        forecast = pred_agent.forecast(
            processed_data,
            numeric_col=_resolve_target(processed_data),
            datetime_col=_resolve_time(processed_data),
            horizon=req.horizon,
        )
        if not forecast.get("valid") and not (forecast.get("points") or []) \
                and not processed_data.get("fallback"):
            _fb = _deterministic_series()
            if _fb:
                processed_data = _fb
                forecast = pred_agent.forecast(
                    processed_data,
                    numeric_col=_resolve_target(processed_data),
                    datetime_col=_resolve_time(processed_data),
                    horizon=req.horizon,
                )
    except Exception as e:
        from core.errors import sanitize_error as _san3
        log.error("PredictionAgent failed: %s", _san3(e))
        forecast = {
            "ok": False,
            "valid": False,
            "method": "unavailable",
            "model": "none",
            "model_selected": None,
            "candidates": [],
            "drivers": [],
            "details": {},
            "preparation": {},
            "accuracy": {"pct": None, "summary": "Forecast unavailable."},
            "reason": f"Forecast unavailable right now: {_san3(e)[:200]}",
            "missing_field": "internal",
            "suggestion": "Ask ARIA to analyze this dataset instead.",
            "message": None,
            "recommendation": None,
            "n_obs": 0,
            "reliability": "insufficient_data",
            "forecast_stage": "none",
            "points": [],
            "history": [],
            "historical": [],
            "forecast": [],
            "confidence_interval": [],
            "timestamps": [],
            "frequency": None,
            "target": valid_measure,
            "horizon": int(req.horizon or 6),
            "horizon_suggested": None,
            "metrics": {"mae": None, "rmse": None, "mape": None},
            "selection_statement": None,
            "uncertainty_note": None,
            "interval_method": None,
        }

    if not forecast.get("valid") and not (forecast.get("points") or []) \
            and not forecast.get("reason") and goal_error:
        forecast["reason"] = (
            "The data could not be prepared for forecasting right now. "
            "Try again shortly or pick a different number.")
    # Data contract (n.txt item 3): the `forecast` object itself carries the
    # contract keys (historical/forecast/frequency/target/model/horizon/
    # metrics). They are mirrored at the top level for convenience — except
    # `forecast`, which keeps its legacy meaning (the full forecast object);
    # the future series is aliased as `forecast_series` up here.
    from insight_agent import sanitize_json
    # Genuinely unforecastable data: structured graceful JSON (ok:false with
    # reason + missing field + suggestion) — never a fabricated forecast,
    # never a stack trace.
    if forecast.get("ok") is False and not (forecast.get("points") or []):
        try:
            from core.evidence import assess_evidence as _assess_uf
            _ev_uf = _assess_uf(forecast.get("n_obs", 0), "forecast",
                               history_points=forecast.get("n_obs", 0),
                               dataset_name=valid_table)
        except Exception:
            _ev_uf = None
        _uf_payload = {
            "ok": False,
            "question": question,
            "reason": forecast.get("reason") or (
                goal_error or "This dataset cannot be forecast."),
            "missing_field": forecast.get("missing_field"),
            "suggestion": forecast.get("suggestion")
            or "Ask ARIA to analyze this dataset instead.",
            "target": forecast.get("target") or valid_measure,
            "selection": {
                "measure": valid_measure,
                "table": valid_table,
                "time_dim": valid_time,
            },
            "info": {
                "rows_analyzed": len((processed_data.get("data") or [])),
                "fallback_used": bool(processed_data.get("fallback")),
                "goal_message": processed_data.get("message"),
            },
            "preparation": forecast.get("preparation") or {},
            "reliability": forecast.get("reliability"),
            "n_obs": forecast.get("n_obs", 0),
        }
        if _ev_uf is not None:
            _uf_payload["evidence_state"] = _ev_uf
        return sanitize_json(_uf_payload)
    _future_series = forecast.get("forecast") or []
    if isinstance(_future_series, dict):
        _future_series = []
    contract = {
        "historical": forecast.get("historical") or [],
        "forecast_series": _future_series,
        "confidence_interval": forecast.get("confidence_interval") or [],
        "timestamps": forecast.get("timestamps") or [],
        "frequency": forecast.get("frequency"),
        "target": forecast.get("target") or valid_measure,
        "model": forecast.get("model") or forecast.get("method") or "none",
        "model_selected": forecast.get("model_selected")
        or forecast.get("model") or forecast.get("method") or "none",
        "candidates": forecast.get("candidates") or [],
        "drivers": forecast.get("drivers") or [],
        "accuracy": forecast.get("accuracy"),
        "details": forecast.get("details") or {},
        "preparation": forecast.get("preparation") or {},
        "validation": forecast.get("validation") or {},
        "reliability": forecast.get("reliability"),
        "forecast_stage": forecast.get("forecast_stage"),
        "message": forecast.get("message"),
        "recommendation": forecast.get("recommendation"),
        "n_obs": forecast.get("n_obs", 0),
        "horizon": forecast.get("horizon") or int(req.horizon or 6),
        "horizon_suggested": forecast.get("horizon_suggested"),
        "metrics": forecast.get("metrics") or {"mae": None, "rmse": None, "mape": None},
        "selection_statement": forecast.get("selection_statement"),
        "uncertainty_note": forecast.get("uncertainty_note"),
        "interval_method": forecast.get("interval_method")
        or ("pointwise" if (forecast.get("points") or []) else None),
    }
    return sanitize_json({
        "ok": True,
        "question": question,
        "forecast": forecast,
        "selection": {
            "measure": valid_measure,
            "table": valid_table,
            "time_dim": valid_time,
        },
        "info": {
            "rows_analyzed": len((processed_data.get("data") or [])),
            "fallback_used": bool(processed_data.get("fallback")),
            "goal_message": processed_data.get("message"),
        },
        "evidence_state": _evidence_state_for_forecast(
            forecast, _fc_rows if _fc_known else None, valid_table),
        **contract,
    })


@router.post("/api/prescription/generate")
def generate_prescription(req: PrescriptionRequest, request: Request, user: dict = Depends(require_writable)):
    """DEPRECATED — kept for old clients only. Use /api/prescriptions/* or Decision Center instead.

    Legacy duplicate of the prescription path: runs the old GoalAgent ->
    InsightAgent -> PredictionAgent -> PrescriptionAgent chain. New code must
    use the shared prescription_engine (analyze/run_scenario/priority_score/
    quality_gate) via /api/prescriptions/* or the Decision Center
    (/api/decision-center/*), which never calls PrescriptionAgent. DO NOT
    delete this endpoint (old clients still call it)."""
    import traceback as _tb
    session = get_session(user["user_id"])
    reject_document_sql(session)
    schema_path = session.get("schema_path")
    if not schema_path or not Path(str(schema_path)).exists():
        raise HTTPException(status_code=400, detail="No database connected.")

    db_config = dict(session.get("db") or {})
    if not db_config:
        raise HTTPException(status_code=400, detail="No database configuration found.")
    if db_config.get("password"):
        try:
            db_config["password"] = _decrypt_secret(db_config["password"])
        except Exception:
            pass

    db_uri = session.get("db_uri", "")
    db_type = session.get("db_type", "postgresql")
    dialect = "postgresql" if "postgres" in db_type else "mysql" if "mysql" in db_type else "sqlite"
    provider = session.get("provider")

    # Step 1: Run GoalAgent
    try:
        from goal_agent.agent import GoalAgent
        from goal_agent.schema import load_user_overrides
        from core.config import resolve_provider_key

        output_dir = Path("artifacts/processed_data") / f"user_{user['user_id']}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"prescription_input_{int(time.time())}.json"

        api_key = resolve_provider_key(provider, session.get("api_keys", {}))
        agent = GoalAgent(
            schema_json_path=str(schema_path),
            db_uri=db_uri,
            provider=provider,
            api_key=api_key,
            dialect=dialect,
            overrides=load_user_overrides(user["user_id"], session.get("db_name", "")),
        )
        goal_result = agent.process_goal(
            "Analyze the data and identify key metrics, trends, and anomalies",
            output_path=str(output_path),
        )
    except Exception as e:
        from core.errors import sanitize_error as _san2
        raise HTTPException(status_code=500, detail=f"Data preparation failed: {_san2(e)}")

    processed_data = {}
    if output_path.exists():
        processed_data = json.loads(output_path.read_text(encoding="utf-8"))

    # Step 2: Run InsightAgent for KPIs, trends, anomalies
    kpis = []
    trends = []
    anomalies = []
    hypotheses = []
    try:
        # Canonical insight path: insight_agent.agent.InsightAgent only.
        # Advanced/Industry variants (insight_agent/advanced.py,
        # insight_agent/industry.py, repo-root insight_agent_*.py) are
        # intentionally NOT in the live path and stay unreachable but intact.
        from insight_agent.agent import InsightAgent

        insight_agent = InsightAgent(provider=provider)
        insights = insight_agent.analyze(
            str(output_path),  # file path, not dict
            output_path=str(output_dir / f"prescription_insights_{int(time.time())}.json"),
        )
        kpis = insights.get("kpis", [])
        trends = insights.get("trends", [])
        anomalies = insights.get("anomalies", [])
        hypotheses = insights.get("hypotheses", [])
    except Exception as e:
        log.warning("InsightAgent failed: %s", e)

    # Step 3: Run PredictionAgent for forecast
    predictions = None
    try:
        from prediction.agent import PredictionAgent

        pred_agent = PredictionAgent(horizon=6)
        predictions = pred_agent.forecast(processed_data)
    except Exception as e:
        log.warning("PredictionAgent failed: %s", e)

    # Step 4: Run PrescriptionAgent
    try:
        from prescription_agent import PrescriptionAgent

        rx_agent = PrescriptionAgent(provider=provider)
        prescriptions = rx_agent.prescribe(
            processed_data, kpis, trends, anomalies, hypotheses,
            predictions=predictions,
        )
    except Exception as e:
        log.warning("PrescriptionAgent failed: %s", e)
        prescriptions = {
            "actions": [
                "Review the key metrics identified in the analysis",
                "Investigate any anomalies or unusual patterns detected",
                "Monitor the trends highlighted in the data",
            ],
            "source": "template",
            "impact_note": "Impact could not be reliably estimated from the available data.",
        }

    return {
        "ok": True,
        "prescriptions": prescriptions,
        "context": {
            "kpis_count": len(kpis),
            "trends_count": len(trends),
            "anomalies_count": len(anomalies),
            "has_forecast": predictions is not None and predictions.get("valid", False),
        },
    }
