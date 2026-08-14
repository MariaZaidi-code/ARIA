"""Goal Agent + Insight Agent routes: suggestions, ask, and insight analysis."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
from core.config import SESSION
from core.deps import require_data, require_writable
from core.validation import validate_goal_text
from goal_agent import GoalAgent
from insight_agent import InsightAgent, sanitize_json

router = APIRouter()


class GoalRequest(BaseModel):
    goal: str


@router.post("/api/suggestions")
def get_suggestions(payload: dict | None = None, user: dict = Depends(require_writable)):
    """LLM-driven suggested search goals after analyzing the tables."""
    provider = require_data()
    limit = (payload or {}).get("limit", 8)
    try:
        agent = GoalAgent(schema_json_path=str(SESSION["schema_path"]), db_uri=SESSION["db_uri"], provider=provider, dialect=SESSION["dialect"])
        suggestions = agent.get_suggestions(limit=limit, use_llm=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Suggestion generation failed: {exc}")
    return {"ok": True, "provider": SESSION["provider_name"], "suggestions": suggestions}


@router.post("/api/ask")
def ask(request: GoalRequest, user: dict = Depends(require_writable)):
    """Run the Goal Agent: goal -> SQL -> processed_data.json."""
    provider = require_data()
    goal = validate_goal_text(request.goal)
    try:
        agent = GoalAgent(schema_json_path=str(SESSION["schema_path"]), db_uri=SESSION["db_uri"], provider=provider, dialect=SESSION["dialect"])
        agent.process_goal(goal, output_path=str(SESSION["processed_path"]))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Goal Agent failed: {exc}")

    processed = json.loads(SESSION["processed_path"].read_text(encoding="utf-8"))
    processed = sanitize_json(processed)
    columns = list(processed.get("data", [{}])[0].keys()) if processed.get("data") else []
    SESSION["pending_history_id"] = auth.add_history(
        user["user_id"],
        goal=goal,
        sql_used=processed.get("sql_used"),
        row_count=processed.get("row_count"),
        columns=columns,
        source_type=SESSION["source_type"],
        db_name=SESSION["db_name"],
        dialect=SESSION["dialect"],
        processed=processed,
    )
    return {
        "ok": True,
        "provider": SESSION["provider_name"],
        "user_goal": processed.get("user_goal"),
        "kpi_alignment": processed.get("kpi_alignment"),
        "join_path": processed.get("join_path"),
        "sql_used": processed.get("sql_used"),
        "row_count": processed.get("row_count"),
        "columns": columns,
        "message": processed.get("message"),
        "preprocessing": processed.get("preprocessing"),
        "data": processed.get("data", [])[:50],
        "history_id": SESSION["pending_history_id"],
    }


@router.post("/api/insight")
def insight(user: dict = Depends(require_writable)):
    """Run the Insight Agent on the last processed data."""
    provider = require_data()
    if not SESSION["processed_path"].exists():
        raise HTTPException(status_code=400, detail="No processed data yet. Call POST /api/ask first.")

    try:
        agent = InsightAgent(provider=provider)
        agent.analyze(str(SESSION["processed_path"]), str(SESSION["insights_path"]))
        insights = json.loads(SESSION["insights_path"].read_text(encoding="utf-8"))
    except Exception as exc:
        # Graceful fallback: keep the UI working even if the local LLM times out or
        # the agent crashes on a bad dataset; return a minimal, valid insights payload.
        processed = json.loads(SESSION["processed_path"].read_text(encoding="utf-8")) if SESSION["processed_path"].exists() else {}
        insights = {
            "generated_at": datetime.now().isoformat(),
            "user_goal": processed.get("user_goal", "Unknown goal"),
            "summary": {"rows": processed.get("row_count", 0), "columns": []},
            "kpis": [],
            "trends": [],
            "anomalies": [],
            "hypotheses": [],
            "dashboard": [],
            "business_story": "The insight agent could not complete this analysis, but the dataset was still received and the UI is ready for retry.",
            "warning": str(exc),
        }
        SESSION["insights_path"].write_text(json.dumps(sanitize_json(insights), indent=2), encoding="utf-8")

    # NaN/Inf are not JSON-compliant under Starlette's strict encoder; a
    # stale or hand-edited file must never 500 the endpoint.
    insights = sanitize_json(insights)

    if SESSION["pending_history_id"]:
        auth.set_history_insights(SESSION["pending_history_id"], user["user_id"], insights)

    return {
        "ok": True,
        "provider": SESSION["provider_name"],
        "insights": insights,
    }
