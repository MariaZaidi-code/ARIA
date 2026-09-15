"""Goal Agent + Insight Agent routes: suggestions, ask, and insight analysis."""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import auth
from core.config import get_session, save_session, resolve_provider_key
from core.deps import require_data, require_writable
from core.validation import validate_goal_text
from goal_agent import GoalAgent
from goal_agent.schema import load_user_overrides
from goal_agent.proactive_intelligence import analyze_result_intelligence
from core.analytical_result import analyze_result
from insight_agent import InsightAgent, sanitize_json

log = logging.getLogger(__name__)

router = APIRouter()


class GoalRequest(BaseModel):
    goal: str
    previous_goal: str | None = None
    previous_result: dict | None = None
    conversation_id: str | None = None
    # Context-aware analytics context (all optional; resolved dynamically).
    metric: str | None = None
    time_range: dict | str | None = None
    filters: dict | list | None = None
    grouping: str | list | None = None
    dataset: str | None = None
    previous_context: dict | None = None


def _schema_terms_for(schema_path) -> set:
    """Token vocabulary of real table/column names for schema grounding."""
    try:
        import re as _re

        if not schema_path or not Path(str(schema_path)).exists():
            return set()
        data = json.loads(Path(str(schema_path)).read_text(encoding="utf-8"))
        terms: set = set()
        for tname, tinfo in (data.get("tables", {}) or {}).items():
            terms.add(str(tname).lower())
            for part in _re.split(r"[^a-z0-9]+", str(tname).lower()):
                if part:
                    terms.add(part)
            cols = (tinfo or {}).get("columns", {})
            names = cols.keys() if isinstance(cols, dict) else [
                (c.get("column") if isinstance(c, dict) else str(c)) for c in (cols or [])]
            for cname in names or []:
                terms.add(str(cname).lower())
                for part in _re.split(r"[^a-z0-9]+", str(cname).lower()):
                    if part:
                        terms.add(part)
        return terms
    except Exception:
        return set()


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
    """Cross-source document context (§6): search the user's documents when
    the question hints at external information.

    Returns [] when no documents or no doc-intent signal (cheap: skipped
    entirely).  Uses the canonical ``insight_rag`` pipeline — NOT the legacy
    FAISS ``document_processor`` — so document context and analytical data
    evidence are always served from the same canonical RAG engine.

    Per astra.txt Phase 2: RAG provides *context*, not analytical proof.
    The Decision Center distinguishes ``data_evidence`` (from analytics) from
    ``document_context`` (from this function).
    """
    try:
        from insight_rag.storage import RAGMetadataStore, get_user_vector_store

        if not any(w in goal_text.lower() for w in _DOC_INTENT_WORDS):
            return []

        meta = RAGMetadataStore(str(user_id))
        documents = meta.list_documents()
        if not documents:
            return []

        store = get_user_vector_store(str(user_id))
        results = store.search(goal_text, k=limit)

        out: list[dict] = []
        for doc, score in results:
            m = doc.metadata if hasattr(doc, "metadata") else {}
            out.append({
                "document_id": m.get("document_id", ""),
                "content": (doc.page_content[:500] if hasattr(doc, "page_content") else ""),
                "score": round(float(score), 6),
                "page_number": m.get("page", m.get("page_number")),
                "filename": m.get("filename"),
                "content_type": m.get("content_type", "text"),
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
    except Exception as exc:
        log.warning("Preference-aware suggestion ranking failed: %s", exc, exc_info=True)

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
    # P3 §31: structured pipeline log (internal only, never returned).
    import time as _t0
    import uuid as _uuid
    _req_id = f"q_{_uuid.uuid4().hex[:12]}"
    _start = _t0.time()

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
        api_key = resolve_provider_key(provider, session.get("api_keys", {}))
        agent = GoalAgent(
            schema_json_path=str(session["schema_path"]),
            db_uri=session["db_uri"],
            provider=provider,
            api_key=api_key,
            dialect=session.get("dialect"),
            overrides=load_user_overrides(user["user_id"], session.get("db_name", "")),
        )
        # P3 §31 context for the internal diagnostic trace (never exposed).
        try:
            agent._active_request_id = _req_id
            agent._active_session_id = str(user.get("user_id", ""))
            agent._active_dataset_id = str(session.get("db_name", "") or Path(str(session.get("schema_path", ""))).stem)
            agent._provider_name = session.get("provider_name", provider)
        except Exception:
            pass
        # Use a bounded execution so slow LLM calls never hang the endpoint.
        agent.process_goal(goal, output_path=str(session["processed_path"]))
    except Exception as exc:
        # Graceful failure: write a fallback result instead of crashing the endpoint.
        # The frontend expects a processed file; we provide a minimal contract.
        # P3 §50: sanitize internal details before shaping the user message.
        from core.errors import sanitize_error as _san_q
        _safe_exc = _san_q(exc)
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
            "message": f"Could not fully analyze: {_safe_exc}. The database connection and dynamic schema are working, but the analytical engine encountered an issue with this specific question. Try rephrasing or ask a simpler analytical question (e.g., counts, totals, top items, trends over time).",
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

    # ── Analytical validation / repair / answer synthesis (spec §5-§11) ──
    analysis = analyze_result(
        ir=processed.get("goal_ir") or {},
        columns=columns,
        rows=processed.get("data", []) or [],
        goal=req.goal,
        sql=processed.get("sql_used", ""),
        row_count=processed.get("row_count", 0),
    )
    result_data = analysis["data"]
    columns = analysis["columns"]
    if analysis.get("repaired"):
        processed["data"] = result_data
        processed["row_count"] = len(result_data)
        processed["columns"] = columns
    # Result-validation gate (n.txt item 2): never send a broken frame blindly
    # to the UI. Invalid/empty results keep status honest and fall back to a
    # table viz; guards/auth above (require_writable) are untouched.
    # P3 §31 structured log (internal only — never added to the response).
    import logging as _logging
    _qlog = _logging.getLogger("aria.query_pipeline")
    _valid = bool(analysis.get("valid")) and bool(processed.get("sql_used"))
    _shape = {"rows": len(result_data or []), "columns": list(columns or [])}
    _tables = processed.get("data_selection", {}).get("tables", []) or processed.get("join_path", [])
    _lat = round((_t0.time() - _start) * 1000)
    _qlog.info(
        "pipeline request_id=%s session_id=%s dataset_id=%s question=%r "
        "intent=%s tables=%s columns=%s sql=%.200s validation=%s "
        "exec_status=%s result_shape=%s context=%s model=%s latency_ms=%s final_status=%s",
        _req_id, str(user.get("user_id", "")),
        str(session.get("db_name", "") or ""),
        req.goal[:160],
        (processed.get("goal_ir") or {}).get("intent"),
        _tables, list(columns or [])[:10],
        str(processed.get("sql_used") or "")[:200],
        {"valid": analysis.get("valid"), "repaired": analysis.get("repaired")},
        "ok" if _valid else "failed", _shape,
        {"chart": (analysis.get("chart_spec") or {}).get("chart_type")},
        session.get("provider_name", provider), _lat,
        processed.get("status", "success"),
    )
    if not _valid and processed.get("status") == "success":
        processed["status"] = "query_failed"
    if not result_data and (analysis.get("chart_spec") or {}).get("chart_type") != "table":
        analysis["chart_spec"] = dict(analysis.get("chart_spec") or {},
                                     chart_type="table",
                                     reason="empty result paired with a non-table chart; downgraded to table")

    # Run proactive intelligence analysis on the validated result data
    proactive = analyze_result_intelligence(
        data=result_data,
        goal=req.goal,
        message=analysis.get("answer") or processed.get("message", ""),
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
    except Exception as exc:
        log.warning("Schema-driven follow-up suggestions failed: %s", exc, exc_info=True)
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
    except Exception as exc:
        log.warning("Preference-aware follow-up ranking failed: %s", exc, exc_info=True)

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
    # ── Why / story / chart-spec envelope (§20-24, intent-aware) ─────────
    why_block = analysis["why"]
    story_text = analysis["story"]
    chart_spec = analysis["chart_spec"]
    consistency = analysis["consistency"]
    answer_message = analysis["answer"] or processed.get("message") or _summarize_result(
        req.goal, columns, result_data)
    # Cross-source: document evidence fused alongside the structured answer.
    # Per astra.txt Phase 2: RAG provides *context*, not proof.  The
    # response carries ``document_context`` (from uploaded PDFs) separately
    # from ``data_evidence`` (from SQL analytics) so the Decision Center
    # can label each channel appropriately.
    doc_evidence = _document_evidence(user["user_id"], req.goal)
    if doc_evidence:
        provenance["document_context"] = [
            {"document_id": d["document_id"], "page": d["page_number"],
             "excerpt": d["content"][:200],
             "content_type": d.get("content_type", "text"),
             "filename": d.get("filename")} for d in doc_evidence
        ]
        # Backward-compat: keep the legacy key for any frontend code that
        # still reads ``document_evidence`` directly.
        provenance["document_evidence"] = provenance["document_context"]
    # ── Explicit display metadata (t.txt-5): server-defined metric,
    # aggregation, dimensions, chart recommendation and KPI values. The
    # frontend renders these instead of recomputing them from raw rows.
    _ainfo = analysis.get("analysis", {}) or {}
    _cspec = analysis.get("chart_spec", {}) or {}
    _kpis = {}
    for _c in columns:
        try:
            _vals = [float(r.get(_c)) for r in result_data
                     if r.get(_c) is not None and str(r.get(_c)).strip() != ""
                     and float(r.get(_c)) == float(r.get(_c))]
        except (TypeError, ValueError):
            continue
        if len(_vals) >= 1 and len(_vals) >= max(1, len(result_data) // 2):
            _kpis[_c] = {
                "sum": round(sum(_vals), 2),
                "avg": round(sum(_vals) / len(_vals), 2),
                "min": round(min(_vals), 2),
                "max": round(max(_vals), 2),
                "count": len(_vals),
            }
    display = {
        "metric": _ainfo.get("measure_label"),
        "measure_column": _ainfo.get("measure_column"),
        "aggregation": _ainfo.get("aggregation"),
        "dimensions": _ainfo.get("dimension_columns", []),
        "chart": {"type": _cspec.get("chart_type"), "x": _cspec.get("x"),
                  "y": _cspec.get("y"), "label": _cspec.get("label"),
                  "reason": _cspec.get("reason")},
        "kpis": _kpis,
    }
    # ── Stable analytics contract (AI-Analytics 1-8, 17-20, additive) ──
    # Frontend renders whatever is present; nothing here is hardcoded to a
    # domain or phrase — intent comes from the classifier + schema grounding,
    # values come from executed SQL, errors are sanitized.
    try:
        from goal_agent.analytics_intent import (
            classify_analytics as _classify,
            resolve_comparison as _resolve_cmp,
            map_visualization as _map_viz,
            compute_possible_drivers as _drivers,
            build_followups as _followups,
            decide_status as _decide,
            graceful_message as _grace_msg,
        )
        from core.errors import sanitize_error as _san
        _schema_terms = _schema_terms_for(session.get("schema_path"))
        _cls = _classify(req.goal, _schema_terms)
        _primary = _cls.get("primary", "descriptive_summary")
        _capabilities = _cls.get("capabilities", [_primary])
        _cmp = _resolve_cmp(req.goal, req.time_range,
                            req.previous_context
                            or ({"question": req.previous_goal}
                                if req.previous_goal else None))
        _metric_col = (_ainfo.get("measure_column")
                       or display.get("measure_column")
                       or req.metric)
        _metric_label = (_ainfo.get("measure_label")
                         or display.get("metric")
                         or _metric_col)
        _dims = list(_ainfo.get("dimension_columns", [])
                     or display.get("dimensions", []) or [])
        if req.grouping:
            _g = [req.grouping] if isinstance(req.grouping, str) else list(req.grouping)
            for _x in _g:
                if _x and _x not in _dims:
                    _dims.append(_x)
        _tables_used = list(tables_used or []) or list(
            (processed.get("data_selection", {}) or {}).get("tables", []) or [])
        _main_table = _tables_used[0] if _tables_used else None
        # Possible drivers from REAL aggregates (best-effort, never fatal).
        _drivers_list: list = []
        try:
            if _main_table and _metric_col and result_data:
                from sqlalchemy import create_engine as _mk
                _eng = _mk(session["db_uri"])
                try:
                    _drivers_list = _drivers(
                        _eng, session.get("dialect", "postgresql"),
                        _main_table, _metric_col, _dims,
                        period_label=_cmp.get("granularity", ""))
                finally:
                    try:
                        _eng.dispose()
                    except Exception:
                        pass
        except Exception:
            _drivers_list = []
        _viz_type = _map_viz(_primary, chart_spec)
        _evidence = [{
            "tables": _tables_used,
            "columns": columns[:10],
            "row_count": len(result_data or []),
            "values": (result_data or [])[:5],
            "sql": processed.get("sql_used", ""),
        }]
        _findings: list[str] = []
        _ans = (answer_message or "").strip()
        if _ans:
            _findings.append(_ans[:500])
        _findings.append(_cmp.get("description", ""))
        for _pi in (proactive.get("proactive_insights", []) or [])[:3]:
            _t = _pi if isinstance(_pi, str) else str(
                (_pi or {}).get("insight") or (_pi or {}).get("text") or _pi)[:300]
            if _t and _t not in _findings:
                _findings.append(_t)
        _limitations = list((why_block or {}).get("limitations", []) or [])
        for _iss in (analysis.get("issues", []) or []):
            if _iss and _iss not in _limitations:
                _limitations.append(str(_iss))
        _recommendations: list[dict] = []
        for _pi in (proactive.get("proactive_insights", []) or [])[:4]:
            if isinstance(_pi, dict) and (_pi.get("action") or _pi.get("recommendation")):
                _recommendations.append({
                    "text": str(_pi.get("action") or _pi.get("recommendation"))[:400],
                    "evidence": _pi.get("evidence") or _tables_used,
                    "confidence": _pi.get("confidence") or proactive.get("confidence", "medium"),
                })
        _hypothesis = None
        if _primary in ("explanation", "root_cause", "hypothesis",
                        "change_detection", "anomaly") or _drivers_list:
            if _drivers_list:
                _top = _drivers_list[0]
                _hypothesis = {
                    "text": (f"Observed association: {_top.get('value')} "
                             f"({_top.get('dimension')}) accounts for about "
                             f"{_top.get('contribution_pct')}% of "
                             f"{_metric_label} in "
                             f"{_top.get('period')}. This is a statistical "
                             f"association in the data, not a proven cause."),
                    "confidence": _top.get("confidence", "low"),
                    "drivers": [d.get("driver") for d in _drivers_list[:3]],
                }
            else:
                _hypothesis = {
                    "text": (f"No strong association found for {_metric_label}: "
                             "no single segment dominates in the returned "
                             "data. Statistical association only, not proven cause."),
                    "confidence": "low",
                    "drivers": [],
                }
        _follow = _followups(req.goal, _primary, _metric_label, _dims,
                             _cmp.get("granularity", ""), _drivers_list)
        # Merge result-derived follow-ups first, keep backend suggestions.
        _merged_follow = list(dict.fromkeys(_follow + list(all_suggestions or [])))[:8]
        _clar = bool(processed.get("status") == "needs_clarification"
                     or "clarification" in str(processed.get("status", "")))
        _rstatus = _decide(valid=bool(analysis.get("valid", True)),
                           rows=result_data or [],
                           repaired=bool(analysis.get("repaired", False)),
                           clarification=_clar,
                           issues=analysis.get("issues", []) or [])
        if processed.get("status") not in ("success", "needs_clarification"):
            _rstatus = "backend-failure" if _rstatus == "success" else _rstatus
        _analytics_envelope = {
            "interpreted_intent": {"primary": _primary,
                                   "capabilities": _capabilities,
                                   "confidence": _cls.get("confidence", "low")},
            "metric": _metric_label,
            "metric_column": _metric_col,
            "dimensions": _dims,
            "filters": req.filters or (processed.get("data_selection", {}) or {}).get("filters", []),
            "time_range": req.time_range or {},
            "comparison_period": _cmp,
            "answer": _ans,
            "findings": _findings[:8],
            "evidence": _evidence,
            "visualization": {"type": _viz_type,
                              "data": (result_data or [])[:50],
                              "x": (_cspec.get("x")),
                              "y": (_cspec.get("y"))},
            "confidence": proactive.get("confidence", "high"),
            "limitations": _limitations,
            "possible_drivers": _drivers_list,
            "hypothesis": _hypothesis,
            "recommendations": _recommendations,
            "follow_up_questions": _merged_follow,
            "result_status": _rstatus,
            "result_message": _grace_msg(_rstatus),
        }
    except Exception as _env_exc:
        from core.errors import sanitize_error as _san2
        _analytics_envelope = {
            "interpreted_intent": {"primary": "descriptive_summary",
                                   "capabilities": ["descriptive_summary"],
                                   "confidence": "low"},
            "metric": None, "dimensions": [], "filters": req.filters or [],
            "time_range": req.time_range or {},
            "comparison_period": {"granularity": "month",
                                  "description": "Comparison unavailable."},
            "answer": answer_message, "findings": [answer_message] if answer_message else [],
            "evidence": [], "visualization": {"type": "bar", "data": []},
            "confidence": "low", "limitations": [_san2(_env_exc)],
            "possible_drivers": [], "hypothesis": None, "recommendations": [],
            "follow_up_questions": list(all_suggestions or [])[:8],
            "result_status": "partial",
            "result_message": ("Partial result: extended analytics metadata "
                               "was unavailable. Core findings above are intact."),
        }
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
        "suggested_questions": _analytics_envelope.get("follow_up_questions", all_suggestions),
        "suggestedQuestions": _analytics_envelope.get("follow_up_questions", all_suggestions),
        "proactive_insights": proactive.get("proactive_insights", []),
        "anomalies": proactive.get("anomalies", []),
        "data_quality_warnings": proactive.get("data_quality_warnings", []),
        "explanation": proactive.get("explanation"),
        "confidence": proactive.get("confidence", "high"),
        "why": why_block,
        "story": story_text,
        "chart_spec": chart_spec,
        "display": display,
        "consistency": consistency,
        "analysis": analysis.get("analysis"),
        "result_valid": analysis.get("valid", True),
        "repaired": analysis.get("repaired", False),
        "document_context": doc_evidence,
        "history_id": session["pending_history_id"],
        "conversation_id": conv_id,
        "turn_number": len(conv_history),
        "provenance": provenance,
        **_analytics_envelope,
    }


@router.post("/api/insight")
def insight(request: Request, user: dict = Depends(require_writable)):
    """Run the Insight Agent on the last processed data.

    Legacy path kept for existing callers (Dashboard/Predictive summaries).
    The canonical Insights page uses GET /api/insights (InsightsEngine-shaped
    cards) and never renders this payload as cards.
    """
    session = get_session(user["user_id"])
    provider = require_data(request)
    if not session.get("processed_path") or not Path(str(session.get("processed_path", ""))).exists():
        raise HTTPException(status_code=400, detail="No processed data yet. Call POST /api/ask first.")

    try:
        agent = InsightAgent(provider=provider)
        agent.analyze(str(session["processed_path"]), str(session["insights_path"]))
        insights = json.loads(session["insights_path"].read_text(encoding="utf-8"))
    except Exception as exc:
        from core.errors import sanitize_error as _san_i
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
            "warning": _san_i(exc),
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
