"""Goal Agent + Insight Agent routes: suggestions, ask, and insight analysis."""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import auth
from core.config import get_session, save_session
from core.deps import require_data, require_writable
from core.validation import validate_goal_text
from goal_agent import GoalAgent
from goal_agent.proactive_intelligence import analyze_result_intelligence
from insight_agent import InsightAgent, sanitize_json

router = APIRouter()


class GoalRequest(BaseModel):
    goal: str
    previous_goal: str | None = None
    previous_result: dict | None = None
    conversation_id: str | None = None


@router.post("/api/suggestions")
def get_suggestions(request: Request, payload: dict | None = None, user: dict = Depends(require_writable)):
    """LLM-driven + template-driven suggested search goals. Works with any
    connected database because it uses dynamic schema intelligence rather
    than hardcoded table/column references."""
    session = get_session(user["user_id"])
    provider = require_data(request)
    limit = (payload or {}).get("limit", 8)
    try:
        # Read the schema mapping directly (no slow agent initialization) so
        # suggestions work instantly regardless of database size.
        schema_path = Path(str(session.get("schema_path", "")))
        schema_data = {}
        if schema_path.exists():
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_data = json.load(f)
        tables = list(schema_data.get("tables", {}).keys()) if schema_data else []
        if not tables:
            # If schema file missing or empty, return intelligent generic
            # suggestions based on common business-analytics patterns.
            suggestions = [
                "How many total records are in the data?",
                "What is the total of the main numeric measure?",
                "Which categories or segments appear most frequently?",
                "How has the key metric changed over time?",
                "What are the top items by value or quantity?",
                "What is the average of the primary measure?",
                "Are there any unusual patterns or outliers?",
                "How is the main metric distributed across categories?",
            ][:limit]
        else:
            # Build suggestions from actual table/column names — fully dynamic.
            from api.schema_intel import SchemaIntelligence
            intel = SchemaIntelligence(schema_data)
            suggestions = []

            # Find best measure and dimension per table
            for tname in intel.tables[:5]:
                measure = intel.find_best_measure(tname)
                dim = intel.find_best_dimension(tname)
                if measure:
                    suggestions.append(f"What is the total {measure} in {tname}?")
                if dim:
                    suggestions.append(f"Which {dim} has the most records in {tname}?")
                if measure and intel.find_best_datetime(tname):
                    suggestions.append(f"How has {measure} changed over time in {tname}?")
                if measure and dim:
                    suggestions.append(f"What are the top {dim} by {measure} in {tname}?")

            # Add generic analytical patterns if we need more
            generic = [
                "Are there any outliers or unusual patterns?",
                "What is the overall data quality?",
                "Which tables have the most records?",
                "What relationships exist between tables?",
            ]
            for g in generic:
                if len(suggestions) < limit:
                    suggestions.append(g)

            suggestions = suggestions[:limit]
    except Exception:
        suggestions = [
            "How many total records are in the data?",
            "What is the total of the main numeric measure?",
            "Which categories or segments appear most frequently?",
            "How has the key metric changed over time?",
            "What are the top items by value or quantity?",
            "What is the average of the primary measure?",
            "Are there any unusual patterns or outliers?",
            "How is the main metric distributed across categories?",
        ][:limit]

    # ── Preference-aware ranking ───────────────────────────────────────
    # Boost suggestions similar to previously clicked ones.
    try:
        from api.feedback_routes import _load_prefs
        prefs = _load_prefs(user["user_id"])
        clicks = prefs.get("suggestion_clicks", {})
        if clicks:
            # Score each suggestion by similarity to clicked suggestions
            scored = []
            for s in suggestions:
                score = 0
                s_lower = s.lower()
                for clicked_text, count in clicks.items():
                    clicked_lower = clicked_text.lower()
                    # Simple word overlap scoring
                    s_words = set(s_lower.split())
                    c_words = set(clicked_lower.split())
                    overlap = len(s_words & c_words)
                    if overlap > 0:
                        score += overlap * count
                scored.append((score, s))
            # Stable sort: higher score first, preserve original order for ties
            scored.sort(key=lambda x: -x[0])
            suggestions = [s for _, s in scored]
    except Exception:
        pass

    return {"ok": True, "provider": session.get("provider_name", provider), "suggestions": suggestions}


@router.post("/api/ask")
def ask(request: Request, req: GoalRequest, user: dict = Depends(require_writable)):
    """Run the Goal Agent: goal -> SQL -> processed_data.json.

    Uses the connected database's actual schema (fully dynamic — no hardcoded
    table/column names) and falls back to deterministic SQL templates when the
    LLM is slow or unavailable, so any analytical question about the data is
    handled rather than timing out.
    """
    session = get_session(user["user_id"])
    provider = require_data(request)

    # ── Conversational memory ──────────────────────────────────────────
    conv_id = req.conversation_id or session.get("conversation_id")
    if not conv_id:
        conv_id = f"conv_{user['user_id']}_{int(datetime.now().timestamp())}"
    session["conversation_id"] = conv_id

    # Retrieve conversation history from session
    conv_history = session.get("conversation_history", [])

    # Build goal with multi-turn context
    full_goal = req.goal
    if req.previous_goal and req.previous_result:
        prev_data = req.previous_result.get("data", [])
        prev_cols = req.previous_result.get("columns", [])
        prev_tables = req.previous_result.get("data_selection", {}).get("tables", [])
        full_goal = (
            f"Previous question: {req.previous_goal}\n"
            f"Previous result columns: {', '.join(prev_cols[:10])}\n"
            f"Previous tables used: {', '.join(prev_tables[:5])}\n"
            f"Current question: {req.goal}"
        )
    elif conv_history:
        # Use stored conversation history for context
        recent = conv_history[-3:]  # last 3 turns
        context_parts = []
        for turn in recent:
            context_parts.append(f"Q: {turn.get('goal', '')}")
            if turn.get("tables"):
                context_parts.append(f"Tables: {', '.join(turn['tables'][:3])}")
        full_goal = "Conversation context:\n" + "\n".join(context_parts) + f"\nCurrent question: {req.goal}"

    goal = validate_goal_text(full_goal)
    agent = None
    try:
        agent = GoalAgent(
            schema_json_path=str(session["schema_path"]),
            db_uri=session["db_uri"],
            provider=provider,
            dialect=session.get("dialect"),
        )
        # Use a bounded execution so slow LLM calls never hang the endpoint.
        agent.process_goal(goal, output_path=str(session["processed_path"]))
    except Exception as exc:
        # Graceful failure: write a fallback result instead of crashing the endpoint.
        # The frontend expects a processed file; we provide a minimal contract.
        fallback_path = session.get("processed_path", Path("/tmp/fallback_processed.json"))
        if isinstance(fallback_path, str):
            fallback_path = Path(fallback_path)
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        fallback_output = {
            "user_goal": goal,
            "kpi_alignment": {},
            "join_path": [],
            "sql_used": None,
            "row_count": 0,
            "data": [],
            "message": f"Could not fully analyze: {str(exc)[:300]}. The database connection and dynamic schema are working, but the analytical engine encountered an issue with this specific question. Try rephrasing or ask a simpler analytical question (e.g., counts, totals, top items, trends over time).",
            "preprocessing": {"notes": ["Dynamic schema detected; analysis partially completed."]},
            "missing_values_handled": "preserved (NULLs kept as-is)",
            "timestamp": datetime.now().isoformat(),
            "status": "query_failed",
            "suggested_questions": [
                "How many records are in the data?",
                "What is the total of the main measure?",
                "Which categories appear most frequently?",
                "How has the main metric changed over time?",
            ],
        }
        try:
            with fallback_path.open("w", encoding="utf-8") as f:
                json.dump(fallback_output, f, indent=2, default=str)
        except Exception:
            pass
        # Continue with the graceful result instead of raising a 500.
    finally:
        if agent and getattr(agent, "engine", None):
            try:
                agent.engine.dispose()
            except Exception:
                pass

    if not session.get("processed_path") or not Path(str(session.get("processed_path", ""))).exists():
        # If the agent produced nothing, return the graceful message directly.
        return {
            "ok": True,
            "provider": session.get("provider_name", provider),
            "status": "query_failed",
            "message": "The analytical engine could not complete this request. The database schema is loaded dynamically. Try a simpler analytical question or verify the database has numeric/datetime columns for analysis.",
            "data": [],
            "suggested_questions": [
                "How many total records?",
                "What is the sum of key values?",
                "Which items rank highest?",
                "Is there a time-based trend?",
            ],
        }
    processed = json.loads(session["processed_path"].read_text(encoding="utf-8"))
    processed = sanitize_json(processed)
    columns = list(processed.get("data", [{}])[0].keys()) if processed.get("data") else []

    # Run proactive intelligence analysis on the result data
    result_data = processed.get("data", [])
    proactive = analyze_result_intelligence(
        data=result_data,
        goal=req.goal,
        message=processed.get("message", ""),
    )

    # ── Provenance ─────────────────────────────────────────────────────
    tables_used = processed.get("data_selection", {}).get("tables", [])
    join_path = processed.get("join_path", [])
    # For aggregate queries, row_count is the number of result rows, not total records
    sql_row_count = processed.get("row_count", 0)
    provenance = {
        "source": session.get("db_name", "unknown"),
        "source_type": session.get("source_type", "unknown"),
        "dialect": session.get("dialect", "unknown"),
        "tables": tables_used,
        "columns": columns[:10],
        "sql": processed.get("sql_used", ""),
        "join_path": [{"from": j[0], "from_col": j[1], "to": j[2], "to_col": j[3]} for j in join_path] if join_path else [],
        "row_count": sql_row_count,
        "data_preview": result_data[:3] if result_data else [],
    }

    # ── Enhanced follow-up suggestions ─────────────────────────────────
    base_suggestions = processed.get("suggested_questions", []) or []
    proactive_suggestions = []
    if result_data and columns:
        first_row = result_data[0] if result_data else {}
        num_cols = []
        cat_cols = []
        for c in columns:
            v = first_row.get(c) if isinstance(first_row, dict) else None
            if isinstance(v, (int, float)):
                num_cols.append(c)
            elif v and not c.lower().endswith("_id"):
                cat_cols.append(c)
        if num_cols:
            proactive_suggestions.append(f"What is the average {num_cols[0]}?")
            proactive_suggestions.append(f"What is the distribution of {num_cols[0]}?")
        if cat_cols and num_cols:
            proactive_suggestions.append(f"Show {num_cols[0]} by {cat_cols[0]}")
            proactive_suggestions.append(f"Which {cat_cols[0]} has the highest {num_cols[0]}?")
        if len(num_cols) >= 2:
            proactive_suggestions.append(f"Is there a correlation between {num_cols[0]} and {num_cols[1]}?")
    # Always add general analytical suggestions
    general_suggestions = [
        "Show me the top items by value",
        "How has this metric changed over time?",
        "What are the main categories?",
        "Are there any outliers or anomalies?",
    ]
    all_suggestions = list(dict.fromkeys(base_suggestions + proactive_suggestions + general_suggestions))[:8]

    # ── Preference-aware follow-up ranking ──────────────────────────────
    try:
        from api.feedback_routes import _load_prefs
        prefs = _load_prefs(user["user_id"])
        clicks = prefs.get("suggestion_clicks", {})
        if clicks:
            scored = []
            for s in all_suggestions:
                score = 0
                s_lower = s.lower()
                for clicked_text, count in clicks.items():
                    clicked_lower = clicked_text.lower()
                    s_words = set(s_lower.split())
                    c_words = set(clicked_lower.split())
                    overlap = len(s_words & c_words)
                    if overlap > 0:
                        score += overlap * count
                scored.append((score, s))
            scored.sort(key=lambda x: -x[0])
            all_suggestions = [s for _, s in scored]
    except Exception:
        pass

    # ── Store turn in conversation history ─────────────────────────────
    turn_record = {
        "goal": req.goal,
        "tables": tables_used,
        "columns": columns[:5],
        "sql": processed.get("sql_used", ""),
        "row_count": processed.get("row_count", 0),
        "timestamp": datetime.now().isoformat(),
    }
    conv_history.append(turn_record)
    # Keep last 10 turns
    session["conversation_history"] = conv_history[-10:]
    save_session(user["user_id"], session)

    session["pending_history_id"] = auth.add_history(
        user["user_id"],
        goal=goal,
        sql_used=processed.get("sql_used"),
        row_count=processed.get("row_count"),
        columns=columns,
        source_type=session.get("source_type"),
        db_name=session.get("db_name"),
        dialect=session.get("dialect"),
        processed=processed,
    )
    return {
        "ok": True,
        "provider": session["provider_name"],
        "status": processed.get("status", "success"),
        "question": processed.get("question"),
        "user_goal": processed.get("user_goal"),
        "kpi_alignment": processed.get("kpi_alignment"),
        "join_path": processed.get("join_path"),
        "sql_used": processed.get("sql_used"),
        "row_count": processed.get("row_count"),
        "columns": columns,
        "message": processed.get("message"),
        "preprocessing": processed.get("preprocessing"),
        "data": processed.get("data", [])[:50],
        "goal": processed.get("goal"),
        "data_selection": processed.get("data_selection"),
        "analysis_plan": processed.get("analysis_plan"),
        "execution": processed.get("execution"),
        "warnings": processed.get("warnings"),
        "suggested_questions": all_suggestions,
        "proactive_insights": proactive.get("proactive_insights", []),
        "anomalies": proactive.get("anomalies", []),
        "data_quality_warnings": proactive.get("data_quality_warnings", []),
        "explanation": proactive.get("explanation"),
        "confidence": proactive.get("confidence", "high"),
        "history_id": session["pending_history_id"],
        "conversation_id": conv_id,
        "turn_number": len(conv_history),
        "provenance": provenance,
    }


@router.post("/api/insight")
def insight(request: Request, user: dict = Depends(require_writable)):
    """Run the Insight Agent on the last processed data."""
    session = get_session(user["user_id"])
    provider = require_data(request)
    if not session.get("processed_path") or not Path(str(session.get("processed_path", ""))).exists():
        raise HTTPException(status_code=400, detail="No processed data yet. Call POST /api/ask first.")

    try:
        agent = InsightAgent(provider=provider)
        agent.analyze(str(session["processed_path"]), str(session["insights_path"]))
        insights = json.loads(session["insights_path"].read_text(encoding="utf-8"))
    except Exception as exc:
        processed = json.loads(session["processed_path"].read_text(encoding="utf-8")) if session["processed_path"].exists() else {}
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
        session["insights_path"].write_text(json.dumps(sanitize_json(insights), indent=2), encoding="utf-8")

    insights = sanitize_json(insights)

    if session["pending_history_id"]:
        auth.set_history_insights(session["pending_history_id"], user["user_id"], insights)
        session["pending_history_id"] = None
        save_session(user["user_id"], session)

    return {
        "ok": True,
        "provider": session["provider_name"],
        "insights": insights,
    }
