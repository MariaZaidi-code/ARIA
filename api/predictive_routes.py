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

        output_dir = Path("artifacts/processed_data") / f"user_{user['user_id']}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"forecast_input_{int(time.time())}.json"

        agent = GoalAgent(
            schema_json_path=str(schema_path),
            db_uri=db_uri,
            provider=provider,
            dialect=dialect,
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

        output_dir = Path("artifacts/processed_data") / f"user_{user['user_id']}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"prescription_input_{int(time.time())}.json"

        agent = GoalAgent(
            schema_json_path=str(schema_path),
            db_uri=db_uri,
            provider=provider,
            dialect=dialect,
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
