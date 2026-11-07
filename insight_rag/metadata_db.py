"""PostgreSQL document metadata, stored in the same database as the pgvector index.

One row per (user, document). Indexed columns (filename, sha256, status,
source_type, share_token, created_at) are copied out of the record for
lookups; the full record stays in ``record`` (JSONB) so new metadata fields
need no schema change. Chunk JSON and the original PDF bytes remain on disk.

Schema changes are versioned migrations applied once per process under a
PostgreSQL advisory lock, so several workers starting together cannot race.
A user's legacy ``manifest.json`` is imported on first access (idempotent,
``ON CONFLICT DO NOTHING``) and kept as ``manifest.json.migrated``.

Errors are never swallowed: every database failure surfaces as a
``RuntimeError`` with a client-safe message (the DSN is never included).
"""

from __future__ import annotations

import atexit
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

_TABLE = "aria_rag_documents"
_MIGRATIONS_TABLE = "aria_rag_schema_migrations"
_IMPORTS_TABLE = "aria_rag_manifest_imports"
_ADVISORY_LOCK_KEY = 0x41524941  # "ARIA"

# (version, description, statements). Append only; never edit an applied entry.
MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "document metadata table", [
        f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
            user_key     VARCHAR(64)  NOT NULL,
            document_id  VARCHAR(80)  NOT NULL,
            filename     TEXT         NOT NULL DEFAULT '',
            sha256       VARCHAR(64),
            status       VARCHAR(32)  NOT NULL DEFAULT 'ready',
            source_type  VARCHAR(16)  NOT NULL DEFAULT 'pdf',
            share_token  VARCHAR(128),
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            record       JSONB        NOT NULL,
            PRIMARY KEY (user_key, document_id)
        )""",
        f"CREATE INDEX IF NOT EXISTS {_TABLE}_sha256_idx ON {_TABLE} (user_key, sha256)",
        f"CREATE INDEX IF NOT EXISTS {_TABLE}_created_idx ON {_TABLE} (user_key, created_at DESC)",
        f"CREATE INDEX IF NOT EXISTS {_TABLE}_share_idx ON {_TABLE} (share_token) "
        "WHERE share_token IS NOT NULL",
        f"CREATE INDEX IF NOT EXISTS {_TABLE}_shared_with_idx ON {_TABLE} "
        "USING GIN ((record -> 'shared_with'))",
        f"""CREATE TABLE IF NOT EXISTS {_IMPORTS_TABLE} (
            user_key        VARCHAR(64) PRIMARY KEY,
            imported_count  INTEGER     NOT NULL,
            imported_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
    ]),
]

_UNAVAILABLE = "The document metadata database is unavailable. Check ARIA_RAG_DATABASE_URL and retry."

_LOCK = threading.RLock()
_ENGINES: dict[str, object] = {}
_MIGRATED: set[str] = set()
_IMPORTED: set[tuple[str, str]] = set()


def _engine(url: str):
    """Process-wide pooled engine per URL, migrated before first use."""
    with _LOCK:
        engine = _ENGINES.get(url)
        if engine is None:
            from sqlalchemy import create_engine

            from .storage import _psycopg_url

            engine = create_engine(
                _psycopg_url(url),
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=5,
                connect_args={"connect_timeout": int(os.getenv("ARIA_RAG_DB_CONNECT_TIMEOUT", "5"))},
            )
            _ENGINES[url] = engine
        if url not in _MIGRATED:
            try:
                apply_migrations(engine)
            except Exception as exc:
                raise RuntimeError(_UNAVAILABLE) from exc
            _MIGRATED.add(url)
        return engine


@atexit.register
def dispose_engines() -> None:
    with _LOCK:
        for engine in _ENGINES.values():
            engine.dispose()
        _ENGINES.clear()
        _MIGRATED.clear()
        _IMPORTED.clear()


def apply_migrations(engine) -> list[int]:
    """Apply pending migrations in one transaction; returns the versions applied."""
    from sqlalchemy import text

    applied: list[int] = []
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        conn.execute(text(
            f"""CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} (
                version     INTEGER     PRIMARY KEY,
                description TEXT        NOT NULL,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""))
        done = {row[0] for row in conn.execute(text(f"SELECT version FROM {_MIGRATIONS_TABLE}"))}
        for version, description, statements in MIGRATIONS:
            if version in done:
                continue
            for statement in statements:
                conn.execute(text(statement))
            conn.execute(text(f"INSERT INTO {_MIGRATIONS_TABLE} (version, description) VALUES (:v, :d)"),
                         {"v": version, "d": description})
            applied.append(version)
    return applied


def _timestamp(value) -> datetime:
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _row_params(user_key: str, record: dict) -> dict:
    # PostgreSQL JSONB rejects NUL characters; they carry no meaning in metadata.
    payload = json.dumps(record, ensure_ascii=False, default=str).replace("\\u0000", "")
    return {
        "user_key": user_key,
        "document_id": str(record["document_id"]),
        "filename": str(record.get("filename") or ""),
        "sha256": record.get("sha256"),
        "status": str(record.get("status") or "ready")[:32],
        "source_type": str(record.get("source_type") or "pdf")[:16],
        "share_token": record.get("share_token") or None,
        "created_at": _timestamp(record.get("created_at")),
        "record": payload,
    }


_UPSERT = f"""
    INSERT INTO {_TABLE} (user_key, document_id, filename, sha256, status, source_type,
                          share_token, created_at, updated_at, record)
    VALUES (:user_key, :document_id, :filename, :sha256, :status, :source_type,
            :share_token, :created_at, now(), CAST(:record AS JSONB))
    ON CONFLICT (user_key, document_id) DO UPDATE SET
        filename = EXCLUDED.filename, sha256 = EXCLUDED.sha256, status = EXCLUDED.status,
        source_type = EXCLUDED.source_type, share_token = EXCLUDED.share_token,
        updated_at = now(), record = EXCLUDED.record
"""

_INSERT_IF_ABSENT = f"""
    INSERT INTO {_TABLE} (user_key, document_id, filename, sha256, status, source_type,
                          share_token, created_at, updated_at, record)
    VALUES (:user_key, :document_id, :filename, :sha256, :status, :source_type,
            :share_token, :created_at, now(), CAST(:record AS JSONB))
    ON CONFLICT (user_key, document_id) DO NOTHING
"""


def _record(value) -> dict:
    return value if isinstance(value, dict) else json.loads(value)


class PostgresDocumentMetadata:
    """Document metadata rows for one user (isolation key = ``user_key``)."""

    def __init__(self, user_key: str, url: str):
        self.user_key = user_key
        self.url = url

    def _run(self, statement: str, params: dict | None = None, *, write: bool = False):
        from sqlalchemy import text

        engine = _engine(self.url)
        try:
            if write:
                with engine.begin() as conn:
                    result = conn.execute(text(statement), params or {})
                    return result.fetchall() if result.returns_rows else None
            with engine.connect() as conn:
                return conn.execute(text(statement), params or {}).fetchall()
        except Exception as exc:
            raise RuntimeError(_UNAVAILABLE) from exc

    def list(self) -> list[dict]:
        rows = self._run(
            f"SELECT record FROM {_TABLE} WHERE user_key = :u ORDER BY created_at DESC, document_id",
            {"u": self.user_key})
        return [_record(row[0]) for row in rows]

    def get(self, document_id: str) -> dict | None:
        rows = self._run(f"SELECT record FROM {_TABLE} WHERE user_key = :u AND document_id = :d",
                         {"u": self.user_key, "d": str(document_id)})
        return _record(rows[0][0]) if rows else None

    def find_by_sha256(self, digest: str) -> dict | None:
        rows = self._run(
            f"SELECT record FROM {_TABLE} WHERE user_key = :u AND sha256 = :s "
            "ORDER BY created_at DESC LIMIT 1",
            {"u": self.user_key, "s": str(digest)})
        return _record(rows[0][0]) if rows else None

    def put(self, record: dict) -> None:
        self._run(_UPSERT, _row_params(self.user_key, record), write=True)

    def remove(self, document_id: str) -> dict | None:
        rows = self._run(
            f"DELETE FROM {_TABLE} WHERE user_key = :u AND document_id = :d RETURNING record",
            {"u": self.user_key, "d": str(document_id)}, write=True)
        return _record(rows[0][0]) if rows else None

    def replace_all(self, records: list[dict]) -> None:
        """Make the user's rows exactly ``records`` in one transaction."""
        from sqlalchemy import text

        engine = _engine(self.url)
        try:
            with engine.begin() as conn:
                conn.execute(text(f"DELETE FROM {_TABLE} WHERE user_key = :u"), {"u": self.user_key})
                for record in records:
                    conn.execute(text(_UPSERT), _row_params(self.user_key, record))
        except Exception as exc:
            raise RuntimeError(_UNAVAILABLE) from exc

    def import_manifest(self, manifest_path: Path, read_json) -> int:
        """Copy a legacy manifest.json into the table once, then keep it as a backup.

        Rows already in the table win (``DO NOTHING``), so a crash between the
        commit and the rename simply re-runs as a no-op on the next access.
        A corrupt manifest raises instead of being skipped silently.
        """
        key = (self.url, self.user_key)
        if key in _IMPORTED:
            return 0
        if not manifest_path.exists():
            _IMPORTED.add(key)
            return 0
        from sqlalchemy import text

        with FileLock(str(manifest_path) + ".lock", timeout=30):
            if not manifest_path.exists():
                _IMPORTED.add(key)
                return 0
            documents = (read_json(manifest_path, {"documents": {}}) or {}).get("documents") or {}
            records = [r for r in documents.values() if isinstance(r, dict) and r.get("document_id")]
            engine = _engine(self.url)
            try:
                with engine.begin() as conn:
                    for record in records:
                        conn.execute(text(_INSERT_IF_ABSENT), _row_params(self.user_key, record))
                    conn.execute(text(
                        f"""INSERT INTO {_IMPORTS_TABLE} (user_key, imported_count) VALUES (:u, :n)
                            ON CONFLICT (user_key) DO UPDATE SET
                                imported_count = EXCLUDED.imported_count, imported_at = now()"""),
                        {"u": self.user_key, "n": len(records)})
            except Exception as exc:
                raise RuntimeError(_UNAVAILABLE) from exc
            os.replace(manifest_path, manifest_path.with_name("manifest.json.migrated"))
        _IMPORTED.add(key)
        return len(records)

    # ── Cross-user lookups (sharing) ────────────────────────────────────
    @classmethod
    def find_share_token(cls, url: str, token: str) -> tuple[str, dict] | None:
        rows = cls("", url)._run(
            f"SELECT user_key, record FROM {_TABLE} WHERE share_token = :t LIMIT 1", {"t": str(token)})
        return (rows[0][0], _record(rows[0][1])) if rows else None

    @classmethod
    def shared_with(cls, url: str, username: str) -> list[dict]:
        rows = cls("", url)._run(
            f"SELECT record FROM {_TABLE} "
            "WHERE (record -> 'shared_with') @> jsonb_build_array(CAST(:name AS TEXT)) "
            "ORDER BY created_at DESC",
            {"name": str(username)})
        return [_record(row[0]) for row in rows]
