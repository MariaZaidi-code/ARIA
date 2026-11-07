"""Persistent PDF metadata, conversation history, and LangChain PGVector access.

Document metadata lives in PostgreSQL (``metadata_db``, same database as the
vectors) whenever ``ARIA_RAG_DATABASE_URL`` is set, otherwise in a per-user
``manifest.json``; ``ARIA_RAG_METADATA_BACKEND`` overrides the choice.

Consistency contract: the vector index (PGVector), the metadata rows and the
filesystem (chunk JSON + PDF bytes) are separate stores with no distributed
transaction. Callers (see ``InsightPDFRAG._ingest_pdf``) own the
write-then-commit order and must roll both back together on any failure,
failing loudly (raise, never report partial as healthy). Helpers here never
swallow errors: read/write/delete failures raise so partial state cannot
look healthy.
"""

from __future__ import annotations

import json
import os
import re
import threading
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.documents import Document
from filelock import FileLock

from . import config as _config
from .config import (
    RAG_COLLECTION_PREFIX,
    RAG_DATABASE_URL,
    RAG_VECTOR_STORE_CACHE_MAX,
    user_dir,
    user_key,
)
from .embeddings import FastBGEEmbeddings

_LOCK = threading.RLock()
# Bounded per-user LRU (isolation key stays user-only). Insertion order is
# recency order: an entry is re-inserted on every hit, so the first key is
# always the least-recently-used one. The lock is the module's existing lock
# (already held for manifest access), so cache and metadata stay consistent.
_VECTOR_STORE_CACHE: dict[str, object] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Stored RAG data could not be read; restore it before retrying.") from exc


def _atomic_write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    _replaced = False
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as handle:
            temp = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _replaced = True
    finally:
        if temp is not None and not _replaced:
            temp.unlink(missing_ok=True)


def metadata_backend_name() -> str:
    """Resolved metadata backend: ``"postgres"`` or ``"file"``."""
    choice = _config.RAG_METADATA_BACKEND
    if choice in ("file", "postgres"):
        return choice
    return "postgres" if _config.RAG_DATABASE_URL else "file"


def _postgres_metadata(key: str):
    from .metadata_db import PostgresDocumentMetadata

    if not _config.RAG_DATABASE_URL:
        raise RuntimeError("ARIA_RAG_METADATA_BACKEND=postgres requires ARIA_RAG_DATABASE_URL.")
    return PostgresDocumentMetadata(key, _config.RAG_DATABASE_URL)


class RAGMetadataStore:
    def __init__(self, user_id: str | int):
        self.user_id = str(user_id)
        self.root = user_dir(user_id)
        self.manifest_path = self.root / "manifest.json"
        self.backend = metadata_backend_name()
        self._db = None
        if self.backend == "postgres":
            self._db = _postgres_metadata(user_key(user_id))
            self._db.import_manifest(self.manifest_path, _read_json)

    def mutation_lock(self):
        return FileLock(str(self.root / "mutation.lock"), timeout=30)

    def load_manifest(self) -> dict:
        if self._db is not None:
            return {"documents": {doc["document_id"]: doc for doc in self._db.list()}}
        with _LOCK:
            return _read_json(self.manifest_path, {"documents": {}})

    def save_manifest(self, manifest: dict) -> None:
        if self._db is not None:
            self._db.replace_all(list((manifest.get("documents") or {}).values()))
            return
        with _LOCK:
            _atomic_write(self.manifest_path, manifest)

    def list_documents(self) -> list[dict]:
        if self._db is not None:
            return self._db.list()
        docs = list(self.load_manifest().get("documents", {}).values())
        docs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return docs

    def get_document(self, document_id: str) -> dict | None:
        if self._db is not None:
            return self._db.get(document_id)
        return self.load_manifest().get("documents", {}).get(document_id)

    def find_by_sha256(self, digest: str) -> dict | None:
        if self._db is not None:
            return self._db.find_by_sha256(digest)
        for doc in self.list_documents():
            if doc.get("sha256") == digest:
                return doc
        return None

    def put_document(self, metadata: dict) -> None:
        if self._db is not None:
            self._db.put(metadata)
            return
        with FileLock(str(self.manifest_path) + ".lock", timeout=30):
            manifest = self.load_manifest()
            manifest.setdefault("documents", {})[metadata["document_id"]] = metadata
            self.save_manifest(manifest)

    def remove_document(self, document_id: str) -> dict | None:
        if self._db is not None:
            return self._db.remove(document_id)
        with FileLock(str(self.manifest_path) + ".lock", timeout=30):
            manifest = self.load_manifest()
            removed = manifest.setdefault("documents", {}).pop(document_id, None)
            self.save_manifest(manifest)
            return removed

    def chunks_path(self, document_id: str) -> Path:
        ConversationStore._safe_id(document_id)
        return self.root / "chunks" / f"{document_id}.json"

    def save_chunks(self, document_id: str, documents: list[Document]) -> None:
        payload = [
            {"page_content": doc.page_content, "metadata": doc.metadata}
            for doc in documents
        ]
        _atomic_write(self.chunks_path(document_id), payload)

    def load_chunks(self, document_id: str) -> list[Document]:
        payload = _read_json(self.chunks_path(document_id), [])
        result = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            content = item.get("page_content")
            metadata = item.get("metadata")
            if isinstance(content, str) and isinstance(metadata, dict):
                result.append(Document(page_content=content, metadata=metadata))
        return result

    def document_file_path(self, document_id: str) -> Path:
        ConversationStore._safe_id(document_id)
        return self.root / "documents" / f"{document_id}.pdf"


def _legacy_manifests():
    """Yield (owner_dir, manifest) for every user with a manifest.json (file backend)."""
    base = _config.RAG_USERS_DIR
    if not base.exists():
        return
    for owner_dir in base.iterdir():
        manifest_path = owner_dir / "manifest.json"
        if not owner_dir.is_dir() or not manifest_path.exists():
            continue
        try:
            yield owner_dir, json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # one unreadable manifest must not hide every other share


def find_shared_document(token: str) -> tuple[Path, dict] | None:
    """Locate a document by its public share token across all users.

    Returns ``(owner_dir, record)``; ``owner_dir`` holds the owner's chunk
    files. Expiry is the caller's decision.
    """
    if not token:
        return None
    if metadata_backend_name() == "postgres":
        from .metadata_db import PostgresDocumentMetadata

        found = PostgresDocumentMetadata.find_share_token(_config.RAG_DATABASE_URL, token)
        return (_config.RAG_USERS_DIR / found[0], found[1]) if found else None
    for owner_dir, manifest in _legacy_manifests():
        for record in (manifest.get("documents") or {}).values():
            if record.get("share_token") == token:
                return owner_dir, record
    return None


def documents_shared_with(username: str) -> list[dict]:
    """Records other users shared with ``username`` (raw; callers strip private keys)."""
    if not username:
        return []
    if metadata_backend_name() == "postgres":
        from .metadata_db import PostgresDocumentMetadata

        return PostgresDocumentMetadata.shared_with(_config.RAG_DATABASE_URL, username)
    return [record
            for _owner_dir, manifest in _legacy_manifests()
            for record in (manifest.get("documents") or {}).values()
            if username in (record.get("shared_with") or [])]


def _conversation_title(question: str, limit: int = 80) -> str:
    text = " ".join(str(question or "").split())
    if len(text) <= limit:
        return text or "New chat"
    return text[:limit].rsplit(" ", 1)[0] + "…"


class ConversationStore:
    """Small persistent conversation store with optional per-turn context metadata."""

    def __init__(self, user_id: str | int):
        self.root = user_dir(user_id) / "conversations"

    @staticmethod
    def _safe_id(conversation_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", conversation_id or ""):
            raise ValueError("Invalid conversation id.")
        return conversation_id

    def _path(self, conversation_id: str) -> Path:
        return self.root / f"{self._safe_id(conversation_id)}.json"

    def load(self, conversation_id: str) -> dict:
        return _read_json(
            self._path(conversation_id),
            {"conversation_id": conversation_id, "created_at": _utc_now(), "messages": []},
        )

    def load_recent(self, conversation_id: str, limit: int = 80) -> dict:
        payload = self.load(conversation_id)
        return {**payload, "messages": payload.get("messages", [])[-max(1, limit):]}

    def turn_lock(self, conversation_id: str):
        return FileLock(str(self._path(conversation_id)) + ".turn.lock", timeout=30)

    def append_turn(self, conversation_id: str, *, question: str, answer: str,
                    sources: list[dict], user_metadata: dict, assistant_metadata: dict) -> None:
        """Commit a complete pair atomically while preserving the full transcript."""
        path = self._path(conversation_id)
        with FileLock(str(path) + ".write.lock", timeout=30):
            payload = self.load(conversation_id)
            messages = payload.setdefault("messages", [])
            for role, content, evidence, metadata in (
                ("user", question, [], user_metadata),
                ("assistant", answer, sources, assistant_metadata),
            ):
                messages.append({"role": role, "content": content, "sources": evidence,
                                 "metadata": metadata, "created_at": _utc_now()})
            payload.setdefault("title", _conversation_title(question))
            payload["updated_at"] = _utc_now()
            _atomic_write(path, payload)

    def exists(self, conversation_id: str) -> bool:
        return self._path(conversation_id).exists()

    def update_meta(self, conversation_id: str, *, scope_document_ids=None, set_scope: bool = False,
                    title: str | None = None) -> None:
        """Record session-level metadata (title, document scope) on an existing file.

        ``scope_document_ids`` is the user's explicit selection for this chat;
        ``None`` means "all of my documents". Older files without these fields
        stay valid: readers treat missing keys as "no saved scope".
        """
        path = self._path(conversation_id)
        if not path.exists():
            return
        with FileLock(str(path) + ".write.lock", timeout=30):
            payload = self.load(conversation_id)
            if set_scope:
                payload["scope_document_ids"] = list(scope_document_ids) if scope_document_ids else None
            if title and not payload.get("title"):
                payload["title"] = title
            payload["updated_at"] = payload.get("updated_at") or _utc_now()
            _atomic_write(path, payload)

    def summaries(self, limit: int = 50) -> list[dict]:
        """Most recent conversations first, without message bodies."""
        if not self.root.exists():
            return []
        files = sorted(self.root.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        out = []
        for path in files[:max(1, limit)]:
            conversation_id = path.stem
            try:
                self._safe_id(conversation_id)
                payload = self.load(conversation_id)
            except (ValueError, RuntimeError):
                continue  # skip unreadable/foreign files rather than failing the list
            messages = payload.get("messages") or []
            first_question = next((m.get("content") for m in messages if m.get("role") == "user"), "")
            out.append({
                "conversation_id": conversation_id,
                "title": payload.get("title") or _conversation_title(first_question),
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at") or payload.get("created_at"),
                "message_count": len(messages),
                "scope_document_ids": payload.get("scope_document_ids"),
            })
        return out

    def delete(self, conversation_id: str) -> bool:
        path = self._path(conversation_id)
        with FileLock(str(path) + ".write.lock", timeout=30):
            existed = path.exists()
            path.unlink(missing_ok=True)
        for suffix in (".write.lock", ".turn.lock"):
            try:
                Path(str(path) + suffix).unlink(missing_ok=True)
            except OSError:
                pass  # a lock held by another request; harmless leftover
        return existed

    def append(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources=None,
        metadata: dict | None = None,
    ) -> None:
        """Append one message while preserving lightweight context for follow-ups.

        Older conversation files without the ``metadata`` field remain fully
        compatible.  Metadata is internal and never treated as document evidence.
        """
        with FileLock(str(self._path(conversation_id)) + ".write.lock", timeout=30):
            payload = self.load(conversation_id)
            payload.setdefault("messages", []).append(
                {
                    "role": role,
                    "content": content,
                    "sources": sources or [],
                    "metadata": metadata or {},
                    "created_at": _utc_now(),
                }
            )
            payload["updated_at"] = _utc_now()
            _atomic_write(self._path(conversation_id), payload)


def _close_vector_store(store) -> None:
    """Best-effort release of an evicted cache entry; never raises.

    ``UserPGVectorStore`` exposes no ``close()``/``dispose()``, so eviction
    alone is the guaranteed action: dropping the last cache reference lets the
    PGVector + SQLAlchemy pool go once idle. Store doubles (or future variants)
    that do expose one are closed here, and cache housekeeping must never fail
    a request, so any close error is ignored after the entry is already gone.
    """
    for target in (store, getattr(store, "store", None)):
        close = getattr(target, "close", None) or getattr(target, "dispose", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
            return


def get_user_vector_store(user_id: str | int):
    """Return a cached per-user PGVector store (isolation key = user_id).

    Reuse avoids reconstructing PGVector + connection overhead on every
    query. Cache key includes only the user so one user's vectors never
    leak into another user's retrieval. The cache is a bounded LRU: at
    ``RAG_VECTOR_STORE_CACHE_MAX`` entries the least-recently-used store is
    evicted (and closed when it exposes ``close``/``dispose``) so a process
    serving N users cannot hold N pools forever.
    """
    key = str(user_id)
    evicted = None
    try:
        with _LOCK:
            cached = _VECTOR_STORE_CACHE.get(key)
            if cached is not None:
                # LRU touch: reinsert so eviction drops least-recently-used.
                _VECTOR_STORE_CACHE.pop(key, None)
                _VECTOR_STORE_CACHE[key] = cached
                return cached
            if len(_VECTOR_STORE_CACHE) >= RAG_VECTOR_STORE_CACHE_MAX:
                evicted = _VECTOR_STORE_CACHE.pop(next(iter(_VECTOR_STORE_CACHE)))
            store = UserPGVectorStore(user_id)
            _VECTOR_STORE_CACHE[key] = store
            return store
    finally:
        if evicted is not None:
            _close_vector_store(evicted)


_PROBE_TTL_SECONDS = 30.0
_PROBE_CACHE: dict[str, tuple[float, dict]] = {}


def _psycopg_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    return url


def probe_vector_database(*, timeout_seconds: int = 3) -> dict:
    """Connect to the RAG database and confirm the pgvector extension exists.

    Returns ``{"reachable": bool, "pgvector": bool, "error": str | None}``.
    Cached briefly so a health dashboard polling the route cannot hammer the
    database; the engine always uses a bounded connect timeout and is disposed.
    """
    import time

    if not RAG_DATABASE_URL:
        return {"reachable": False, "pgvector": False, "error": "not_configured"}
    now = time.monotonic()
    with _LOCK:
        cached = _PROBE_CACHE.get(RAG_DATABASE_URL)
        if cached and now - cached[0] < _PROBE_TTL_SECONDS:
            return dict(cached[1])
    result = {"reachable": False, "pgvector": False, "error": None}
    engine = None
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(_psycopg_url(RAG_DATABASE_URL), pool_pre_ping=False,
                               connect_args={"connect_timeout": timeout_seconds})
        with engine.connect() as conn:
            result["reachable"] = True
            row = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()
            result["pgvector"] = row is not None
            if row is None:
                result["error"] = "pgvector_missing"
    except Exception as exc:  # report the class only; never the DSN
        result["error"] = type(exc).__name__
    finally:
        if engine is not None:
            engine.dispose()
    with _LOCK:
        _PROBE_CACHE[RAG_DATABASE_URL] = (now, dict(result))
    return result


class UserPGVectorStore:
    """One isolated LangChain PGVector collection per authenticated user."""

    def __init__(self, user_id: str | int):
        if not RAG_DATABASE_URL:
            raise RuntimeError(
                "ARIA_RAG_DATABASE_URL is not configured. Set it to PostgreSQL with pgvector enabled, e.g. "
                "postgresql+psycopg://postgres:password@localhost:5432/aria_rag"
            )

        try:
            from langchain_postgres import PGVector
        except ImportError as exc:
            raise RuntimeError(
                "langchain-postgres is required for PDF RAG. Run: pip install langchain-postgres"
            ) from exc

        connection = _psycopg_url(RAG_DATABASE_URL)
        collection = f"{RAG_COLLECTION_PREFIX}_{user_key(user_id)}"
        self.store = PGVector(
            embeddings=FastBGEEmbeddings(),
            collection_name=collection,
            connection=connection,
            use_jsonb=True,
        )

    def add_documents(self, documents: list[Document]) -> list[str]:
        # Loud on failure: the caller rolls back the filesystem side too.
        ids = [str(doc.metadata["chunk_id"]) for doc in documents]
        self.store.add_documents(documents=documents, ids=ids)
        return ids

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        # Loud on failure: incomplete cleanup must raise so the caller can
        # fail loudly instead of reporting a partial index as healthy.
        if chunk_ids:
            self.store.delete(ids=chunk_ids)

    def search(self, query: str, *, k: int, document_ids: list[str] | None = None):
        if document_ids == []:
            return []
        metadata_filter = None
        if document_ids:
            if len(document_ids) == 1:
                metadata_filter = {"document_id": document_ids[0]}
            else:
                metadata_filter = {"document_id": {"$in": document_ids}}
        return self.store.similarity_search_with_score(
            query=query,
            k=k,
            filter=metadata_filter,
        )
