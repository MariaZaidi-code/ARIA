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
from core.deps import require_data, require_writable
from core.secret_box import decrypt as _decrypt_secret

log = logging.getLogger("aria.predictive_routes")
router = APIRouter()


class ForecastRequest(BaseModel):
    question: str = ""
    column: str | None = None
    horizon: int = 6


class PrescriptionRequest(BaseModel):
    insight_id: str = ""


class ScenarioRequest(BaseModel):
    column: str | None = None
    pct_change: float = 10.0
    periods: int = 3


@router.post("/api/predictive/scenario")
def run_scenario(req: ScenarioRequest, request: Request, user: dict = Depends(require_writable)):
    """Deterministic what-if analysis on real aggregates (spec §16).

    Applies a user-supplied percentage change to the trailing average of a
    measure. Pure arithmetic — labelled an estimate, never a forecast.
    """
    session = get_session(user["user_id"])
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
    if req.column:
        want = req.column.split(" (")[0].strip().lower()
        for tname, tinfo in tables.items():
            cols = tinfo.get("columns", []) if isinstance(tinfo, dict) else []
            names = [(c.get("column") if isinstance(c, dict) else c) for c in cols]
            for n in names:
                if n and str(n).lower() == want:
                    target_table, target_col = tname, n
                    break
            if target_table:
                break
    if not target_col:
        for tname in tables:
            m = intel.find_best_measure(tname)
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
    try:
        with engine.connect() as conn:
            if dt_col:
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
                          for r in rows if r[1] is not None]
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
        raise HTTPException(status_code=500, detail=f"Scenario data retrieval failed: {str(exc)[:200]}")
    if not series:
        raise HTTPException(status_code=400, detail="Not enough data for scenario analysis.")
    baseline = sum(s["actual"] for s in series) / len(series)
    factor = 1.0 + pct / 100.0
    for s in series:
        s["scenario"] = round(s["actual"] * factor, 2)
    scenario_value = round(baseline * factor, 2)
    return {
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


@router.post("/api/predictive/forecast")
def generate_forecast(req: ForecastRequest, request: Request, user: dict = Depends(require_writable)):
    """Generate a real forecast from the connected database."""
    import traceback as _tb
    session = get_session(user["user_id"])
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

    # Step 1: Run GoalAgent to get time-series data
    question = req.question or "Show me the trend of the main measure over time"
    try:
        from goal_agent.agent import GoalAgent
        from goal_agent.schema import load_user_overrides

        output_dir = Path("artifacts/processed_data") / f"user_{user['user_id']}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"forecast_input_{int(time.time())}.json"

        agent = GoalAgent(
            schema_json_path=str(schema_path),
            db_uri=db_uri,
            provider=provider,
            dialect=dialect,
            overrides=load_user_overrides(user["user_id"], session.get("db_name", "")),
        )
        goal_result = agent.process_goal(question, output_path=str(output_path))
    except Exception as e:
        log.error("GoalAgent failed: %s\n%s", e, _tb.format_exc())
        raise HTTPException(status_code=500, detail=f"Data preparation failed: {str(e)}")

    # Step 2: Run PredictionAgent
    try:
        from prediction.agent import PredictionAgent

        processed_data = {}
        if output_path.exists():
            processed_data = json.loads(output_path.read_text(encoding="utf-8"))

        pred_agent = PredictionAgent(
            horizon=req.horizon,
            min_points=5,
            valid_threshold=70.0,
        )
        forecast = pred_agent.forecast(
            processed_data,
            numeric_col=req.column,
        )
    except Exception as e:
        log.error("PredictionAgent failed: %s\n%s", e, _tb.format_exc())
        forecast = {
            "valid": False,
            "method": "unavailable",
            "error": str(e),
            "points": [],
        }

    return {
        "ok": True,
        "question": question,
        "forecast": forecast,
    }


@router.post("/api/prescription/generate")
def generate_prescription(req: PrescriptionRequest, request: Request, user: dict = Depends(require_writable)):
    """Generate evidence-based recommendations from the connected data."""
    import traceback as _tb
    session = get_session(user["user_id"])
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

        output_dir = Path("artifacts/processed_data") / f"user_{user['user_id']}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"prescription_input_{int(time.time())}.json"

        agent = GoalAgent(
            schema_json_path=str(schema_path),
            db_uri=db_uri,
            provider=provider,
            dialect=dialect,
            overrides=load_user_overrides(user["user_id"], session.get("db_name", "")),
        )
        goal_result = agent.process_goal(
            "Analyze the data and identify key metrics, trends, and anomalies",
            output_path=str(output_path),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data preparation failed: {str(e)}")

    processed_data = {}
    if output_path.exists():
        processed_data = json.loads(output_path.read_text(encoding="utf-8"))

    # Step 2: Run InsightAgent for KPIs, trends, anomalies
    kpis = []
    trends = []
    anomalies = []
    hypotheses = []
    try:
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
