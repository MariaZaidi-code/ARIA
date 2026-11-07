"""Per-user document upload jobs with stage-level progress.

Ingestion stays synchronous inside one worker thread (the per-user mutation
lock in ``PDFIngestion`` already serialises writes); this module only adds an
observable job record around it so the UI can show per-file progress for a
multi-file upload. Job state is process-local and intentionally ephemeral:
the manifest remains the source of truth for documents, so a restart loses
in-flight progress but never a committed document.
"""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

# Ordered stages; the percentage is what the UI renders for a running stage.
STAGES = {
    "queued": 0,
    "validating": 10,
    "extracting": 35,
    "indexing": 70,
    "saving": 90,
    "ready": 100,
    "failed": 100,
}
TERMINAL = {"ready", "failed"}

MAX_BATCH_FILES = int(os.getenv("ARIA_RAG_MAX_BATCH_FILES", "10"))
_MAX_JOBS_PER_USER = 100
_WORKERS = int(os.getenv("ARIA_RAG_UPLOAD_WORKERS", "2"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UploadJobRegistry:
    def __init__(self, workers: int = _WORKERS):
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, dict]] = {}
        self._futures: dict[str, Future] = {}
        self._executor = ThreadPoolExecutor(max_workers=max(1, workers),
                                            thread_name_prefix="aria-doc-upload")

    def create(self, user_id, *, filename: str, size_bytes: int, batch_id: str | None = None) -> dict:
        job = {
            "job_id": uuid.uuid4().hex,
            "batch_id": batch_id,
            "filename": filename,
            "size_bytes": int(size_bytes),
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "error": None,
            "duplicate": False,
            "document": None,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        with self._lock:
            jobs = self._jobs.setdefault(str(user_id), {})
            jobs[job["job_id"]] = job
            self._prune(jobs)
            return dict(job)

    def _prune(self, jobs: dict[str, dict]) -> None:
        # Drop the oldest finished jobs first; running jobs are never evicted.
        overflow = len(jobs) - _MAX_JOBS_PER_USER
        if overflow <= 0:
            return
        finished = sorted((j for j in jobs.values() if j["status"] in TERMINAL),
                          key=lambda j: j["updated_at"])
        for job in finished[:overflow]:
            jobs.pop(job["job_id"], None)
            self._futures.pop(job["job_id"], None)

    def update(self, user_id, job_id: str, **fields) -> dict | None:
        with self._lock:
            job = self._jobs.get(str(user_id), {}).get(job_id)
            if job is None:
                return None
            stage = fields.get("stage")
            if stage:
                fields.setdefault("progress", STAGES.get(stage, job["progress"]))
                fields.setdefault("status", stage if stage in TERMINAL else "processing")
            job.update(fields, updated_at=_utc_now())
            return dict(job)

    def fail(self, user_id, job_id: str, message: str) -> dict | None:
        return self.update(user_id, job_id, stage="failed", error=message)

    def get(self, user_id, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(str(user_id), {}).get(job_id)
            return dict(job) if job else None

    def list(self, user_id, *, batch_id: str | None = None) -> list[dict]:
        with self._lock:
            jobs = [dict(j) for j in self._jobs.get(str(user_id), {}).values()
                    if batch_id is None or j.get("batch_id") == batch_id]
        jobs.sort(key=lambda j: j["created_at"], reverse=True)
        return jobs

    def submit(self, user_id, job_id: str, work: Callable[[Callable[[str], None]], dict],
               *, on_error: Callable[[BaseException], str], cleanup: Callable[[], None] | None = None) -> None:
        """Run ``work(progress)`` in the pool; it returns the ingestion result."""

        def progress(stage: str) -> None:
            self.update(user_id, job_id, stage=stage)

        def run() -> None:
            try:
                result = work(progress) or {}
                self.update(user_id, job_id, stage="ready",
                            duplicate=bool(result.get("duplicate")),
                            document=result.get("document"))
            except BaseException as exc:  # noqa: BLE001 - every failure must end the job
                self.fail(user_id, job_id, on_error(exc))
            finally:
                if cleanup is not None:
                    try:
                        cleanup()
                    except Exception:
                        pass

        future = self._executor.submit(run)
        with self._lock:
            self._futures[job_id] = future

    def wait(self, job_id: str, timeout: float | None = None) -> None:
        """Block until a submitted job finishes (used by tests and shutdown)."""
        with self._lock:
            future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)


UPLOAD_JOBS = UploadJobRegistry()
