"""Copilot route — RAG over the connected database, provider-independent.

The LLM execution backend (Ollama local / Groq cloud) is whatever the session
already selected; this route never branches on it. All retrieval, SQL,
validation and response logic lives in the `copilot` package so the SAME
Copilot runs on either provider.
"""

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
    if not mapping.get("tables"):
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
        )
        result = pipeline.ask(body.question)
    except Exception as exc:
        log.exception("Copilot pipeline failed")
        return {
            "ok": False,
            "answer": ("I hit an internal error while analysing that question. "
                       "Please try again or rephrase it."),
            "error": str(exc)[:300],
        }

    payload = result.to_public()
    payload["provider"] = session.get("provider_name")
    return payload