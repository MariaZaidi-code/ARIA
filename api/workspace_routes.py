"""Workspace API: monitors, targets, glossary, inbox, alerts, integrations.

All state lives per-user via ``services.workspace_service`` (JSON under
``data/users/user_<id>/workspace/``). Writes require a writable session so
the mobile read-only invariant is preserved; reads stay on get_current_user.
Monitor SQL is always re-validated as read-only before execution.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from core.deps import get_current_user, require_writable

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def _ws():
    from services import workspace_service as _w
    try:
        from reporting import monitors as _m
        _m.ensure_started()
    except Exception:
        pass
    return _w


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class MonitorCreate(BaseModel):
    model_config = ConfigDict(extra="allow")
    question: str | None = None
    name: str | None = None
    sql: str | None = None
    condition: dict | None = None
    condition_text: str | None = None
    cadence: str | None = None
    metric_label: str | None = None
    measure_column: str | None = None
    time_column: str | None = None
    webhook_id: str | None = None

    model_config = ConfigDict(extra="allow")


class MonitorPatch(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    enabled: bool | None = None
    cadence: str | None = None
    condition: dict | None = None
    webhook_id: str | None = None

    model_config = ConfigDict(extra="allow")


class MonitorPreview(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str = ""

    model_config = ConfigDict(extra="allow")


class TargetsPut(BaseModel):
    model_config = ConfigDict(extra="allow")
    targets: list[dict] = []

    model_config = ConfigDict(extra="allow")


class GlossaryPut(BaseModel):
    model_config = ConfigDict(extra="allow")
    entries: list[dict] = []

    model_config = ConfigDict(extra="allow")


class NotificationsRead(BaseModel):
    model_config = ConfigDict(extra="allow")
    ids: list[str] = []
    all: bool = False

    model_config = ConfigDict(extra="allow")


class WebhookCreate(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    url: str

    model_config = ConfigDict(extra="allow")


class IntegrationsPatch(BaseModel):
    model_config = ConfigDict(extra="allow")
    regenerate_slack_token: bool = False
    clear_slack_token: bool = False

    model_config = ConfigDict(extra="allow")


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Monitors
# ---------------------------------------------------------------------------

@router.get("/monitors")
def list_monitors(request: Request, user: dict = Depends(get_current_user)):
    """List this user's monitors with last-check status."""
    items = _ws().list_monitors(user["user_id"])
    return {"ok": True, "items": items, "data": items, "total": len(items)}


@router.post("/monitors/preview")
def preview_monitor(req: MonitorPreview, request: Request,
                    user: dict = Depends(get_current_user)):
    """Parse plain-English monitor text into a condition + cadence (no save)."""
    parsed = _ws().parse_monitor_text(req.text)
    return {"ok": True, **parsed}


@router.post("/monitors")
def create_monitor(req: MonitorCreate, request: Request,
                   user: dict = Depends(require_writable)):
    """Create a monitor (condition given or parsed from condition_text)."""
    try:
        item = _ws().create_monitor(user["user_id"], req.model_dump())
    except ValueError as exc:
        raise _bad_request(exc)
    return {"ok": True, "item": item, "data": item}


@router.patch("/monitors/{monitor_id}")
def patch_monitor(monitor_id: str, req: MonitorPatch, request: Request,
                  user: dict = Depends(require_writable)):
    """Enable/disable, rename, retarget a monitor or change its cadence."""
    updated = _ws().patch_monitor(user["user_id"], monitor_id,
                                  req.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Monitor not found.")
    return {"ok": True, "item": updated, "data": updated}


@router.delete("/monitors/{monitor_id}")
def delete_monitor(monitor_id: str, request: Request,
                   user: dict = Depends(require_writable)):
    """Delete a monitor."""
    if not _ws().delete_monitor(user["user_id"], monitor_id):
        raise HTTPException(status_code=404, detail="Monitor not found.")
    return {"ok": True}


@router.post("/monitors/{monitor_id}/check")
def check_monitor(monitor_id: str, request: Request,
                  user: dict = Depends(require_writable)):
    """Evaluate a monitor now (re-runs its stored read-only query)."""
    result = _ws().check_monitor_now(user["user_id"], monitor_id)
    if not result.get("ok") and result.get("detail") == "Monitor not found.":
        raise HTTPException(status_code=404, detail="Monitor not found.")
    return result


# ---------------------------------------------------------------------------
# KPI targets
# ---------------------------------------------------------------------------

@router.get("/targets")
def get_targets(request: Request, user: dict = Depends(get_current_user)):
    """List KPI targets (matched to dashboard cards by label)."""
    items = _ws().get_targets(user["user_id"])
    return {"ok": True, "items": items, "data": items, "total": len(items)}


@router.put("/targets")
def put_targets(req: TargetsPut, request: Request,
                user: dict = Depends(require_writable)):
    """Replace the target set (bulk save from the editor)."""
    items = _ws().set_targets(user["user_id"], req.targets)
    return {"ok": True, "items": items, "data": items, "total": len(items)}


# ---------------------------------------------------------------------------
# Business glossary
# ---------------------------------------------------------------------------

@router.get("/glossary")
def get_glossary(request: Request, user: dict = Depends(get_current_user)):
    """List glossary entries (term -> canonical wording)."""
    items = _ws().get_glossary(user["user_id"])
    return {"ok": True, "items": items, "data": items, "total": len(items)}


@router.put("/glossary")
def put_glossary(req: GlossaryPut, request: Request,
                 user: dict = Depends(require_writable)):
    """Replace the glossary (bulk save from the editor)."""
    items = _ws().set_glossary(user["user_id"], req.entries)
    return {"ok": True, "items": items, "data": items, "total": len(items)}


# ---------------------------------------------------------------------------
# Notification inbox
# ---------------------------------------------------------------------------

@router.get("/notifications")
def list_notifications(request: Request, unread_only: bool = False,
                       user: dict = Depends(get_current_user)):
    """List in-app notifications (monitor triggers, deliveries)."""
    w = _ws()
    items = w.list_notifications(user["user_id"], unread_only=bool(unread_only))
    return {"ok": True, "items": items, "data": items, "total": len(items),
            "unread": w.unread_count(user["user_id"])}


@router.post("/notifications/read")
def mark_notifications(req: NotificationsRead, request: Request,
                       user: dict = Depends(require_writable)):
    """Mark notifications read (ids or all)."""
    changed = _ws().mark_notifications(user["user_id"], req.ids, all_items=bool(req.all))
    return {"ok": True, "changed": changed,
            "unread": _ws().unread_count(user["user_id"])}


@router.delete("/notifications")
def clear_notifications(request: Request,
                        user: dict = Depends(require_writable)):
    """Clear the notification inbox."""
    _ws().clear_notifications(user["user_id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Webhooks (outbound Slack/Teams/generic)
# ---------------------------------------------------------------------------

@router.get("/webhooks")
def list_webhooks(request: Request, user: dict = Depends(get_current_user)):
    """List outbound webhooks with last delivery status."""
    items = _ws().list_webhooks(user["user_id"])
    return {"ok": True, "items": items, "data": items, "total": len(items)}


def _validate_webhook_url(url: str) -> None:
    from urllib.parse import urlparse
    import ipaddress
    import socket
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=400, detail="Webhook URL is required.")
    parts = urlparse(url.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise HTTPException(status_code=400, detail="Webhook URL must be an http(s) URL.")
    # Outbound webhooks should not target private/loopback/link-local hosts (SSRF guard).
    host = parts.hostname.strip().lower().rstrip(".")
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise HTTPException(status_code=400, detail="Webhook URL host is not allowed.")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(status_code=400, detail="Webhook URL host is not allowed.")
    except ValueError:
        # hostname, not IP — resolve and check
        try:
            infos = socket.getaddrinfo(host, None)
        except Exception:
            raise HTTPException(status_code=400, detail="Webhook URL host could not be resolved.")
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise HTTPException(status_code=400, detail="Webhook URL host is not allowed.")
    # Require https for non-loopback in production; allow http only for tests/local.
    if parts.scheme != "https":
        # Permit http only for explicit local/dev hosts.
        if host not in {"localhost", "127.0.0.1"}:
            raise HTTPException(status_code=400, detail="Webhook URL must use https://.")


@router.post("/webhooks")
def create_webhook(req: WebhookCreate, request: Request,
                   user: dict = Depends(require_writable)):
    """Register an outbound webhook URL."""
    _validate_webhook_url(req.url)
    try:
        item = _ws().create_webhook(user["user_id"], req.model_dump())
    except ValueError as exc:
        raise _bad_request(exc)
    return {"ok": True, "item": item, "data": item}


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(webhook_id: str, request: Request,
                   user: dict = Depends(require_writable)):
    """Delete a webhook."""
    if not _ws().delete_webhook(user["user_id"], webhook_id):
        raise HTTPException(status_code=404, detail="Webhook not found.")
    return {"ok": True}


@router.post("/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: str, request: Request,
                 user: dict = Depends(require_writable)):
    """Send a test payload to one webhook (result reported, never raised)."""
    result = _ws().send_webhook_test(user["user_id"], webhook_id)
    if result.get("detail") == "Webhook not found." and not result.get("ok"):
        raise HTTPException(status_code=404, detail="Webhook not found.")
    return result


# ---------------------------------------------------------------------------
# Integrations (inbound tokens)
# ---------------------------------------------------------------------------

@router.get("/integrations")
def get_integrations(request: Request, user: dict = Depends(get_current_user)):
    """Integration status (Slack command token stays masked)."""
    return {"ok": True, "data": _ws().get_integrations(user["user_id"])}


@router.post("/integrations")
def set_integrations(req: IntegrationsPatch, request: Request,
                     user: dict = Depends(require_writable)):
    """Regenerate/clear the Slack command token (returned once, in full)."""
    data = _ws().set_integrations(user["user_id"], req.model_dump())
    return {"ok": True, "data": data}
