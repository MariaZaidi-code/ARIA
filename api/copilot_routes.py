"""Copilot route — RAG over the connected database, provider-independent.

The LLM execution backend (Ollama local / Groq cloud) is whatever the session
already selected; this route never branches on it. All retrieval, SQL,
validation and response logic lives in the `copilot` package so the SAME
Copilot runs on either provider.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.deps import get_current_user
from core.config import get_session

log = logging.getLogger("aria.copilot")

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class CopilotRequest(BaseModel):
    question: str
    conversation_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None


def _load_schema_mapping(session: dict) -> dict:
    """Read the session's schema mapping JSON (written at connect time)."""
    schema_path = session.get("schema_path")
    if not schema_path:
        return {}
    try:
        p = Path(str(schema_path))
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Copilot could not read schema mapping: %s", exc)
    return {}


def _suggest_questions(mapping: dict, session: dict | None = None) -> list[str]:
    """Build 4 runnable questions from the connected schema (never generic).

    Each suggestion references a real measure/dimension/date from the
    mapping, so every one can actually be answered. When a session is
    provided, candidate measures are verified against real data (a text
    column mislabeled numeric must never drive suggestions). Falls back
    gracefully when parts are missing.
    """
    from api.schema_intel import SchemaIntelligence
    try:
        intel = SchemaIntelligence(mapping or {})
        tables = [t for t in (mapping or {}).get("tables", {}) if t]
        if not tables:
            return []

        def _numeric_measure(t):
            try:
                m = intel.find_best_measure(t)
                if m and m in (intel.get_numeric_cols(t) or []):
                    if session is not None and not _measure_holds_data(session, t, m):
                        return None
                    return m
            except Exception:
                pass
            return None

        # Prefer the first table with a genuinely numeric measure; a text
        # column mislabeled as a measure must never drive suggestions.
        table = tables[0]
        measure = _numeric_measure(table)
        for t in tables:
            m = _numeric_measure(t)
            if m:
                table, measure = t, m
                break
        dim = intel.find_best_dimension(table)
        date = intel.find_best_datetime(table)
        other_dim = None
        try:
            for c in (intel.get_text_cols(table) or []):
                if c != dim:
                    other_dim = c
                    break
        except Exception:
            pass
        out: list[str] = []
        if measure:
            out.append(f"What is the total {measure.replace('_', ' ')}?")
        else:
            out.append(f"How many records are in {table.replace('_', ' ')}?")
        if measure and dim:
            out.append(f"Which {dim.replace('_', ' ')} has the highest {measure.replace('_', ' ')}?")
        elif dim:
            out.append(f"Show the breakdown by {dim.replace('_', ' ')}.")
        else:
            out.append(f"Summarize {table.replace('_', ' ')}.")
        if measure and date:
            out.append(f"How has {measure.replace('_', ' ')} changed over time?")
        elif measure and (other_dim or dim):
            out.append(f"Show {measure.replace('_', ' ')} by {(other_dim or dim).replace('_', ' ')}.")
        else:
            out.append(f"What are the top {table.replace('_', ' ')} records?")
        if measure and dim and date:
            out.append(f"Compare {measure.replace('_', ' ')} across {dim.replace('_', ' ')} over time.")
        elif measure:
            out.append(f"What is the average {measure.replace('_', ' ')}?")
        else:
            out.append(f"Describe {table.replace('_', ' ')}.")
        seen, clean = set(), []
        for q in out:
            if q not in seen:
                seen.add(q)
                clean.append(q)
        return clean[:4]
    except Exception as exc:
        log.info("Copilot suggestions failed (%s).", exc)
        return []


def _measure_holds_data(session: dict, table: str, column: str, sample: int = 20) -> bool:
    """Verify a candidate measure holds numbers in the live source.

    Never raises; verification failure means "skip this candidate".
    SQLite/CSV sources read directly; relational sources go through a
    short-lived engine built from the session (password stays server-side).
    """
    try:
        from api.schema_intel import _safe_name
        from sqlalchemy import create_engine as _mk, text as _t
        db_type = session.get("db_type", "postgresql")
        dialect = session.get("dialect", db_type)
        uri = None
        if db_type == "sqlite":
            raw = session.get("db_uri") or ""
            uri = raw if str(raw).startswith("sqlite:") else f"sqlite:///{raw}"
        elif db_type in ("postgresql", "mysql"):
            cfg = dict(session.get("db") or {})
            if not cfg.get("host"):
                return True
            from core.secret_box import decrypt as _dec
            pwd = cfg.get("password")
            if isinstance(pwd, str) and pwd.startswith("enc1:"):
                pwd = _dec(pwd)
            if db_type == "mysql":
                from urllib.parse import quote_plus as _qp
                uri = (f"mysql+pymysql://{_qp(str(cfg.get('user', '')))}:{_qp(str(pwd))}"
                       f"@{cfg.get('host')}:{cfg.get('port', 3306)}/{cfg.get('db', '')}")
            else:
                from urllib.parse import quote_plus as _qp2
                uri = (f"postgresql+psycopg2://{_qp2(str(cfg.get('user', '')))}:{_qp2(str(pwd))}"
                       f"@{cfg.get('host')}:{cfg.get('port', 5432)}/{cfg.get('db', '')}")
        else:
            return True
        eng = _mk(uri, pool_pre_ping=True, connect_args={"connect_timeout": 8})
        try:
            with eng.connect() as conn:
                rows = conn.execute(_t(
                    f"SELECT {_safe_name(column, dialect)} "
                    f"FROM {_safe_name(table, dialect)} LIMIT {int(sample)}")).fetchall()
        finally:
            eng.dispose()
        vals = [r[0] for r in rows]
        if not vals:
            return False
        good = 0
        for v in vals:
            if isinstance(v, bool):
                continue
            try:
                float(str(v).replace(",", ""))
                good += 1
            except (TypeError, ValueError):
                continue
        return good >= max(1, len(vals) // 2)
    except Exception as exc:
        log.info("Copilot suggestion measure check skipped (%s).", type(exc).__name__)
        return True


@router.get("/suggestions")
async def copilot_suggestions(user: dict = Depends(get_current_user)):
    """4 data-driven starter questions for the connected source."""
    session = get_session(user["user_id"])
    mapping = _load_schema_mapping(session)
    suggestions = _suggest_questions(mapping, session=session)
    if not suggestions:
        suggestions = [
            "What are the main metrics in this dataset?",
            "Show me a summary of the data",
            "Which categories have the most records?",
            "What trends do you see in the data?",
        ]
    return {"ok": True, "suggestions": suggestions}


def _linked_context(session: dict) -> dict:
    """Rebuild queryable context for a stashed linked database (§7).

    The linked db config carries an encrypted password; decrypt it here and
    rebuild the URI + mapping in memory only (never persisted, never logged).
    Returns {} when no linked database exists.
    """
    linked = session.get("linked_db") or {}
    if not isinstance(linked, dict):
        return {}
    cfg = linked.get("db") or {}
    if not isinstance(cfg, dict):
        return {}
    uri = linked.get("db_uri") or ""
    db_type = linked.get("db_type", "postgresql")
    # File-based sqlite links stash their URI directly (no secret in it).
    if not uri and db_type == "sqlite":
        return {}
    if not uri:
        if not cfg.get("host"):
            return {}
        try:
            from core.secret_box import decrypt as _dec
            from core.db import build_db_uri
            password = cfg.get("password")
            if isinstance(password, str) and password.startswith("enc1:"):
                password = _dec(password)
            plain = dict(cfg, password=password)
            uri = build_db_uri(plain, db_type)
        except Exception as exc:
            log.info("Copilot linked-DB URI rebuild failed (%s).", type(exc).__name__)
            return {}
    mapping: dict = {}
    spath = linked.get("schema_path")
    try:
        if spath and Path(str(spath)).exists():
            mapping = json.loads(Path(str(spath)).read_text(encoding="utf-8"))
    except Exception as exc:
        log.info("Copilot linked-DB mapping unreadable (%s).", type(exc).__name__)
    if not mapping.get("tables"):
        return {}
    return {"db_uri": uri, "dialect": linked.get("dialect", db_type),
            "db_name": linked.get("db_name"), "mapping": mapping}


@router.post("")
async def copilot_endpoint(body: CopilotRequest, user: dict = Depends(get_current_user)):
    """Answer an analytical question over the connected source via RAG."""
    session = get_session(user["user_id"])
    provider = session.get("provider")
    if not provider:
        raise HTTPException(
            status_code=400,
            detail="No LLM provider configured. Connect a source first (POST /api/connect).",
        )
    if not session.get("db_uri"):
        raise HTTPException(
            status_code=400,
            detail="No queryable source connected. Connect a PostgreSQL/MySQL database "
                   "or upload a CSV/PDF first.",
        )

    mapping = _load_schema_mapping(session)
    # Intent-aware gating (t.txt §14): schema-less intents must not be
    # blocked by the relational mapping check. Document questions need only
    # a connected document; schema/general questions need no mapping at all.
    from copilot.intent import COMBINED as _COMBINED_I, DOCUMENT as _DOCUMENT_I
    from copilot.intent import GENERAL as _GENERAL_I, SCHEMA as _SCHEMA_I, classify as _classify
    _route = _classify(body.question or "")
    _needs_mapping = _route.intent not in (_DOCUMENT_I, _COMBINED_I, _GENERAL_I, _SCHEMA_I)
    if _needs_mapping and not mapping.get("tables"):
        return {
            "ok": False,
            "answer": ("The schema for this connection is not available yet. "
                       "Reconnect or use Rescan Schema on the Data page, then try again."),
        }

    dialect = session.get("dialect", session.get("db_type", "postgresql"))

    # Embedder is local-first and never required for the pipeline to work.
    try:
        from copilot import create_embedder, create_pipeline
        embedder = create_embedder()
    except Exception as exc:
        log.info("Copilot embedder unavailable (%s); lexical retrieval only.", exc)
        embedder = None
        from copilot import create_pipeline

    try:
        pipeline = create_pipeline(
            llm=provider,
            schema_mapping=mapping,
            db_uri=session["db_uri"],
            dialect=dialect,
            user_id=user["user_id"],
            embedder=embedder,
            provider_name=session.get("provider_name"),
            document_id=session.get("document_id"),
            linked=_linked_context(session),
        )
        # pipeline.ask is blocking (SQL + LLM I/O); offload so the event
        # loop stays responsive under concurrent requests.
        result = await asyncio.to_thread(pipeline.ask, body.question)
    except Exception as exc:
        from core.errors import sanitize_error as _san
        log.exception("Copilot pipeline failed")
        return {
            "ok": False,
            "answer": ("I hit an internal error while analysing that question. "
                       "Please try again or rephrase it."),
            "error": _san(exc)[:300],
        }

    payload = result.to_public()
    payload["provider"] = session.get("provider_name")
    return payload