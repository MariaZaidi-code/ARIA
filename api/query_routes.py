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
from goal_agent.schema import load_user_overrides
from goal_agent.proactive_intelligence import analyze_result_intelligence
from insight_agent import InsightAgent, sanitize_json

router = APIRouter()


class GoalRequest(BaseModel):
    goal: str
    previous_goal: str | None = None
    previous_result: dict | None = None
    conversation_id: str | None = None


def _build_why(*, goal, tables, columns, row_count, sql, explanation,
               confidence, warnings) -> dict:
    """Structured Why block (§21): stored at analysis time, shown on demand."""
    limitations = []
    if not row_count:
        limitations.append("The query returned no rows, so no conclusion can be drawn.")
    if warnings:
        limitations.append(f"{len(warnings)} data-quality warning(s) apply to this result.")
    limitations.append("Aggregates describe association in this dataset, not external causation.")
    return {
        "what_happened": (explanation or "Analysis completed over the connected data.").strip()[:800],
        "why_it_matters": (
            f"Answers '{goal}' from {row_count} row(s) across "
            f"{', '.join(tables[:3]) or 'the connected source'}."
        ),
        "evidence": {
            "tables": tables,
            "columns": columns[:10],
            "row_count": row_count,
            "sql": sql,
        },
        "contributing_factors": columns[1:4] if len(columns) > 1 else [],
        "comparisons": [],
        "confidence": confidence,
        "limitations": limitations,
    }


def _build_story(*, goal, tables, columns, result_data, why_block) -> str:
    """Coherent data story (§23): finding → evidence → contributors → next step."""
    n = len(result_data or [])
    first = (result_data or [{}])[0] if result_data else {}
    if isinstance(first, dict) and first:
        lead_col = next(iter(first.keys()))
        lead_val = first[lead_col]
        finding = f"Top result: {lead_col} = {lead_val} across {n} row(s)."
    elif n:
        finding = f"Query returned {n} row(s) from {', '.join(tables[:3]) or 'the source'}."
    else:
        finding = "No matching rows were found for this question."
    evidence = f"Evidence: {why_block['evidence']['row_count']} row(s), columns {', '.join(columns[:5]) or '—'}."
    factors = ""
    if why_block["contributing_factors"]:
        factors = f" Segmented by {', '.join(why_block['contributing_factors'])}."
    return (
        f"{finding} {evidence}{factors} "
        f"Confidence: {why_block['confidence']}. "
        f"Limitation: {why_block['limitations'][0]}"
    )


def _chart_spec_for_result(columns, result_data) -> dict:
    """Chart spec generated from the actual result shape (§19) via the registry."""
    try:
        from insight_agent.chart_catalog import compatible_chart_options
    except Exception:
        return {"chart_type": "table", "reason": "chart catalog unavailable"}
    rows = result_data or []
    first = rows[0] if rows and isinstance(rows[0], dict) else {}
    num, cat, dt = 0, 0, 0
    for c in columns or []:
        v = first.get(c)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            num += 1
        elif isinstance(v, str) and any(k in c.lower() for k in
                                        ("date", "time", "month", "year", "day", "period")):
            dt += 1
        elif v is not None:
            cat += 1
    card = len(set(str((r or {}).get(columns[0])) for r in rows[:200] if isinstance(r, dict))) if columns else 0
    options = compatible_chart_options(num, cat, dt, card)
    if not options:
        return {"chart_type": "table", "reason": "no compatible chart for this shape"}
    top = options[0]
    return {"chart_type": top["chart_type"], "label": top["label"],
            "reason": top["analyst_use"], "compatible": [o["chart_type"] for o in options[1:4]]}


def _summarize_result(goal, columns, result_data) -> str:
    """Deterministic answer sentence from real rows (fallback when the agent
    returns no message, so the Answer section is never empty on success)."""
    rows = result_data or []
    if not rows:
        return f"No matching rows were found for '{goal}'."
    first = rows[0] if isinstance(rows[0], dict) else {}
    if first:
        lead_col = next(iter(first.keys()))
        lead_val = first[lead_col]
        extra = ""
        if len(rows) > 1:
            extra = f" ({len(rows)} rows, led by {lead_val})"
        return f"Top result: {lead_col} = {lead_val}{extra}."
    return f"Query returned {len(rows)} row(s)."


_DOC_INTENT_WORDS = ("target", "goal", "plan", "report", "forecast says",
                      "document", "mentioned", "according to", "versus", "vs ",
                      "compare with", "management", "says", "stated")


def _document_evidence(user_id, goal_text, limit: int = 3) -> list[dict]:
    """Cross-source evidence (§6): search the user's documents when the
    question hints at external information. Returns [] otherwise (cheap:
    skipped entirely when no documents or no doc-intent signal)."""
    try:
        from pathlib import Path as _Path

        from core.config import PROCESSED_DIR
        from document_processor import create_document_processor

        if not any(w in goal_text.lower() for w in _DOC_INTENT_WORDS):
            return []
        doc_dir = PROCESSED_DIR / f"user_{user_id}" / "documents"
        if not _Path(doc_dir).exists() or not any(_Path(doc_dir).iterdir()):
            return []
        processor = create_document_processor(
            upload_dir="data/uploads", processed_dir=doc_dir)
        results = processor.search_documents(query=goal_text, user_id=user_id, k=limit)
        out = []
        for r in results or []:
            out.append({
                "document_id": getattr(r, "document_id", ""),
                "content": (getattr(r, "content", "") or "")[:500],
                "score": getattr(r, "score", 0),
                "page_number": getattr(r, "page_number", None),
            })
        return out
    except Exception:
        return []


def _check_consistency(chart_spec, result_data, why_block) -> dict:
    """§24: chart + result + explanation must describe the same outcome."""
    issues = []
    rows = result_data or []
    ctype = (chart_spec or {}).get("chart_type", "table")
    if not rows and ctype != "table":
        issues.append("empty result paired with a non-table chart; downgraded to table")
        chart_spec = dict(chart_spec or {}, chart_type="table")
    if why_block.get("evidence", {}).get("row_count", 0) != len(rows):
        issues.append("row-count drift between evidence and returned data")
    return {"consistent": not issues, "issues": issues, "chart_spec": chart_spec}


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
    # Explicit-intent-wins (§12): a fresh COUNT/ranking-of-records question
    # must not inherit measures from previous turns ("most readings" means
    # COUNT, even after discussing averages). Only when no measure word is
    # present ("most valuable" stays a revenue ranking).
    import re as _re

    _gl = req.goal.lower()
    _measure_words = ("amount", "value", "price", "revenue", "profit", "total",
                      "average", "avg", "cost", "temperature", "temp", "sales",
                      "money", "score", "rate", "percent")
    _count_like = _re.search(
        r"\b(how many|number of|count\b|most\s+\w+|fewest\s+\w+|least\s+\w+)", _gl)
    if _count_like and not any(w in _gl for w in _measure_words):
        goal = (goal + "\nNOTE: the current question explicitly asks for a count "
                "of records. Use COUNT(*) and do not reuse measures or averages "
                "from previous questions.")
    # Fail fast with an actionable error when schema extraction never
    # completed, instead of leaking an internal path from the agent.
    _schema_path = session.get("schema_path")
    if not _schema_path or not Path(str(_schema_path)).exists():
        status_note = session.get("schema_status", "unknown")
        raise HTTPException(
            status_code=400,
            detail=("Schema extraction did not complete for this connection "
                    f"(status: {status_note}). Reconnect or use Rescan Schema on the Data page, "
                    "then ask again."),
        )
    agent = None
    try:
        agent = GoalAgent(
            schema_json_path=str(session["schema_path"]),
            db_uri=session["db_uri"],
            provider=provider,
            dialect=session.get("dialect"),
            overrides=load_user_overrides(user["user_id"], session.get("db_name", "")),
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
    # Normalize join-path entries: 4-tuples, edge-dicts, or opaque strings.
    norm_joins = []
    for j in join_path or []:
        try:
            if isinstance(j, dict) and {"from", "to"} <= set(j):
                norm_joins.append({
                    "from": j.get("from"), "from_col": j.get("from_col"),
                    "to": j.get("to"), "to_col": j.get("to_col")})
            elif isinstance(j, (list, tuple)) and len(j) >= 4:
                norm_joins.append({"from": j[0], "from_col": j[1], "to": j[2], "to_col": j[3]})
        except Exception:
            continue
    # For aggregate queries, row_count is the number of result rows, not total records
    sql_row_count = processed.get("row_count", 0)
    provenance = {
        "source": session.get("db_name", "unknown"),
        "source_type": session.get("source_type", "unknown"),
        "dialect": session.get("dialect", "unknown"),
        "tables": tables_used,
        "columns": columns[:10],
        "sql": processed.get("sql_used", ""),
        "join_path": norm_joins,
        "row_count": sql_row_count,
        "data_preview": result_data[:3] if result_data else [],
        # Structured envelope (t.txt section 7/57 — additive keys only).
        "methodology": processed.get("methodology", "SQL aggregation over connected source; LLM used for intent/explanation only."),
        "confidence": proactive.get("confidence", "high"),
        "assumptions": processed.get("assumptions", []),
        "warnings": processed.get("warnings", []),
        "timestamp": datetime.now().isoformat(),
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
    # Schema-derived fallback suggestions (spec §21): built from the actual
    # connected schema, never a static generic list.
    general_suggestions = []
    try:
        from api.schema_intel import SchemaIntelligence

        _schema_path = Path(str(session.get("schema_path", "")))
        if _schema_path.exists():
            with open(_schema_path, "r", encoding="utf-8") as _fh:
                _schema_data = json.load(_fh)
            _intel = SchemaIntelligence(_schema_data)
            for _t in list(_intel.tables.keys())[:3]:
                _m = _intel.find_best_measure(_t)
                _d = _intel.find_best_dimension(_t)
                _dt = _intel.find_best_datetime(_t)
                if _m and _d:
                    general_suggestions.append(f"Show {_m} breakdown by {_d}")
                    general_suggestions.append(f"Which {_d} has the highest {_m}?")
                elif _m:
                    general_suggestions.append(f"What is the total {_m}?")
                if _m and _dt:
                    general_suggestions.append(f"How has {_m} changed over time?")
                if len(general_suggestions) >= 6:
                    break
    except Exception:
        pass
    if not general_suggestions:
        # No schema context at all: say so honestly instead of inventing specifics.
        general_suggestions = ["What data is currently connected?"]
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
    # ── Why / story / chart-spec envelope (§20-24, deterministic) ─────────
    why_block = _build_why(
        goal=req.goal, tables=tables_used, columns=columns,
        row_count=processed.get("row_count", 0),
        sql=processed.get("sql_used", ""),
        explanation=proactive.get("explanation"),
        confidence=proactive.get("confidence", "high"),
        warnings=processed.get("warnings", []),
    )
    story_text = _build_story(
        goal=req.goal, tables=tables_used, columns=columns,
        result_data=result_data, why_block=why_block,
    )
    chart_spec = _chart_spec_for_result(columns, result_data)
    consistency = _check_consistency(chart_spec, result_data, why_block)
    answer_message = processed.get("message") or _summarize_result(
        req.goal, columns, result_data)
    # Cross-source: document evidence fused alongside the structured answer.
    doc_evidence = _document_evidence(user["user_id"], req.goal)
    if doc_evidence:
        provenance["document_evidence"] = [
            {"document_id": d["document_id"], "page": d["page_number"],
             "excerpt": d["content"][:200]} for d in doc_evidence
        ]
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
        "message": answer_message,
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
        "why": why_block,
        "story": story_text,
        "chart_spec": chart_spec,
        "consistency": consistency,
        "document_evidence": doc_evidence,
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
