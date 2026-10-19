"""Inbound integrations API: Slack slash command -> ARIA ask.

Flow: a Slack slash command posts the user's text plus the workspace token
(configured under Settings -> Workspace -> Slack). The token resolves the
ARIA user, a short-lived session token is minted for that user, and the
question is answered through the exact same ``/api/ask`` pipeline the app
uses — the bot can never see or compute anything the user couldn't see
themselves, and no analytics logic is duplicated here.

Slack requires a fast ack: when Slack supplies a ``response_url`` the route
returns an ephemeral "running" ack immediately and posts the answer to the
response URL from a background thread. Without a response_url (tests, other
callers) the answer is returned synchronously.
"""

from __future__ import annotations

import logging
import os
import threading
from html import escape as _escape

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

log = logging.getLogger("aria.integrations")

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

_ASK_TIMEOUT = 120
_MAX_TEXT = 3500
_SLACK_RESPONSE_PREFIX = "https://hooks.slack.com/"


def _base_url() -> str:
    env = os.getenv("ARIA_BASE_URL")
    if env:
        return env.rstrip("/")
    try:
        port = int(os.getenv("ARIA_PORT", "8000"))
    except (TypeError, ValueError):
        port = 8000
    return f"http://127.0.0.1:{port}"


def _mint_token(user_id: int) -> str:
    import auth
    username = ""
    try:
        conn = auth._get_db()
        try:
            row = conn.execute("SELECT username FROM users WHERE id = ?",
                               (int(user_id),)).fetchone()
            if row:
                username = str(row["username"] or "")
        finally:
            conn.close()
    except Exception:
        username = ""
    # 5-minute credential: a loopback token that never enters revocation
    # state must be worthless long before anyone could harvest it (Slack
    # logs, webhook payload dumps). auth.issue_token accepts fractional
    # day TTLs.
    return auth.issue_token(int(user_id), username or f"user_{user_id}",
                            ttl_days=5 / 1440)


# Bounded ask concurrency: each command can hold a threadpool worker for up
# to _ASK_TIMEOUT seconds; an unbounded burst of commands against one leaked
# workspace token would otherwise multiply threads / LLM spend and starve
# the shared threadpool other async routes use.
_ASK_CONCURRENCY = 3
_ASK_SEMAPHORE = threading.BoundedSemaphore(_ASK_CONCURRENCY)


def _summarize(body: dict, question: str) -> str:
    def _s(key: str) -> str:
        v = body.get(key)
        return str(v).strip() if isinstance(v, str) else ""

    answer = _s("answer") or _s("message") or _s("summary") or _s("story")
    if not answer:
        detail = _s("detail") or "ARIA returned no summary."
        answer = detail
    if len(answer) > _MAX_TEXT:
        answer = answer[: _MAX_TEXT - 1].rstrip() + "…"
    lines = [f"*{_escape(question)}*", f"> {answer}"]
    why = body.get("why")
    if isinstance(why, dict):
        what = str(why.get("what_happened") or "").strip()
        if what and what != answer:
            lines.append(f"> _Why: {what[:400]}_")
    sql_used = _s("sql_used")
    confidence = _s("confidence")
    if confidence:
        lines.append(f"_Confidence: {confidence}_")
    del sql_used  # shown only in-app; never leak raw SQL to Slack by default
    return "\n".join(lines)


def _slack_shape(text: str, in_channel: bool = True) -> dict:
    return {"response_type": "in_channel" if in_channel else "ephemeral",
            "text": text}


def _ask_sync(user_id: int, question: str) -> str:
    """Answer through /api/ask and return Slack mrkdwn text."""
    import requests
    try:
        resp = requests.post(
            f"{_base_url()}/api/ask",
            json={"goal": question},
            headers={"Authorization": f"Bearer {_mint_token(user_id)}",
                     "X-Client-Type": "integration"},
            timeout=_ASK_TIMEOUT,
        )
        if resp.status_code != 200:
            return f":warning: ARIA returned HTTP {resp.status_code} for that question."
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        return _summarize(body, question)
    except Exception as exc:
        log.warning("integrations: slack ask failed (%s)", exc)
        return ":warning: ARIA could not be reached to answer that question."


def _post_later(response_url: str, text: str) -> None:
    import requests
    try:
        requests.post(response_url, json=_slack_shape(text), timeout=15)
    except Exception as exc:
        log.warning("integrations: slack delayed post failed (%s)", exc)


@router.post("/slack/command")
async def slack_command(request: Request):
    """Slack slash-command endpoint; accept the workspace token in POST body only.

    Configure in Slack with URL ``{base}/api/integrations/slack/command`` and
    send the workspace token in Slack's ``token`` form field.
    """
    from services.workspace_service import resolve_user_by_slack_token

    form = {}
    try:
        form = dict(await request.form())
    except Exception:
        form = {}
    token = str(form.get("token") or "").strip()
    user_id = resolve_user_by_slack_token(token)
    if not user_id:
        raise HTTPException(status_code=401,
                            detail="Invalid or missing integration token.")

    text = str(form.get("text") or "").strip()[:500]
    response_url = str(form.get("response_url") or "").strip()

    if not text:
        return JSONResponse(_slack_shape(
            "Ask ARIA a data question, e.g. `/aria why did revenue drop last month`",
            in_channel=False))

    # Slack expects a <3s ack; defer through response_url when available.
    if response_url.startswith(_SLACK_RESPONSE_PREFIX):
        def _worker() -> None:
            if _ASK_SEMAPHORE.acquire(blocking=False):
                try:
                    _post_later(response_url, _ask_sync(user_id, text))
                finally:
                    _ASK_SEMAPHORE.release()
            else:
                _post_later(response_url, _slack_shape(
                    ":warning: ARIA is busy answering other questions — try "
                    "again in a moment.", in_channel=False))
        threading.Thread(target=_worker, name="aria-slack-ask", daemon=True).start()
        return JSONResponse(_slack_shape(":hourglass_flowing_sand: Running your question in ARIA…", in_channel=False))

    # Off the event loop: _ask_sync blocks on a loopback POST to this same
    # server, which cannot be served while the loop is blocked here.
    acquired = False
    try:
        acquired = _ASK_SEMAPHORE.acquire(blocking=False)
        if not acquired:
            return JSONResponse(_slack_shape(
                ":warning: ARIA is busy answering other questions — try "
                "again in a moment.", in_channel=False))
        answer = await run_in_threadpool(_ask_sync, user_id, text)
    finally:
        if acquired:
            _ASK_SEMAPHORE.release()
    return JSONResponse(_slack_shape(answer))
