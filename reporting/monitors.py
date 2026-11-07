"""ARIA background monitors (NL alerting).

Per-user monitors stored by ``services.workspace_service`` are evaluated on a
cadence by a dependency-free background scheduler (threading + timer), the
same pattern used by ``reporting/digests.py``:

- every evaluation re-runs the monitor's stored read-only SQL (no LLM),
- the numeric series is compared against the parsed condition,
- triggers write an in-app notification and deliver to the monitor's linked
  webhook (Slack/Teams/generic) when one is configured.

Threading model: one daemon thread, 60s poll, ``threading.Event`` for graceful
shutdown + ``atexit`` hook. Startup is lazy (``ensure_started`` is called from
the workspace API routes) so no app wiring is needed.
"""

from __future__ import annotations

import atexit
import logging
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger("aria.monitors")

POLL_SECONDS = 60
_LOCAL_USER_ID_FALLBACK = None  # reserved; monitors are always per-user

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_started = False

_INTERVALS = {
    "hourly": 3600,
    "daily": 24 * 3600,
    "weekly": 7 * 24 * 3600,
}


def _due(monitor: dict, now_ts: float) -> bool:
    try:
        if not monitor.get("enabled"):
            return False
        cadence = str(monitor.get("cadence") or "daily").lower()
        interval = _INTERVALS.get(cadence)
        if not interval:
            return False  # manual cadence: only checked on demand
        last = monitor.get("last_check_at")
        if not last:
            return True  # newly created / never checked -> check on next tick
        try:
            last_dt = datetime.fromisoformat(str(last))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            last_ts = last_dt.timestamp()
        except Exception:
            return True
        return (now_ts - last_ts) >= interval
    except Exception:
        return False


def _tick() -> None:
    from services import workspace_service as ws
    now_ts = time.time()
    for uid in ws._iter_user_ids():
        try:
            monitors = ws.list_monitors(uid)
        except Exception:
            continue
        for monitor in monitors:
            try:
                if _due(monitor, now_ts):
                    log.info("monitors: scheduled check user=%s monitor=%s cadence=%s",
                             uid, monitor.get("id"), monitor.get("cadence"))
                    ws.evaluate_monitor(uid, monitor)
            except Exception as exc:
                # Never crash the scheduler; failures are recorded on the
                # monitor itself inside evaluate_monitor.
                log.warning("monitors: tick error user=%s (%s)", uid, exc)


def _loop() -> None:
    log.info("monitors: scheduler started (poll=%ss)", POLL_SECONDS)
    while not _stop_event.wait(POLL_SECONDS):
        try:
            _tick()
        except Exception as exc:
            log.warning("monitors: scheduler tick failed (%s)", exc)
    log.info("monitors: scheduler stopped")


def ensure_started() -> bool:
    """Start the background scheduler once (idempotent, lazy)."""
    global _thread, _started
    with _lock:
        if _started and _thread is not None and _thread.is_alive():
            return True
        _stop_event.clear()
        _thread = threading.Thread(target=_loop, name="aria-monitors",
                                   daemon=True)
        try:
            _thread.start()
            _started = True
            log.info("monitors: scheduler ensure_started ok")
            return True
        except Exception as exc:
            log.warning("monitors: scheduler failed to start (%s)", exc)
            return False


def stop() -> None:
    """Graceful shutdown: signal the loop and join briefly."""
    global _started
    try:
        _stop_event.set()
        t = _thread
        if t is not None and t.is_alive():
            t.join(timeout=5)
    except Exception:
        pass
    finally:
        _started = False


atexit.register(stop)
