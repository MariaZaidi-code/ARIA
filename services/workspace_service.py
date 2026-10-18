"""ARIA workspace service: monitors, targets, glossary, alerts, integrations.

Per-user JSON storage under ``data/users/user_<id>/workspace/`` with atomic
writes (same pattern as ``reporting/digests.py``):

- ``monitors.json``     natural-language monitors evaluated on a cadence
- ``targets.json``      KPI targets shown against dashboard cards
- ``glossary.json``     business terms rewritten into canonical wording
- ``notifications.json`` in-app inbox (monitor triggers, digest events)
- ``webhooks.json``     named Slack/Teams/generic webhook URLs
- ``integrations.json`` inbound integration tokens (e.g. Slack command)

Everything here is best-effort and defensive: storage or delivery failures
are logged and recorded on the item, never raised into request handlers.
"""

from __future__ import annotations

import json
import ipaddress
import logging
import os
import re
import secrets
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger("aria.workspace")

MONITOR_CADENCES = ("manual", "hourly", "daily", "weekly")
MAX_ITEMS = 200
MAX_RUNS_KEPT = 20
MAX_NOTIFICATIONS = 100
MAX_SQL_LEN = 20000


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _users_dir() -> Path:
    try:
        from core.config import USERS_DIR as _d
        _d.mkdir(parents=True, exist_ok=True)
        return _d
    except Exception:
        d = Path("data") / "users"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _ws_dir(user_id: int) -> Path:
    d = _users_dir() / f"user_{user_id}" / "workspace"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(user_id: int, name: str) -> Path:
    return _ws_dir(user_id) / name


def _load(user_id: int, name: str, default: Any) -> Any:
    try:
        p = _path(user_id, name)
        if not p.exists():
            return default
        data = json.loads(p.read_text(encoding="utf-8"))
        return data
    except Exception as exc:
        log.warning("workspace: could not load %s for user=%s (%s)", name, user_id, exc)
        return default


def _save(user_id: int, name: str, data: Any) -> bool:
    try:
        path = _path(user_id, name)
        tmp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex[:8]}")
        tmp.write_text(json.dumps(data, default=str, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(path)
        try:
            # Carry integrations' private-file hardening over to every
            # workspace store (token files must be readable only by this
            # process/user: chmod on POSIX, DPAPI ACL guidance on Windows).
            from core.secret_box import ensure_private_file as _ensure_private

            _ensure_private(path)
        except Exception:
            pass
        if os.name != "nt":
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass
        return True
    except Exception as exc:
        log.warning("workspace: could not save %s for user=%s (%s)", name, user_id, exc)
        return False


def _load_list(user_id: int, name: str) -> list:
    data = _load(user_id, name, [])
    return data if isinstance(data, list) else []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_user_ids() -> list[int]:
    try:
        out = []
        for child in _users_dir().iterdir():
            if child.is_dir() and child.name.startswith("user_"):
                try:
                    out.append(int(child.name.split("user_")[1]))
                except Exception:
                    continue
        return out
    except Exception:
        return []


def _clean_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _clean_sql(sql: Any) -> str:
    return str(sql or "").strip()[:MAX_SQL_LEN]


def _safe_read_sql(sql: str) -> str:
    """Only read-only statements may be executed by the workspace engine."""
    s = _clean_sql(sql).rstrip(";").strip()
    if not s:
        raise ValueError("A read-only SELECT query is required.")
    # Use the shared SQL guard: a prefix check alone lets a data-modifying
    # CTE (WITH ... DELETE/UPDATE ... RETURNING ...) pass the old monitor
    # check even though the monitor engine executes the stored SQL directly.
    from core.validation import is_read_only_sql
    if not is_read_only_sql(s):
        raise ValueError("Only read-only SELECT statements can be monitored.")
    return s


def _run_sql(user_id: int, sql: str, limit: int = 5000) -> tuple[list[str], list[dict]]:
    """Execute a stored read-only statement against the user's connection."""
    from sqlalchemy import create_engine, text as sqlt
    from core.config import get_session
    session = get_session(user_id) or {}
    db_uri = session.get("db_uri")
    if not db_uri:
        raise RuntimeError("No data source connected for this user.")
    eng = create_engine(db_uri)
    try:
        with eng.connect() as conn:
            res = conn.execute(sqlt(_safe_read_sql(sql)))
            cols = [str(c) for c in (res.keys() or [])]
            rows = [dict(zip(cols, r)) for r in res.fetchmany(int(limit))]
        return cols, rows
    finally:
        try:
            eng.dispose()
        except Exception:
            pass


def _to_float(v: Any) -> float | None:
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _fmt_num(v: float | None) -> str:
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"{v / 1_000:.1f}K"
    if a >= 10:
        return f"{v:.0f}"
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _series(cols: list[str], rows: list[dict],
            measure_column: str | None = None,
            time_column: str | None = None) -> dict:
    """Latest/previous numeric points from a (possibly) ordered result."""
    if not rows or not cols:
        return {"measure": None, "time": None, "points": []}
    measure = measure_column if measure_column in cols else None
    if measure is None:
        for c in reversed(cols):
            vals = [_to_float(r.get(c)) for r in rows if r.get(c) is not None]
            if vals and all(v is not None for v in vals):
                measure = c
                break
    if measure is None:
        for c in cols:
            vals = [_to_float(r.get(c)) for r in rows if r.get(c) is not None]
            if vals:
                measure = c
                break
    time_col = time_column if time_column in cols else None
    if time_col is None:
        for c in cols:
            if c == measure:
                continue
            if all(_to_float(r.get(c)) is None for r in rows if r.get(c) is not None):
                time_col = c
                break
    points = []
    for r in rows:
        v = _to_float(r.get(measure)) if measure else None
        if v is None:
            continue
        points.append({
            "label": str(r.get(time_col)) if time_col else "",
            "value": v,
        })
    return {"measure": measure, "time": time_col, "points": points}


# ---------------------------------------------------------------------------
# Monitors
# ---------------------------------------------------------------------------

_FALL_RE = re.compile(
    r"\b(drop|drops|dropped|fall|falls|fell|decline|declines|declined|"
    r"decrease|decreases|decreased|dip|dips)\b[^%\d]{0,40}?"
    r"(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
_RISE_RE = re.compile(
    r"\b(rise|rises|rose|grow|grows|grew|growth|increase|increases|"
    r"increased|jump|jumps|jumped|gain|gains|gained|spike|spikes)\b"
    r"[^%\d]{0,40}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
_ABOVE_RE = re.compile(
    r"\b(above|over|greater than|exceeds?|hits?|reaches?)\b\s*\$?"
    r"([\d,]+(?:\.\d+)?)\s*([km])?", re.IGNORECASE)
_BELOW_RE = re.compile(
    r"\b(below|under|less than|dips? under)\b\s*\$?"
    r"([\d,]+(?:\.\d+)?)\s*([km])?", re.IGNORECASE)


def _scaled(value: str, suffix: str | None) -> float:
    v = float(str(value).replace(",", ""))
    if suffix:
        v *= 1000.0 if suffix.lower() == "k" else 1_000_000.0
    return v


def parse_monitor_text(text: str) -> dict:
    """Parse plain-English monitor text into a condition + cadence.

    Examples:
    - "tell me when revenue drops more than 10% week over week"
      -> drops_pct 10, weekly
    - "alert me if orders go above 5K" -> above 5000, daily (default)
    """
    t = str(text or "")
    cadence = "daily"
    if re.search(r"\b(hourly|every hour|each hour)\b", t, re.IGNORECASE):
        cadence = "hourly"
    elif re.search(r"\b(weekly|every week|each week|week over week|wow)\b", t, re.IGNORECASE):
        cadence = "weekly"
    condition: dict | None = None
    m = _FALL_RE.search(t)
    if m:
        condition = {"type": "drops_pct", "value": float(m.group(2))}
    else:
        m = _RISE_RE.search(t)
        if m:
            condition = {"type": "rises_pct", "value": float(m.group(2))}
        else:
            m = _ABOVE_RE.search(t)
            if m:
                condition = {"type": "above",
                             "value": _scaled(m.group(2), m.group(3))}
            else:
                m = _BELOW_RE.search(t)
                if m:
                    condition = {"type": "below",
                                 "value": _scaled(m.group(2), m.group(3))}
    return {"matched": condition is not None, "condition": condition,
            "cadence": cadence, "text": str(t)[:300]}


def list_monitors(user_id: int) -> list:
    return _load_list(user_id, "monitors.json")


def get_monitor(user_id: int, monitor_id: str) -> dict | None:
    for m in list_monitors(user_id):
        if str(m.get("id") or "") == str(monitor_id):
            return m
    return None


def create_monitor(user_id: int, data: dict) -> dict:
    data = data or {}
    question = _clean_text(data.get("question"), 500)
    sql = _clean_sql(data.get("sql"))
    condition = data.get("condition") if isinstance(data.get("condition"), dict) else None
    text = _clean_text(data.get("condition_text") or data.get("text"), 300)
    cadence = str(data.get("cadence") or "").lower()
    if condition is None and text:
        parsed = parse_monitor_text(text)
        condition = parsed.get("condition")
        if not cadence:
            cadence = parsed.get("cadence") or "daily"
    if condition is not None:
        ctype = str(condition.get("type") or "").lower()
        if ctype not in ("drops_pct", "rises_pct", "above", "below"):
            condition = None
        else:
            val = _to_float(condition.get("value"))
            if val is None:
                condition = None
            else:
                condition = {"type": ctype, "value": val}
    if condition is None:
        raise ValueError(
            "Could not understand the condition. Try 'drops 10%' or 'above 5000'.")
    if not sql:
        raise ValueError("A stored query is required to evaluate the monitor.")
    if cadence not in MONITOR_CADENCES:
        cadence = "daily"
    monitor = {
        "id": uuid.uuid4().hex[:12],
        "user_id": user_id,
        "name": _clean_text(data.get("name"), 120) or
                (_clean_text(question, 80) or "Monitor"),
        "question": question,
        "sql": sql,
        "condition": condition,
        "condition_text": text,
        "cadence": cadence,
        "enabled": bool(data.get("enabled", True)),
        "metric_label": _clean_text(data.get("metric_label"), 80),
        "measure_column": _clean_text(data.get("measure_column"), 120),
        "time_column": _clean_text(data.get("time_column"), 120),
        "webhook_id": _clean_text(data.get("webhook_id"), 40) or None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "last_check_at": None,
        "last_status": "never",
        "last_value": None,
        "last_prev_value": None,
        "last_message": None,
        "last_error": None,
        "run_count": 0,
        "runs": [],
    }
    items = list_monitors(user_id)
    if len(items) >= MAX_ITEMS:
        raise ValueError(f"At most {MAX_ITEMS} monitors.")
    items.append(monitor)
    _save(user_id, "monitors.json", items)
    return monitor


def patch_monitor(user_id: int, monitor_id: str, patch: dict) -> dict | None:
    patch = patch or {}
    items = list_monitors(user_id)
    for m in items:
        if str(m.get("id") or "") != str(monitor_id):
            continue
        if patch.get("enabled") is not None:
            m["enabled"] = bool(patch.get("enabled"))
        if patch.get("name") is not None:
            name = _clean_text(patch.get("name"), 120)
            if name:
                m["name"] = name
        if patch.get("cadence") is not None:
            c = str(patch.get("cadence")).lower()
            if c in MONITOR_CADENCES:
                m["cadence"] = c
        if patch.get("webhook_id") is not None:
            m["webhook_id"] = _clean_text(patch.get("webhook_id"), 40) or None
        if isinstance(patch.get("condition"), dict):
            ctype = str(patch["condition"].get("type") or "").lower()
            val = _to_float(patch["condition"].get("value"))
            if ctype in ("drops_pct", "rises_pct", "above", "below") and val is not None:
                m["condition"] = {"type": ctype, "value": val}
        m["updated_at"] = _now_iso()
        _save(user_id, "monitors.json", items)
        return m
    return None


def delete_monitor(user_id: int, monitor_id: str) -> bool:
    items = list_monitors(user_id)
    kept = [m for m in items if str(m.get("id") or "") != str(monitor_id)]
    if len(kept) < len(items):
        _save(user_id, "monitors.json", kept)
        return True
    return False


def _condition_met(condition: dict, cur: float, prev: float | None) -> tuple[bool, str | None]:
    ctype = str(condition.get("type") or "")
    val = _to_float(condition.get("value"))
    if val is None:
        return False, None
    if ctype == "drops_pct":
        if prev is None or prev == 0:
            return False, None
        pct = (cur - prev) / abs(prev) * 100.0
        return pct <= -abs(val), f"{pct:+.1f}% vs previous period"
    if ctype == "rises_pct":
        if prev is None or prev == 0:
            return False, None
        pct = (cur - prev) / abs(prev) * 100.0
        return pct >= abs(val), f"{pct:+.1f}% vs previous period"
    if ctype == "above":
        return cur > val, f"latest value {_fmt_num(cur)} vs threshold {_fmt_num(val)}"
    if ctype == "below":
        return cur < val, f"latest value {_fmt_num(cur)} vs threshold {_fmt_num(val)}"
    return False, None


def evaluate_monitor(user_id: int, monitor: dict, persist: bool = True) -> dict:
    """Run one monitor check. Records the run and notifies on trigger."""
    result: dict = {"ok": False, "triggered": False, "message": ""}
    try:
        cols, rows = _run_sql(user_id, monitor.get("sql") or "")
        series = _series(cols, rows, monitor.get("measure_column") or None,
                         monitor.get("time_column") or None)
        points = series.get("points") or []
        if not points:
            raise RuntimeError("The monitored query returned no numeric values.")
        cur = points[-1]["value"]
        prev = points[-2]["value"] if len(points) >= 2 else None
        triggered, detail = _condition_met(monitor.get("condition") or {}, cur, prev)
        label = points[-1].get("label") or ""
        metric = monitor.get("metric_label") or monitor.get("name") or "metric"
        name = monitor.get("name") or "Monitor"
        message = (
            f"{name}: {metric}"
            + (f" for {label}" if label else "")
            + f" is {_fmt_num(cur)}"
            + (f" ({detail})" if detail else "")
            + (" — condition met." if triggered else " — condition not met.")
        )
        result = {"ok": True, "triggered": triggered, "message": message,
                  "value": cur, "previous": prev, "label": label}
    except Exception as exc:
        result = {"ok": False, "triggered": False, "message": str(exc)[:300]}
    if persist:
        try:
            items = list_monitors(user_id)
            for m in items:
                if str(m.get("id") or "") != str(monitor.get("id") or ""):
                    continue
                entry = {
                    "at": _now_iso(),
                    "ok": bool(result.get("ok")),
                    "triggered": bool(result.get("triggered")),
                    "value": result.get("value"),
                    "message": _clean_text(result.get("message"), 400),
                }
                runs = list(m.get("runs") or [])
                runs.append(entry)
                m["runs"] = runs[-MAX_RUNS_KEPT:]
                m["run_count"] = int(m.get("run_count") or 0) + 1
                m["last_check_at"] = entry["at"]
                m["last_status"] = ("triggered" if result.get("triggered")
                                    else ("ok" if result.get("ok") else "failed"))
                m["last_message"] = entry["message"]
                m["last_error"] = None if result.get("ok") else entry["message"]
                if result.get("value") is not None:
                    m["last_value"] = result.get("value")
                if result.get("previous") is not None:
                    m["last_prev_value"] = result.get("previous")
                m["updated_at"] = _now_iso()
                _save(user_id, "monitors.json", items)
                if result.get("triggered") and result.get("ok"):
                    result["monitor"] = m
                    _notify_trigger(user_id, m, entry["message"])
                break
        except Exception as exc:
            log.warning("workspace: monitor bookkeeping failed (%s)", exc)
    return result


def _notify_trigger(user_id: int, monitor: dict, message: str) -> None:
    add_notification(user_id, {
        "kind": "monitor",
        "title": f"Monitor triggered: {monitor.get('name') or 'Monitor'}",
        "message": message,
        "meta": {"monitor_id": monitor.get("id")},
    })
    webhook_id = monitor.get("webhook_id")
    if webhook_id:
        for wh in list_webhooks(user_id):
            if str(wh.get("id") or "") == str(webhook_id):
                deliver_webhooks(user_id, f"ARIA monitor: {monitor.get('name')}",
                                 message, only_ids=[webhook_id])
                break


def check_monitor_now(user_id: int, monitor_id: str) -> dict:
    monitor = get_monitor(user_id, monitor_id)
    if not monitor:
        return {"ok": False, "detail": "Monitor not found."}
    return evaluate_monitor(user_id, monitor)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

def get_targets(user_id: int) -> list:
    return _load_list(user_id, "targets.json")


def set_targets(user_id: int, targets: list) -> list:
    cleaned: list[dict] = []
    for t in targets or []:
        if not isinstance(t, dict):
            continue
        metric = _clean_text(t.get("metric"), 120)
        value = _to_float(t.get("target"))
        if not metric or value is None:
            continue
        direction = str(t.get("direction") or "above").lower()
        if direction not in ("above", "below"):
            direction = "above"
        cleaned.append({
            "id": _clean_text(t.get("id"), 40) or uuid.uuid4().hex[:10],
            "metric": metric,
            "label": _clean_text(t.get("label"), 120) or metric,
            "target": value,
            "direction": direction,
            "note": _clean_text(t.get("note"), 200),
            "updated_at": _now_iso(),
        })
        if len(cleaned) >= 50:
            break
    _save(user_id, "targets.json", cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------

def get_glossary(user_id: int) -> list:
    return _load_list(user_id, "glossary.json")


def set_glossary(user_id: int, entries: list) -> list:
    cleaned: list[dict] = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        term = _clean_text(e.get("term"), 80)
        maps_to = _clean_text(e.get("maps_to"), 200)
        if not term or not maps_to:
            continue
        cleaned.append({
            "id": _clean_text(e.get("id"), 40) or uuid.uuid4().hex[:10],
            "term": term,
            "maps_to": maps_to,
            "note": _clean_text(e.get("note"), 200),
            "updated_at": _now_iso(),
        })
        if len(cleaned) >= 100:
            break
    _save(user_id, "glossary.json", cleaned)
    return cleaned


def apply_glossary(user_id: int, goal: str) -> tuple[str, list[str]]:
    """Rewrite business terms in a question to their canonical wording."""
    text = str(goal or "")
    entries = get_glossary(user_id)
    applied: list[str] = []
    if not entries or not text.strip():
        return text, applied
    # Longest terms first so overlapping phrases resolve deterministically.
    for e in sorted(entries, key=lambda x: -len(str(x.get("term") or ""))):
        term = str(e.get("term") or "").strip()
        maps_to = str(e.get("maps_to") or "").strip()
        if not term or not maps_to or term.lower() == maps_to.lower():
            continue
        pattern = re.compile(
            rf"(?<![\w]){re.escape(term)}(?![\w])", re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub(lambda _m: maps_to, text)
            applied.append(term)
    return text, applied


# ---------------------------------------------------------------------------
# Notifications (in-app inbox)
# ---------------------------------------------------------------------------

def list_notifications(user_id: int, unread_only: bool = False) -> list:
    items = _load_list(user_id, "notifications.json")
    if unread_only:
        items = [n for n in items if not n.get("read")]
    return items


def unread_count(user_id: int) -> int:
    return sum(1 for n in list_notifications(user_id) if not n.get("read"))


def add_notification(user_id: int, data: dict) -> dict:
    data = data or {}
    note = {
        "id": uuid.uuid4().hex[:12],
        "at": _now_iso(),
        "kind": _clean_text(data.get("kind"), 40) or "info",
        "title": _clean_text(data.get("title"), 160) or "Notification",
        "message": _clean_text(data.get("message"), 600),
        "meta": data.get("meta") if isinstance(data.get("meta"), dict) else {},
        "read": False,
    }
    items = _load_list(user_id, "notifications.json")
    items.append(note)
    _save(user_id, "notifications.json", items[-MAX_NOTIFICATIONS:])
    return note


def mark_notifications(user_id: int, ids: list | None = None,
                       all_items: bool = False) -> int:
    items = _load_list(user_id, "notifications.json")
    wanted = {str(i) for i in (ids or [])}
    changed = 0
    for n in items:
        if all_items or str(n.get("id") or "") in wanted:
            if not n.get("read"):
                n["read"] = True
                changed += 1
    if changed:
        _save(user_id, "notifications.json", items)
    return changed


def clear_notifications(user_id: int) -> None:
    _save(user_id, "notifications.json", [])


# ---------------------------------------------------------------------------
# Webhooks (Slack / Teams / generic outbound delivery)
# ---------------------------------------------------------------------------

def _webhook_kind(url: str) -> str:
    try:
        host = (urlsplit(str(url or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        host = ""
    if host == "hooks.slack.com":
        return "slack"
    if host == "webhook.office.com" or host.endswith(".webhook.office.com") \
            or host == "outlook.office.com" or host.endswith(".outlook.office.com"):
        return "teams"
    return "generic"


def _resolve_public_webhook_target(url: str) -> tuple[str, list[str]]:
    """Validate and resolve a webhook URL to public IPs for a pinned send.

    The validated IPs must be used for the connection itself; resolving the
    hostname again in an HTTP client would leave a DNS-rebinding race.
    """
    value = _clean_text(url, 500)
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in ("http", "https")
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment):
            raise ValueError
        host = parsed.hostname.rstrip(".")
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("Webhook URL must be a valid public HTTP or HTTPS URL.")
    if not value or len(value) > 500 or (port is not None and not 1 <= port <= 65535):
        raise ValueError("Webhook URL must be a valid public HTTP or HTTPS URL.")

    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
            addresses = [ipaddress.ip_address(info[4][0].split("%", 1)[0])
                         for info in infos]
        except (OSError, ValueError, IndexError):
            raise ValueError("Webhook host must resolve to a public address.")
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Webhook host must resolve only to public addresses.")
    return value, [str(address) for address in addresses]


def _validate_webhook_url(url: str) -> str:
    """Validate outbound webhook URLs and reject local/private addresses."""
    value, _addresses = _resolve_public_webhook_target(url)
    return value


def _pinned_webhook_adapter(hostname: str, port: int, address: str):
    """Build a requests adapter that connects to a validated IP directly."""
    # Delay importing requests until webhook delivery is actually used.
    from requests.adapters import HTTPAdapter

    class PinnedWebhookAdapter(HTTPAdapter):
        def build_connection_pool_key_attributes(self, request, verify, cert=None):
            host_params, pool_kwargs = super().build_connection_pool_key_attributes(
                request, verify, cert
            )
            host_params["host"] = address
            host_params["port"] = port
            if urlsplit(request.url).scheme.lower() == "https":
                # Connect to the pinned IP while retaining correct TLS SNI and
                # certificate-hostname verification for the URL host.
                pool_kwargs["server_hostname"] = hostname
                pool_kwargs["assert_hostname"] = hostname
            return host_params, pool_kwargs

    return PinnedWebhookAdapter()


def list_webhooks(user_id: int) -> list:
    return _load_list(user_id, "webhooks.json")


def create_webhook(user_id: int, data: dict) -> dict:
    data = data or {}
    url = _validate_webhook_url(data.get("url"))
    items = list_webhooks(user_id)
    if len(items) >= 20:
        raise ValueError("At most 20 webhooks.")
    wh = {
        "id": uuid.uuid4().hex[:12],
        "name": _clean_text(data.get("name"), 80) or "Webhook",
        "url": url,
        "kind": _webhook_kind(url),
        "created_at": _now_iso(),
        "last_status": "never",
        "last_error": None,
    }
    items.append(wh)
    _save(user_id, "webhooks.json", items)
    return wh


def delete_webhook(user_id: int, webhook_id: str) -> bool:
    items = list_webhooks(user_id)
    kept = [w for w in items if str(w.get("id") or "") != str(webhook_id)]
    if len(kept) < len(items):
        _save(user_id, "webhooks.json", kept)
        return True
    return False


def _webhook_payload(kind: str, title: str, text: str) -> dict:
    if kind == "slack":
        return {"text": f"*{title}*\n{text}"}
    if kind == "teams":
        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": title,
            "title": title,
            "text": text,
        }
    return {"source": "aria", "title": title, "text": text}


def deliver_webhooks(user_id: int, title: str, text: str,
                     only_ids: list | None = None) -> list[dict]:
    """Best-effort delivery to this user's webhooks. Never raises."""
    import requests
    wanted = {str(i) for i in (only_ids or [])}
    outcomes: list[dict] = []
    items = list_webhooks(user_id)
    for wh in items:
        if wanted and str(wh.get("id") or "") not in wanted:
            continue
        status, error = "ok", None
        try:
            # Revalidate at send time so webhook URLs saved before the SSRF
            # guard was introduced cannot target private services.
            target, addresses = _resolve_public_webhook_target(
                str(wh.get("url") or "")
            )
            parsed = urlsplit(target)
            hostname = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
            pinned_ip = addresses[0]
            host_header = f"[{hostname}]" if ":" in hostname else hostname
            if parsed.port is not None:
                host_header = f"{host_header}:{parsed.port}"
            with requests.Session() as session:
                # Do not permit environment proxy settings to redirect this
                # pinned connection through an unvalidated proxy endpoint.
                session.trust_env = False
                session.mount(
                    f"{parsed.scheme.lower()}://",
                    _pinned_webhook_adapter(hostname, port, pinned_ip),
                )
                resp = session.post(
                    target,
                    json=_webhook_payload(str(wh.get("kind") or "generic"),
                                          title, text),
                    headers={"Host": host_header},
                    timeout=8,
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    if resp.status_code >= 400:
                        status, error = "failed", f"HTTP {resp.status_code}"
                finally:
                    resp.close()
        except Exception as exc:
            status, error = "failed", str(exc)[:200]
        outcomes.append({"id": wh.get("id"), "status": status, "error": error})
        wh["last_status"] = status
        wh["last_error"] = error
        wh["last_used_at"] = _now_iso()
    if outcomes:
        _save(user_id, "webhooks.json", items)
    return outcomes


def send_webhook_test(user_id: int, webhook_id: str) -> dict:
    wh = next((w for w in list_webhooks(user_id)
               if str(w.get("id") or "") == str(webhook_id)), None)
    if not wh:
        return {"ok": False, "detail": "Webhook not found."}
    outcomes = deliver_webhooks(user_id, "ARIA test message",
                                "This is a test from ARIA — delivery works.",
                                only_ids=[webhook_id])
    ok = bool(outcomes) and outcomes[0].get("status") == "ok"
    return {"ok": ok, "detail": (outcomes[0].get("error") if outcomes else None),
            "outcome": outcomes[0] if outcomes else None}


# ---------------------------------------------------------------------------
# Integrations (inbound tokens, e.g. Slack slash command)
# ---------------------------------------------------------------------------

# Slack token at rest is DPAPI-encrypted ("enc1:"). Legacy plaintext files
# still resolve: decrypt() passes non-prefixed values through and the next
# regeneration rewrites them encrypted. Index is digest-keyed (token hashes,
# never raw values) for the per-command hot path.
def _wrap_slack_secret(token: str) -> str:
    try:
        from core.secret_box import encrypt as _enc

        return _enc(token)
    except Exception:
        return token


def _unwrap_slack_secret(stored: str | None) -> str:
    stored = str(stored or "")
    if not stored:
        return ""
    try:
        from core.secret_box import decrypt as _dec

        return _dec(stored)
    except Exception:
        return stored


def _load_integrations(user_id: int) -> dict:
    data = _load(user_id, "integrations.json", {})
    return data if isinstance(data, dict) else {}


def get_integrations(user_id: int, reveal: bool = False) -> dict:
    data = _load_integrations(user_id)
    token = _unwrap_slack_secret(data.get("slack_command_token"))
    if reveal:
        try:
            # Rewrite legacy plaintext at rest as an explicit reveal-readup.
            stored_raw = str(data.get("slack_command_token") or "")
            if stored_raw and not stored_raw.startswith("enc1:"):
                data["slack_command_token"] = _wrap_slack_secret(token)
                _save(user_id, "integrations.json", data)
                try:
                    _index_slack_token(token, user_id)
                except Exception:
                    pass
        except Exception:
            pass
# Never emit the token inside the command URL unless this is an explicit
    # reveal (set/regenerate). A status GET must not leak the secret into
    # response bodies, browser history, or proxy/access logs.
    url = ""
    if token:
        url = "/api/integrations/slack/command"
        if reveal:
            url += "?token=" + token
    return {
        "slack_command_token": token if reveal else (token[:6] + "..." if token else ""),
        "slack_configured": bool(token),
        "slack_command_url": url,
    }


def set_integrations(user_id: int, patch: dict) -> dict:
    patch = patch or {}
    data = _load_integrations(user_id)
    _old_token = str(data.get("slack_command_token") or "")
    if patch.get("regenerate_slack_token") or patch.get("clear_slack_token"):
        data.pop("slack_command_token", None)
    if patch.get("regenerate_slack_token") or patch.get("slack_command_token"):
        data["slack_command_token"] = _wrap_slack_secret(
            secrets.token_urlsafe(24))
    saved = _save(user_id, "integrations.json", data)
    try:
        # Digest-keyed index: hot path for every Slack command (no O(users)
        # file scan per request).
        import hashlib as _hash
        stale = _hash.sha256(_unwrap_slack_secret(_old_token).encode()).hexdigest()
        _SLACK_INDEX.pop(stale, None)
        new_token = _unwrap_slack_secret(data.get("slack_command_token"))
        if new_token:
            _SLACK_INDEX[_hash.sha256(new_token.encode()).hexdigest()] = int(user_id)
    except Exception:
        pass
    return get_integrations(user_id, reveal=True)


_SLACK_INDEX: dict[str, int] = {}

def _index_slack_token(token: str, user_id: int) -> None:
    import hashlib as _hash
    if token:
        _SLACK_INDEX[_hash.sha256(token.encode()).hexdigest()] = int(user_id)


def resolve_user_by_slack_token(token: str) -> int | None:
    token = str(token or "")
    if not token:
        return None
    import hashlib as _hash
    digest = None
    try:
        digest = _hash.sha256(str(token).encode()).hexdigest()
    except Exception:
        digest = None
    try:
        if digest and digest in _SLACK_INDEX:
            return _SLACK_INDEX[digest]
    except Exception:
        pass
    # Index miss (cold or another worker): full scan, then warm the index.
    for uid in _iter_user_ids():
        try:
            data = _load_integrations(uid)
            stored = str(data.get("slack_command_token") or "")
            if stored:
                stored_plain = _unwrap_slack_secret(stored)
                if stored_plain:
                    try:
                        _index_slack_token(stored_plain, uid)
                    except Exception:
                        pass
                if stored_plain and secrets.compare_digest(stored_plain, token):
                    return uid
        except Exception:
            continue
    return None
