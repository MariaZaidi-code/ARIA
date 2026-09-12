"""Prescription API: evidence-gated action workspace endpoints.

GET  /api/prescriptions/context   dynamic metrics/drivers/dimensions/dates
POST /api/prescriptions/analyze   ranked prescriptions or honest refusal
POST /api/prescriptions/scenario  read-only scenario recomputation
POST /api/prescriptions/save      persist a structured prescription
GET  /api/prescriptions/saved     list saved prescriptions
DELETE /api/prescriptions/saved/{sid}  remove one
"""

import time
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from core.config import get_session, save_session
from core.deps import get_current_user, require_writable
from api.hypothesis_routes import _engine_for_session

router = APIRouter(tags=["prescriptions"])


class SegmentRef(BaseModel):
    field: str | None = None
    value: str | int | float | None = None


class AnalyzeContext(BaseModel):
    origin: str | None = None
    insight_id: str | None = None
    metric: str | None = None
    driver: str | None = None
    effect: float | None = None
    confidence: str | None = None


class AnalyzeRequest(BaseModel):
    context: AnalyzeContext | None = None
    metric: str | None = None
    driver: str | None = None
    dimensions: list[str] | None = None
    segment: SegmentRef | None = None
    table: str | None = None
    question: str | None = None


class ScenarioChange(BaseModel):
    field: str
    operation: str
    value: float


class ScenarioFilter(BaseModel):
    field: str
    operator: str = "equals"
    value: str | int | float


class ScenarioJoin(BaseModel):
    table: str
    self_col: str
    other_col: str


class ScenarioRequest(BaseModel):
    table: str
    metric: str
    driver: str
    changes: list[ScenarioChange] = []
    filters: list[ScenarioFilter] | None = None
    join: ScenarioJoin | None = None


class SaveRequest(BaseModel):
    prescription: dict = {}
    question: str | None = None


def _setup(user):
    """Shared loader: mapping + tables + engine for any supported source."""
    from api.schema_intel import SchemaIntelligence
    session = get_session(user["user_id"])
    schema_path = session.get("schema_path")
    if not schema_path:
        return None, {"ok": False, "success": False, "code": "NO_CONNECTION",
                      "detail": "No data source is connected yet.", "recoverable": True}
    try:
        from pathlib import Path as _P
        import json as _j
        mapping = _j.loads(_P(str(schema_path)).read_text(encoding="utf-8"))
    except Exception:
        return None, {"ok": False, "success": False, "code": "NO_CONNECTION",
                      "detail": "The schema description could not be read. Reconnect first.",
                      "recoverable": True}
    tables = list(mapping.get("tables", {}).keys())
    if not tables:
        return None, {"ok": False, "success": False, "code": "NO_CONNECTION",
                      "detail": "The connected source has no tables to analyze.",
                      "recoverable": True}
    engine, dialect = _engine_for_session(session)
    if engine is None:
        return None, {"ok": False, "success": False, "code": "NO_CONNECTION",
                      "detail": dialect, "recoverable": True}
    return (mapping, tables, engine, dialect, SchemaIntelligence(mapping), session), None


def _doc_setup(user):
    """Text-only document source: reloadable chunk texts, no model loading.

    Returns ((chunks, doc_name, session), None) or (None, err). Chunk text
    comes straight from the vector store's SQLite metadata — deterministic,
    no embeddings needed.
    """
    import sqlite3
    from pathlib import Path
    from core.config import PROCESSED_DIR
    session = get_session(user["user_id"])
    if session.get("source_type") != "document" or not session.get("document_id"):
        return None, None
    doc_id = session["document_id"]
    docs_dir = Path(str(PROCESSED_DIR)) / f"user_{user['user_id']}" / "documents"
    doc_name = doc_id
    try:
        meta = (docs_dir / f"{doc_id}.json").read_text(encoding="utf-8")
        import json as _j
        doc_name = _j.loads(meta).get("original_name") or _j.loads(meta).get("name") or doc_id
    except Exception:
        pass
    db_path = docs_dir / "vector_metadata.db"
    if not db_path.exists():
        return None, {"ok": False, "success": False, "code": "NO_CONNECTION",
                      "detail": "This document has no readable text to base recommendations on.",
                      "recoverable": True}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT chunk_id, content, page_number, section FROM chunks "
            "WHERE document_id = ? ORDER BY rowid LIMIT 400", (doc_id,)).fetchall()
        conn.close()
    except Exception:
        return None, {"ok": False, "success": False, "code": "NO_CONNECTION",
                      "detail": "This document has no readable text to base recommendations on.",
                      "recoverable": True}
    chunks = [{"id": r[0], "content": r[1], "page_number": r[2], "section": r[3]}
              for r in rows if (r[1] or "").strip()]
    if not chunks:
        return None, {"ok": False, "success": False, "code": "NO_CONNECTION",
                      "detail": "This document has no readable text to base recommendations on.",
                      "recoverable": True}
    return (chunks, doc_name, session), None


@router.get("/api/prescriptions/context")
def prescription_context(user: dict = Depends(get_current_user)):
    """Dynamically discovered prescription context — never hardcoded columns."""
    from hypothesis_engine import data_context
    from insight_agent import sanitize_json
    setup, err = _setup(user)
    if err:
        doc, doc_err = _doc_setup(user)
        if doc is None:
            return err if doc_err is None else doc_err
        chunks, doc_name, session = doc
        return sanitize_json({
            "ok": True, "success": True,
            "connection": {"status": "connected", "source_type": "document",
                           "db_name": doc_name},
            "document": {"name": doc_name, "chunks": len(chunks), "tables": 0},
            "metrics": [], "drivers": [], "dimensions": [],
            "date_columns": [], "tables": [], "time_range": {},
            "opportunities": [],
            "limitations": ["Text-only document — qualitative recommendations with "
                            "citations only; no numeric modeling is possible."],
            "latest": {"saved_insights": len(session.get("saved_insights", [])),
                       "saved_prescriptions": len(session.get("saved_prescriptions", []))},
        })
    mapping, tables, engine, dialect, intel, session = setup
    try:
        ctx = data_context(engine, dialect, intel, tables)
        # Derived stay-length driver: offered only when the table really has
        # 2+ date columns — still 100% data-based, never assumed.
        by_table: dict[str, list] = {}
        for d in ctx.get("date_columns", []):
            by_table.setdefault(d["table"], []).append(d["column"])
        for t, cols in by_table.items():
            if len(cols) >= 2:
                ctx["drivers"].append({"table": t, "column": "length_of_stay",
                                       "kind": "derived",
                                       "note": f"days between {cols[0]} and {cols[1]}"})
        enrich = _enrich_context(engine, dialect, intel, tables, session)
        return sanitize_json({"ok": True, "success": True,
                              "connection": {"status": "connected",
                                             "source_type": session.get("source_type"),
                                             "db_name": session.get("db_name")},
                              **ctx, **enrich})
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


def _enrich_context(engine, dialect, intel, tables, session):
    """Opportunities, per-table limitations, and latest saved evidence (§1).

    Opportunity candidates are schema-discovered only (no data scanned):
    metric × controllable-ish drivers, derived stay length, and declared
    joins. Actionable reasons name row counts and missing pieces.
    """
    from prescription_engine.engine import _usable_measures, classify_driver, _edge_neighbors
    from sqlalchemy import text as _t
    opportunities, limitations = [], []

    def _count(table):
        from api.schema_intel import _safe_name
        try:
            with engine.connect() as conn:
                return int(conn.execute(
                    _t(f"SELECT COUNT(*) FROM {_safe_name(table, dialect)}")).scalar() or 0)
        except Exception:
            return -1

    for t in tables[:3]:
        measures = _usable_measures(intel, t)
        n = _count(t)
        if n >= 0 and n < 10:
            limitations.append(f"{t}: only {n} rows — below the 10-observation minimum for modeling.")
            continue
        if not measures:
            limitations.append(f"{t}: no measurable numeric columns to improve.")
            continue
        dates = intel.get_datetime_cols(t)
        neighbors = _edge_neighbors(intel, t)
        for m in measures[:2]:
            cands = []
            for c in measures:
                if c != m:
                    cands.append((c, None, "same table"))
            if len(dates) >= 2:
                cands.append(("length_of_stay", None, "derived from dates"))
            for ot, sc, oc in neighbors:
                for c in _usable_measures(intel, ot)[:2]:
                    cands.append((c, ot, f"via {t}.{sc} → {ot}.{oc}"))
                    if len(cands) >= 4:
                        break
                if len(cands) >= 4:
                    break
            if not cands:
                limitations.append(f"{t}.{m}: no other numbers reachable to test as drivers.")
                continue
            for c, ot, how in cands[:3]:
                level, _ = classify_driver(c, "numeric")
                opportunities.append({"table": t, "metric": m, "driver": c,
                                      "driver_table": ot or t, "control": level,
                                      "note": how})
    saved_rx = session.get("saved_prescriptions", [])
    latest = {"saved_insights": len(session.get("saved_insights", [])),
              "saved_prescriptions": len(saved_rx)}
    if saved_rx:
        latest["last_prescription"] = {k: saved_rx[0].get(k)
                                       for k in ("id", "title", "created_at")}
    return {"opportunities": opportunities[:9], "table_limitations": limitations[:6],
            "latest": latest}


@router.post("/api/prescriptions/analyze")
def prescription_analyze(req: AnalyzeRequest, request: Request,
                         user: dict = Depends(require_writable)):
    """Ranked, evidence-backed prescriptions — or an honest refusal."""
    from prescription_engine import analyze as _analyze, analyze_document as _analyze_doc
    from insight_agent import sanitize_json
    setup, err = _setup(user)
    if err:
        doc, doc_err = _doc_setup(user)
        if doc is None:
            return err if doc_err is None else doc_err
        chunks, doc_name, _ = doc
        out = _analyze_doc(chunks, (req.question or ""), doc_name)
        return sanitize_json(out)
    mapping, tables, engine, dialect, intel, session = setup
    try:
        metric = req.metric or (req.context.metric if req.context else None)
        driver = req.driver or (req.context.driver if req.context else None)
        priors = {}
        if req.context:
            priors = {"origin": req.context.origin, "insight_id": req.context.insight_id,
                      "effect": req.context.effect, "confidence": req.context.confidence}
        if not metric:
            return {"ok": False, "success": False, "code": "INVALID_METRIC",
                    "detail": "Choose a target metric first — ARIA won't guess what to improve.",
                    "recoverable": True}
        # Locate the metric's table (schema-discovered, never assumed).
        table = req.table
        if table not in tables:
            table = None
            for t in tables:
                if metric in [c for c in intel.get_numeric_cols(t)]:
                    table = t
                    break
        if not table:
            return {"ok": False, "success": False, "code": "INVALID_METRIC",
                    "detail": f"ARIA couldn't find a measurable '{metric}' in this data.",
                    "recoverable": True}
        seg = None
        if req.segment and req.segment.field:
            seg = {"field": req.segment.field, "value": req.segment.value}
        out = _analyze(engine, dialect, intel, table, metric, driver=driver,
                       dimensions=req.dimensions, segment=seg,
                       question=req.question, priors=priors)
        if out.get("status") == "completed":
            polished = _polish_story(session, out)
            if polished:
                out["story"] = polished
        return sanitize_json(out)
    except Exception:
        import logging as _logging
        _logging.getLogger("aria.prescription").exception("Analyze failed")
        return {"ok": False, "success": False, "code": "ANALYSIS_FAILED",
                "detail": "Prescription analysis failed unexpectedly. Your data was not changed.",
                "recoverable": True}
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


def _polish_story(session, out):
    """LLM rewording of the story only; None on any failure (§24).

    Skipped for the local provider: a cold/slow Ollama can stall the
    response ~30s for zero analytical gain — the deterministic story,
    built from real numbers, is the product.
    """
    try:
        if (session.get("provider_name") or "local") == "local":
            return None
        prov = session.get("provider")
        if prov is None:
            return None
        fit = out.get("fit", {})
        prompt = (
            "Rewrite this business finding in one plain sentence for a manager. "
            "Keep every number exactly as given. Do not calculate, invent, or "
            "claim causality.\nFinding: " + str(out.get("story"))
            + f"\nNumbers: r={fit.get('r')}, n={fit.get('n')}, p={fit.get('p_value')}"
        )
        text = prov.chat("story", messages=[{"role": "user", "content": prompt}],
                         temperature=0.3, num_predict=120, timeout=30)
        text = (text or "").strip()
        if 20 <= len(text) <= 400:
            return text
    except Exception:
        pass
    return None


@router.post("/api/prescriptions/scenario")
def prescription_scenario(req: ScenarioRequest, request: Request,
                          user: dict = Depends(require_writable)):
    """Read-only scenario recomputation — the source database is never touched."""
    from prescription_engine import run_scenario as _scenario
    from insight_agent import sanitize_json
    setup, err = _setup(user)
    if err:
        doc, doc_err = _doc_setup(user)
        if doc is None:
            return err if doc_err is None else doc_err
        return {"ok": False, "success": False, "code": "SCENARIO_UNSUPPORTED",
                "detail": "Scenarios need modeled numbers; this source is a text document. "
                          "Use the cited passages above instead.",
                "recoverable": True}
    mapping, tables, engine, dialect, intel, session = setup
    try:
        if req.table not in tables:
            return {"ok": False, "success": False, "code": "SCENARIO_UNSUPPORTED",
                    "detail": "Unknown table for this scenario.", "recoverable": True}
        filt = None
        if req.filters:
            f0 = req.filters[0]
            if (f0.operator or "equals") != "equals":
                return {"ok": False, "success": False, "code": "SCENARIO_UNSUPPORTED",
                        "detail": "Only 'equals' segment filters are supported.",
                        "recoverable": True}
            filt = (f0.field, f0.value)
        join = None
        if req.join:
            # Validate the join against DECLARED edges only (§34) — the
            # frontend may never inject arbitrary join SQL.
            from prescription_engine.engine import _edge_neighbors
            allowed = _edge_neighbors(intel, req.table)
            if (req.join.table, req.join.self_col, req.join.other_col) not in allowed:
                return {"ok": False, "success": False, "code": "SCENARIO_UNSUPPORTED",
                        "detail": "Unknown join for this scenario.", "recoverable": True}
            join = (req.join.table, req.join.self_col, req.join.other_col)
        out = _scenario(engine, dialect, intel, req.table, req.metric, req.driver,
                        [c.model_dump() for c in req.changes], filt=filt, join=join)
        return sanitize_json(out)
    except Exception:
        import logging as _logging
        _logging.getLogger("aria.prescription").exception("Scenario failed")
        return {"ok": False, "success": False, "code": "ANALYSIS_FAILED",
                "detail": "Scenario failed unexpectedly. Your data was not changed.",
                "recoverable": True}
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


@router.post("/api/prescriptions/save")
def prescription_save(req: SaveRequest, request: Request,
                      user: dict = Depends(require_writable)):
    """Persist the structured prescription — never prose alone (§28)."""
    session = get_session(user["user_id"])
    saved = session.get("saved_prescriptions", [])
    entry = {"id": f"rxsv_{int(time.time() * 1000)}",
             "created_at": datetime.now().isoformat(),
             "question": req.question,
             **(req.prescription or {})}
    saved = [entry] + saved[:49]
    session["saved_prescriptions"] = saved
    save_session(user["user_id"], session)
    return {"ok": True, "success": True, "saved": saved}


@router.get("/api/prescriptions/saved")
def prescription_saved(user: dict = Depends(require_writable)):
    session = get_session(user["user_id"])
    return {"ok": True, "success": True,
            "saved": session.get("saved_prescriptions", [])}


@router.delete("/api/prescriptions/saved/{sid}")
def prescription_unsave(sid: str, user: dict = Depends(require_writable)):
    session = get_session(user["user_id"])
    saved = [s for s in session.get("saved_prescriptions", []) if s.get("id") != sid]
    session["saved_prescriptions"] = saved
    save_session(user["user_id"], session)
    return {"ok": True, "success": True, "saved": saved}
