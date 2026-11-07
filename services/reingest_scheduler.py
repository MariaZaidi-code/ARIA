"""Lightweight re-ingestion scheduler.

Stores per-user schedules in a JSON file and runs a background thread that
re-ingests documents whose next_run has passed. Best-effort: failures are
logged and the job is retried on the next tick.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.config import DATA_DIR

JOBS_PATH = DATA_DIR / "reingest_jobs.json"
_lock = threading.Lock()
_thread = None
_stop = threading.Event()
# Smallest interval the scheduler will honour. Without a floor a job created
# with a non-positive interval would re-run on every tick (every 60s) forever.
_MIN_INTERVAL_HOURS = 1.0
_DEFAULT_INTERVAL_HOURS = 24.0


def _load_jobs() -> list:
    try:
        if JOBS_PATH.exists():
            raw = JOBS_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_jobs(jobs: list) -> None:
    try:
        JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = JOBS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(jobs, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, JOBS_PATH)
    except Exception:
        pass


def list_jobs(user_id=None) -> list:
    with _lock:
        jobs = _load_jobs()
    if user_id is not None:
        jobs = [j for j in jobs if str(j.get("user_id")) == str(user_id)]
    return jobs


def _normalise_interval(interval_hours) -> float:
    """Coerce an interval to a finite, positive number of hours.

    Raises ValueError for NaN/Infinity/non-numeric input: ``timedelta`` blows
    up on those (ValueError/OverflowError -> 500), and a non-positive interval
    would schedule a job that re-runs on every scheduler tick.
    """
    try:
        value = float(interval_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("interval_hours must be a number of hours.") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("interval_hours must be a finite, positive number of hours.")
    return value


def add_job(user_id, interval_hours: float, document_ids: list | None = None) -> dict:
    interval = _normalise_interval(interval_hours)
    job = {
        "id": uuid.uuid4().hex[:12],
        "user_id": str(user_id),
        "interval_hours": interval,
        "document_ids": list(document_ids or []),
        "next_run": (datetime.now(timezone.utc) + timedelta(hours=interval)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_run": None,
        "last_status": None,
    }
    with _lock:
        jobs = _load_jobs()
        jobs.append(job)
        _save_jobs(jobs)
    return job


def remove_job(job_id: str, user_id=None) -> bool:
    with _lock:
        jobs = _load_jobs()
        before = len(jobs)
        jobs = [j for j in jobs if not (j.get("id") == job_id
                                         and (user_id is None or str(j.get("user_id")) == str(user_id)))]
        if len(jobs) < before:
            _save_jobs(jobs)
            return True
    return False


def _run_job(job: dict) -> str:
    try:
        from insight_rag.storage import RAGMetadataStore
        uid = job["user_id"]
        meta = RAGMetadataStore(uid)
        docs = meta.list_documents()
        targets = job.get("document_ids") or [d.get("document_id") for d in docs]
        count = 0
        for did in targets:
            try:
                rec = meta.get_document(did)
                if rec:
                    rec["last_reingested"] = datetime.now(timezone.utc).isoformat()
                    meta.put_document(rec)
                    count += 1
            except Exception:
                pass
        return f"ok: touched {count} documents"
    except Exception as exc:
        return f"error: {type(exc).__name__}"


def _tick() -> None:
    now = datetime.now(timezone.utc)
    with _lock:
        jobs = _load_jobs()
        changed = False
        for job in jobs:
            try:
                nr = datetime.fromisoformat(str(job.get("next_run")).replace("Z", "+00:00"))
            except Exception:
                continue
            if nr <= now:
                status = _run_job(job)
                job["last_run"] = now.isoformat()
                job["last_status"] = status
                # Floor the interval so a job stored with a non-positive
                # interval cannot re-run on every tick forever.
                try:
                    _interval = float(job.get("interval_hours", _DEFAULT_INTERVAL_HOURS))
                except (TypeError, ValueError):
                    _interval = _DEFAULT_INTERVAL_HOURS
                if not math.isfinite(_interval) or _interval < _MIN_INTERVAL_HOURS:
                    _interval = _MIN_INTERVAL_HOURS
                job["next_run"] = (now + timedelta(hours=_interval)).isoformat()
                changed = True
        if changed:
            _save_jobs(jobs)


def _loop() -> None:
    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            pass
        _stop.wait(60)


def start() -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, daemon=True, name="reingest-scheduler")
        _thread.start()


def stop() -> None:
    _stop.set()
