"""Data source connection routes: relational databases (PostgreSQL / MySQL) + CSV files + PDF documents."""

import asyncio
import json
import os
import re
import time
import types
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import csv_orchestrator
import schema_agent
from core.config import DB_TYPES, PROVIDER_NAMES, SOURCE_TYPES, SCHEMA_DIR, PROCESSED_DIR, INSIGHTS_DIR, DATA_DIR, get_session, save_session
from core.db import build_db_uri
from core.deps import require_writable, get_current_user
from core.secret_box import decrypt as _decrypt_secret
from csv_handler import CsvValidationError
from llm_provider import create_provider
from document_processor import create_document_processor

router = APIRouter()

# Hosted providers run inference off-machine (need an API key, can serve vision).
HOSTED_PROVIDERS = {"cloud", "deepseek", "omniroute"}

# Upload bounds (§40): enforced while streaming so oversized bodies never
# fill the disk. CSV cap matches the handler's 100 MB post-write check.
MAX_UPLOAD_BYTES_CSV = int(os.getenv("ARIA_MAX_UPLOAD_CSV_MB", "100")) * 1024 * 1024
MAX_UPLOAD_BYTES_PDF = int(os.getenv("ARIA_MAX_UPLOAD_PDF_MB", "50")) * 1024 * 1024


def _spool_limited(upload_file, dest: Path, max_bytes: int, label: str) -> int:
    """Stream an upload to disk, aborting with 413 past max_bytes."""
    total = 0
    with open(dest, "wb") as _f:
        while True:
            chunk = upload_file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                try:
                    _f.close()
                    dest.unlink(missing_ok=True)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=413,
                    detail=f"{label} exceeds the {max_bytes // (1024 * 1024)} MB upload limit.",
                )
            _f.write(chunk)
    return total


def _pdf_tables_to_sqlite(document, upload_dir: Path, stem: str, stamp: str):
    """Load clean PDF tables into a queryable SQLite DB (§5/§15).

    Returns (db_uri, mapping_tables, loaded_names) or (None, {}, []) when
    no table is well-formed enough to query. Never raises: failures degrade
    to document-only (RAG) mode, which keeps working.
    """
    import sqlite3 as _sqlite3

    from csv_orchestrator import _quote_ident

    usable = []
    for i, t in enumerate(getattr(document, "tables", []) or []):
        try:
            raw_headers = t.get("headers", []) or []
            headers = [str(h or "").strip() or f"col_{j}" for j, h in enumerate(raw_headers)]
            rows = [r for r in (t.get("rows", []) or [])
                    if any(str(c or "").strip() for c in r)]
            if len(headers) < 2 or not rows:
                continue
            clean, seen = [], set()
            for h in headers:
                base = re.sub(r"[^0-9a-zA-Z]+", "_", h).strip("_") or "col"
                name, k = base, 2
                while name.lower() in seen:
                    name, k = f"{base}_{k}", k + 1
                seen.add(name.lower())
                clean.append(name)
            # Infer REAL columns (all non-empty cells numeric) for aggregation.
            col_types = []
            for j in range(len(clean)):
                vals = [str(r[j]).strip() for r in rows if j < len(r) and str(r[j]).strip()]
                numeric = [v.replace(",", "").replace("$", "").replace("%", "") for v in vals]
                if vals and all(_is_num(v) for v in numeric):
                    col_types.append("REAL")
                else:
                    col_types.append("TEXT")
            usable.append({"name": f"pdf_t{i}", "columns": clean,
                           "types": col_types, "rows": rows, "page": t.get("page")})
        except Exception:
            continue
    if not usable:
        return None, {}, []

    db_path = upload_dir / f"{stem}_{stamp}_tables.db"
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        conn = _sqlite3.connect(str(db_path))
        mapping_tables: dict = {}
        loaded: list[str] = []
        try:
            for t in usable:
                ddl = ", ".join(f"{_quote_ident(c)} {typ}"
                                for c, typ in zip(t["columns"], t["types"]))
                conn.execute(f"CREATE TABLE {_quote_ident(t['name'])} ({ddl})")
                placeholders = ", ".join("?" for _ in t["columns"])
                cols = ", ".join(_quote_ident(c) for c in t["columns"])
                batch = []
                for r in t["rows"]:
                    vals = []
                    for j, typ in enumerate(t["types"]):
                        cell = str(r[j]).strip() if j < len(r) else ""
                        if not cell:
                            vals.append(None)
                        elif typ == "REAL":
                            try:
                                vals.append(float(cell.replace(",", "").replace("$", "").replace("%", "")))
                            except ValueError:
                                vals.append(None)
                        else:
                            vals.append(cell)
                    batch.append(vals)
                conn.executemany(
                    f"INSERT INTO {_quote_ident(t['name'])} ({cols}) VALUES ({placeholders})",
                    batch,
                )
                mapping_tables[t["name"]] = {
                    "columns": [{"column": c, "data_type": ("REAL" if typ == "REAL" else "TEXT"),
                                 "nullable": True} for c, typ in zip(t["columns"], t["types"])],
                    "primary_key": [],
                    "row_count": len(batch),
                    "source": f"pdf page {t['page']}",
                }
                loaded.append(t["name"])
            conn.commit()
        finally:
            conn.close()
        return f"sqlite:///{db_path}", mapping_tables, loaded
    except Exception:
        try:
            db_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None, {}, []


def _is_num(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False

# ── Ingestion progress tracking ──────────────────────────────────────────
# Maps user_id -> { "step": str, "progress": float 0-100, "message": str, "done": bool, "error": str|None }
_upload_progress: dict[int, dict] = {}


def _set_progress(user_id: int, step: str, progress: float, message: str, done: bool = False, error: str | None = None, result: dict | None = None):
    _upload_progress[user_id] = {
        "step": step,
        "progress": progress,
        "message": message,
        "done": done,
        "error": error,
        "result": result,
        "timestamp": time.time(),
    }


@router.get("/api/upload/progress")
async def get_upload_progress(user: dict = Depends(get_current_user)):
    """Return current ingestion progress for the user."""
    prog = _upload_progress.get(user["user_id"])
    if not prog:
        return {"ok": True, "active": False}
    return {"ok": True, "active": True, **prog}


@router.get("/api/upload/progress/stream")
async def stream_upload_progress(user: dict = Depends(require_writable)):
    """SSE stream of ingestion progress for the user (writable sessions only, max 2 min)."""
    async def event_stream():
        uid = user["user_id"]
        last_ts = 0
        for _ in range(120):  # max 2 minutes (was 5 min, reduces connection exhaustion)
            prog = _upload_progress.get(uid)
            if prog and prog.get("timestamp", 0) > last_ts:
                last_ts = prog["timestamp"]
                yield f"data: {json.dumps({k: v for k, v in prog.items() if k != 'timestamp'})}\n\n"
                if prog.get("done") or prog.get("error"):
                    break
            await asyncio.sleep(1)
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ProviderSwitchRequest(BaseModel):
    provider: str = "local"
    api_key: str | None = None      # optional key override for hosted providers
    base_url: str | None = None     # optional endpoint override for hosted providers


@router.post("/api/provider/switch")
def switch_provider(request: ProviderSwitchRequest, user: dict = Depends(require_writable)):
    """Explicitly switch the LLM backend for this session."""
    session = get_session(user["user_id"])
    if request.provider not in PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{request.provider}'. Choose from {sorted(PROVIDER_NAMES)}.")
    # SSRF guard: custom endpoints only over https for hosted providers.
    # Local provider (ollama) may use loopback http; hosted must not probe internal http.
    if request.base_url and request.provider != "local":
        if not request.base_url.startswith("https://"):
            raise HTTPException(status_code=400, detail="Custom base_url must use https:// (http/internal hosts blocked).")
    current = session.get("provider_name")
    if current == request.provider:
        return {"ok": True, "provider": current, "changed": False}

    try:
        llm = create_provider(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{request.provider}' LLM provider: {exc}")

    # Validate hosted keys with a no-cost ping so a bad key fails here,
    # not pages later inside an analysis.
    if request.provider != "local" and (request.api_key or request.provider in ("cloud", "deepseek", "omniroute")):
        try:
            llm.ping(timeout=25)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"The {request.provider} key was rejected or unreachable ({exc}). Check the key and try again.",
            )

    session["provider"] = llm
    session["provider_name"] = request.provider
    # Provider isolation: API keys are stored per hosted provider only.
    # Local (Ollama) uses no key, so a key sent with provider=local is ignored
    # rather than stored.
    if request.api_key and request.provider in HOSTED_PROVIDERS:
        keys = session.get("api_keys", {})
        keys[request.provider] = request.api_key
        session["api_keys"] = keys
    save_session(user["user_id"], session)
    return {"ok": True, "provider": request.provider, "changed": True}


class ConnectRequest(BaseModel):
    provider: str = "local"
    source_type: str = "relational"
    db_type: str = "postgresql"   # 'postgresql' | 'mysql'
    host: str = "localhost"
    port: int | str = 5432
    db: str | None = None
    user: str | None = None
    password: str | None = None
    db_schema: str = "public"


def _discover_table_schema(config, exclude="public"):
    """Find the PostgreSQL schema that actually holds tables.

    Returns (mapping, schema_name); ({}, None) when nothing is found.
    Read-only introspection; used only when the requested schema is empty.
    """
    import logging as _logging
    _log = _logging.getLogger("aria.connect")
    try:
        conn = schema_agent.get_connection(types.SimpleNamespace(**config))
    except Exception:
        return {}, None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('pg_catalog', 'information_schema') "
                "AND schema_name NOT LIKE 'pg\\_toast%' AND schema_name NOT LIKE 'pg\\_temp%' "
                "ORDER BY (schema_name = 'public') DESC, schema_name;"
            )
            schemata = [r[0] for r in cur.fetchall() if r[0] != exclude]
        for sch in schemata:
            try:
                mapping = schema_agent.build_schema_mapping(conn, sch, db_type="postgresql")
            except Exception:
                continue
            if mapping.get("tables"):
                _log.info("Schema auto-discovery: using '%s' (%d tables).",
                          sch, len(mapping["tables"]))
                return mapping, sch
    except Exception:
        _log.exception("Schema auto-discovery failed.")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {}, None


def _do_connect(request: ConnectRequest, user: dict, db_type: str) -> dict:
    """Shared connect logic. `db_type` is authoritative (set by the calling endpoint)."""
    uid = user["user_id"]
    _set_progress(uid, "connecting", 15, f"Connecting to {db_type} database...")

    session = get_session(uid)
    if request.provider not in PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{request.provider}'. Choose from {sorted(PROVIDER_NAMES)}.")
    if request.source_type not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown source type '{request.source_type}'. Choose from {sorted(SOURCE_TYPES)}.")
    if request.source_type == "relational" and db_type not in DB_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown database type '{db_type}'. Choose from {sorted(DB_TYPES)}.")

    if request.source_type == "relational":
        if not (request.db and request.user and request.password):
            raise HTTPException(status_code=400, detail="Relational source requires db, user, and password.")

    # Use user's saved API key for hosted providers if available
    user_key = session.get("api_keys", {}).get(request.provider) if request.provider in HOSTED_PROVIDERS else None
    try:
        llm = create_provider(provider=request.provider, api_key=user_key or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{request.provider}' LLM provider: {exc}")

    # The provider in this connect request is an explicit user choice.
    session["provider"] = llm
    session["provider_name"] = request.provider
    session["source_type"] = request.source_type
    # A fresh database connection replaces any previously linked source.
    session.pop("linked_db", None)
    session["db"] = None
    session["db_type"] = db_type
    session["db_uri"] = None
    session["db_name"] = None
    uid_dir = f"user_{user['user_id']}"
    session["schema_path"] = SCHEMA_DIR / uid_dir / "schema_mapping_latest.json"
    session["processed_path"] = PROCESSED_DIR / uid_dir / "processed_data.json"
    session["insights_path"] = INSIGHTS_DIR / uid_dir / "insights.json"
    session["processed_path"].parent.mkdir(parents=True, exist_ok=True)
    session["insights_path"].parent.mkdir(parents=True, exist_ok=True)

    config = request.model_dump()
    config["db_type"] = db_type
    conn = None
    try:
        config["port"] = int(config["port"])
        conn = schema_agent.get_connection(types.SimpleNamespace(**config))
        with conn.cursor() as cur:
            if db_type == "mysql":
                cur.execute("SELECT DATABASE();")
                db_name = cur.fetchone()[0]
                current_db_schema = db_name
            else:
                cur.execute("SELECT current_database(), current_schema();")
                db_name, current_db_schema = cur.fetchone()
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid port number.")
    except Exception as exc:
        import logging as _logging
        from core.errors import sanitize_error
        _logging.getLogger("aria.connect").exception("Database connection failed")
        safe = sanitize_error(exc)
        if db_type == "mysql":
            detail = (f"Connection failed: {safe} Hint: is the MySQL server running, "
                      "and is pymysql installed (pip install pymysql)? "
                      "Verify host/port, database, user, password.")
        else:
            detail = (f"Connection failed: {safe} Hint: is the PostgreSQL service running "
                      "on that host/port? Verify the database name, user, and password are correct.")
        raise HTTPException(status_code=400, detail=detail)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    from core.secret_box import encrypt as _encrypt_secret
    safe_config = dict(config)
    if "password" in safe_config and safe_config["password"] is not None:
        safe_config["password"] = _encrypt_secret(str(safe_config["password"]))
    session["db"] = safe_config
    session["db_type"] = db_type
    session["db_uri"] = build_db_uri(config, db_type)
    session["db_name"] = db_name
    session["dialect"] = db_type

    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", db_name)
    uid_dir = f"user_{user['user_id']}"
    # Schema Agent writes DB-specific files (e.g. schema_mapping_northwind_latest.json)
    # so the session must point to the same naming convention.
    session["schema_path"] = SCHEMA_DIR / uid_dir / f"schema_mapping_{safe}_latest.json"
    session["processed_path"] = PROCESSED_DIR / uid_dir / f"processed_data_{safe}.json"
    session["insights_path"] = INSIGHTS_DIR / uid_dir / f"insights_{safe}.json"
    session["processed_path"].parent.mkdir(parents=True, exist_ok=True)
    session["insights_path"].parent.mkdir(parents=True, exist_ok=True)

    save_session(user["user_id"], session)

    _set_progress(uid, "extracting", 50, "Extracting schema...")

    # Auto-trigger schema extraction so Dashboard KPIs work immediately
    import logging as _logging

    _conn_log = _logging.getLogger("aria.connect")
    session["schema_status"] = "pending"
    try:
        config = dict(session.get("db", {}))
        if "password" in config and config.get("password"):
            try:
                config["password"] = _decrypt_secret(config["password"])
            except Exception as exc:
                _conn_log.error("Stored DB credential failed to decrypt; "
                                "reconnect with a fresh password. (%s)", exc)
                raise HTTPException(
                    status_code=400,
                    detail="Stored database credential is unreadable. "
                           "Please reconnect with your password.",
                )
        try:
            conn = schema_agent.get_connection(types.SimpleNamespace(**config))
        except SystemExit as _sx:
            _conn_log.error("Schema extraction refused connection setup: %s", _sx)
            raise
        try:
            db_type = session.get("db_type", "postgresql")
            schema_filter = config.get("db_schema", "public") if db_type == "postgresql" else config.get("db", "")
            mapping = schema_agent.build_schema_mapping(conn, schema_filter, db_type=db_type)
            conn.close()
            if not mapping.get("tables") and db_type == "postgresql":
                # Requested schema is empty (e.g. tables live in a named
                # schema like "hotel", not public): discover the schema that
                # actually holds tables instead of connecting to nothing.
                mapping, discovered = _discover_table_schema(config, exclude=schema_filter)
                if discovered:
                    session["db"]["db_schema"] = discovered
                    current_db_schema = discovered
            if mapping.get("tables"):
                user_schema_dir = SCHEMA_DIR / f"user_{user['user_id']}"
                user_schema_dir.mkdir(parents=True, exist_ok=True)
                safe_name_for_file = re.sub(r"[^a-zA-Z0-9_-]+", "_", db_name)[:64] or "db"
                user_path = user_schema_dir / f"schema_mapping_{safe_name_for_file}_latest.json"
                user_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
                session["schema_path"] = user_path
                session["schema_status"] = "ok"
                save_session(user["user_id"], session)
            else:
                session["schema_status"] = "empty"
                save_session(user["user_id"], session)
                _conn_log.warning("Schema extraction returned no tables for db '%s' (user %s).",
                                  db_name, user["user_id"])
        except Exception as exc:
            session["schema_status"] = "failed"
            save_session(user["user_id"], session)
            _conn_log.exception("Schema extraction failed for db '%s' (user %s).",
                                db_name, user["user_id"])
    except SystemExit:
        pass
    except Exception as exc:
        session["schema_status"] = "failed"
        try:
            save_session(user["user_id"], session)
        except Exception:
            pass
        _conn_log.exception("Schema extraction setup failed for db '%s'.", db_name)

    _set_progress(uid, "ready", 100, "Connected", done=True)

    return {
        "ok": True,
        "provider": request.provider,
        "source_type": "relational",
        "database": db_name,
        "schema": current_db_schema,
        "db_type": db_type,
        "schema_file": Path(str(session.get("schema_path", ""))).name,
        "schema_status": session.get("schema_status", "unknown"),
    }


@router.post("/api/connect")
def connect(request: ConnectRequest, user: dict = Depends(require_writable)):
    """Connect to a source; database type taken from the request body."""
    return _do_connect(request, user, request.db_type)


@router.post("/api/connect/postgresql")
def connect_postgresql(request: ConnectRequest, user: dict = Depends(require_writable)):
    """Connect to a PostgreSQL source (explicit route)."""
    return _do_connect(request, user, "postgresql")


@router.post("/api/connect/mysql")
def connect_mysql(request: ConnectRequest, user: dict = Depends(require_writable)):
    """Connect to a MySQL source (explicit route)."""
    return _do_connect(request, user, "mysql")


@router.post("/api/connect_file")
def connect_file(provider: str = Form("local"), file: UploadFile = File(...),
                 llm_api_key: str | None = Form(None),
                 llm_base_url: str | None = Form(None),
                 user: dict = Depends(require_writable)):
    """Connect a semi-structured source: upload a CSV file.

    The file is validated and profiled deterministically with the CSV handler
    (encoding/dialect detection, header checks, type inference, data-quality
    warnings), its schema mapping is written in the Goal Agent's ``tables``
    format, the rows are loaded into a file-based SQLite database, and the
    session is pointed at it so the Goal Agent and Insight Agent consume it
    exactly like a relational source (dialect=sqlite).
    """
    if provider not in PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'. Choose from {sorted(PROVIDER_NAMES)}.")
    if llm_base_url and provider != "local":
        if not llm_base_url.startswith("https://"):
            raise HTTPException(status_code=400, detail="Custom base_url must use https:// (http/internal hosts blocked).")
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="No file received.")
    ext = Path(filename).suffix.lower()
    if ext != ".csv":
        raise HTTPException(
            status_code=400,
            detail="Only .csv files are accepted for file sources right now. "
                   "Tabular PDF extraction is not available in this build.",
        )
    try:
        llm = create_provider(provider=provider, api_key=llm_api_key, base_url=llm_base_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{provider}' LLM provider: {exc}")

    uid = user["user_id"]
    _set_progress(uid, "uploading", 10, "Uploading file...")

    # Isolate uploads by user and use an unpredictable suffix to prevent
    # same-name uploads from overwriting one another.
    upload_dir = DATA_DIR / "uploads" / f"user_{uid}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(8)}"
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(filename).stem)[:64] or "upload"
    file_path = upload_dir / f"{safe_name}_{stamp}{ext}"
    _spool_limited(file.file, file_path, MAX_UPLOAD_BYTES_CSV, "CSV file")

    _set_progress(uid, "validating", 25, "Validating CSV structure...")

    try:
        table_name = csv_orchestrator.safe_table_name(safe_name)
        mapping = csv_orchestrator.build_csv_schema_mapping(file_path, table_name=table_name)
    except CsvValidationError as exc:
        _set_progress(uid, "error", 0, f"Invalid CSV: {exc}", error=str(exc))
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}")
    except Exception as exc:
        from core.errors import sanitize_error as _san
        _set_progress(uid, "error", 0, "Validation failed", error=_san(exc))
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"CSV processing failed: {_san(exc)}")

    _set_progress(uid, "extracting", 45, "Extracting schema and structure...")

    try:
        sqlite_path = upload_dir / f"{safe_name}_{stamp}.db"
        db_uri, table_name, row_count = csv_orchestrator.load_csv_to_sqlite(
            file_path, sqlite_path, table_name=table_name
        )
    except Exception as exc:
        from core.errors import sanitize_error as _san2
        _set_progress(uid, "error", 0, "Processing failed", error=_san2(exc))
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"CSV processing failed: {_san2(exc)}")

    _set_progress(uid, "profiling", 65, f"Profiling {row_count} rows...")

    uid_dir = f"user_{uid}"
    safe_db_name = mapping["database"]
    schema_path = SCHEMA_DIR / uid_dir / f"schema_mapping_{safe_db_name}_latest.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    _set_progress(uid, "understanding", 80, "Understanding data structure...")

    session = get_session(uid)
    # A new file connection must honour the provider selected for this upload.
    session["provider"] = llm
    session["provider_name"] = provider
    session["source_type"] = "semi-structured"
    session["db"] = {".csv": str(file_path)}
    # A fresh file source replaces any previously linked source.
    session.pop("linked_db", None)
    session["db_type"] = "sqlite"
    session["db_uri"] = db_uri
    session["db_name"] = table_name
    session["schema_path"] = schema_path
    session["processed_path"] = PROCESSED_DIR / uid_dir / f"processed_data_{safe_db_name}.json"
    session["insights_path"] = INSIGHTS_DIR / uid_dir / f"insights_{safe_db_name}.json"
    session["processed_path"].parent.mkdir(parents=True, exist_ok=True)
    session["insights_path"].parent.mkdir(parents=True, exist_ok=True)
    session["dialect"] = "sqlite"
    session["file_type"] = "csv"

    save_session(uid, session)

    _set_progress(uid, "generating", 90, "Generating insights...")

    columns = [c["column"] for c in mapping["tables"][table_name]["columns"]]
    quality = mapping["tables"][table_name]["csv_profile"]["quality"]

    result = {
        "ok": True,
        "provider": provider,
        "source_type": "semi-structured",
        "file": filename,
        "type": "csv",
        "tables": {table_name: row_count},
        "table": table_name,
        "rows": row_count,
        "columns": columns,
        "schema_file": schema_path.name,
        "quality": quality,
        "db_file": sqlite_path.name,
    }

    _set_progress(uid, "ready", 100, "Ready", done=True, result=result)

    return result


@router.post("/api/connect_pdf")
def connect_pdf(
    provider: str = Form("local"),
    file: UploadFile = File(...),
    llm_api_key: str | None = Form(None),
    llm_base_url: str | None = Form(None),
    user: dict = Depends(require_writable),
):
    """Connect a document source: upload a PDF file.
    
    The PDF is processed through ARIA's document intelligence pipeline:
    - Validation and integrity check
    - Document type detection (digital, scanned, handwritten, mixed)
    - Content extraction (text, OCR, vision LLM)
    - Table extraction
    - Chunking with metadata
    - Embedding generation
    - Vector indexing for RAG retrieval
    """
    if provider not in PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'. Choose from {sorted(PROVIDER_NAMES)}.")
    if llm_base_url and provider != "local":
        if not llm_base_url.startswith("https://"):
            raise HTTPException(status_code=400, detail="Custom base_url must use https:// (http/internal hosts blocked).")
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="No file received.")
    ext = Path(filename).suffix.lower()
    if ext != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Only .pdf files are accepted for document sources.",
        )
    
    session = get_session(user["user_id"])
    # Provider isolation: only hosted providers use a saved API key; local
    # (Ollama) works keyless and must never pick one up.
    saved_key = session.get("api_keys", {}).get(provider) if provider in HOSTED_PROVIDERS else None
    try:
        llm = create_provider(
            provider=provider,
            api_key=llm_api_key or saved_key,
            base_url=llm_base_url,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{provider}' LLM provider: {exc}")

    # Keep raw PDFs within the owning user's upload directory.
    upload_dir = DATA_DIR / "uploads" / f"user_{user['user_id']}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(8)}"
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(filename).stem)[:64] or "upload"
    file_path = upload_dir / f"{safe_name}_{stamp}{ext}"
    _spool_limited(file.file, file_path, MAX_UPLOAD_BYTES_PDF, "PDF file")

    # Create document processor
    processed_dir = PROCESSED_DIR / f"user_{user['user_id']}" / "documents"
    vector_index_dir = PROCESSED_DIR / f"user_{user['user_id']}" / "vector_store"
    
    processor = create_document_processor(
        upload_dir=upload_dir,
        processed_dir=processed_dir,
        llm_provider=llm if provider in HOSTED_PROVIDERS else None,
    )
    
    # Process document (this runs synchronously - could be made async with background tasks)
    result = processor.process_document(
        file_path=file_path,
        user_id=user["user_id"],
        original_name=filename,
    )
    
    if not result.success:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=result.error or "Document processing failed")
    
    document = result.document

    # Update session to include document reference
    session = get_session(user["user_id"])
    # Multi-source (§7): a PDF upload must not destroy a live database
    # connection. Stash the queryable relational/file source so Copilot can
    # answer from both (with per-source attribution) in one session.
    try:
        _prev_uri = session.get("db_uri") or ""
        _prev_type = session.get("db_type", "")
        if _prev_type in ("postgresql", "mysql", "sqlite") and not str(_prev_uri).startswith("document://"):
            _sp = session.get("schema_path")
            _stash: dict = {
                "db": session.get("db"),
                "db_type": _prev_type,
                "db_name": session.get("db_name"),
                "dialect": session.get("dialect", _prev_type),
                "source_type": session.get("source_type"),
                "schema_path": str(_sp) if _sp else None,
            }
            # File-based sqlite URIs carry no secret and are safe to stash;
            # relational URIs embed the password and are rebuilt instead.
            if _prev_type == "sqlite":
                _stash["db_uri"] = _prev_uri
            session["linked_db"] = _stash
    except Exception:
        pass
    # A new document connection must honour the provider selected for this upload.
    session["provider"] = llm
    session["provider_name"] = provider
    session["source_type"] = "document"
    session["db"] = {".pdf": str(file_path)}
    session["db_type"] = "document"
    session["db_uri"] = f"document://{document.id}"
    session["db_name"] = document.id
    session["dialect"] = "document"
    session["document_id"] = document.id
    session["document_name"] = filename
    session["document_type"] = document.document_type.value if document.document_type else "unknown"

    # Structured PDF tables become queryable SQLite + schema mapping (§5/§15).
    # RAG over the narrative keeps working regardless.
    pdf_tables_loaded: list[str] = []
    try:
        _pdf_uri, _pdf_mapping, pdf_tables_loaded = _pdf_tables_to_sqlite(
            document, upload_dir, safe_name, stamp)
        if _pdf_uri and _pdf_mapping:
            from core.config import SCHEMA_DIR as _SCHEMA_DIR

            _uid_dir = f"user_{user['user_id']}"
            _safe_db = re.sub(r"[^a-zA-Z0-9_-]+", "_", f"pdf_{safe_name}")[:64] or "pdf_doc"
            _schema_path = _SCHEMA_DIR / _uid_dir / f"schema_mapping_{_safe_db}_latest.json"
            _schema_path.parent.mkdir(parents=True, exist_ok=True)
            _schema_path.write_text(json.dumps({
                "database": _safe_db,
                "tables": _pdf_mapping,
            }, indent=2), encoding="utf-8")
            session["source_type"] = "semi-structured"
            session["db"] = {"document_tables": _pdf_uri}
            session["db_type"] = "sqlite"
            session["db_uri"] = _pdf_uri
            session["db_name"] = _safe_db
            session["dialect"] = "sqlite"
            session["schema_path"] = _schema_path
    except Exception:
        pass

    if not pdf_tables_loaded:
        # Text-only PDF: stay a `document` source and drop every stale
        # analytical pointer (schema/db/artifact refs from a previous
        # connection). SQL analytics must never run against the old source.
        for _key in ("schema_path", "processed_path", "insights_path",
                     "schema_status", "pending_history_id", "file_type"):
            session.pop(_key, None)
        session["schema_status"] = "document"
    
    # Ensure processed directories exist
    processed_dir.mkdir(parents=True, exist_ok=True)
    vector_index_dir.mkdir(parents=True, exist_ok=True)

    # Bridge (§7/§21): mirror the manifest + text chunks into the shared RAG
    # metadata store so Copilot's document/combined branches read the same
    # content the Documents page indexed. Best-effort; never fails the upload.
    try:
        from insight_rag.storage import RAGMetadataStore as _RAGStore
        from langchain_core.documents import Document as _LCDocument
        _rag = _RAGStore(user["user_id"])
        _rag.put_document({
            "document_id": document.id,
            "filename": filename,
            "original_filename": filename,
            "document_type": document.document_type.value if document.document_type else "unknown",
            "page_count": document.page_count,
            "chunk_count": len(document.chunks),
            "created_at": document.created_at,
            "source": "upload",
        })
        _lcdocs = [_LCDocument(
            page_content=c.content or "",
            metadata={"page": c.page_number, "section": c.section,
                      "chunk_id": c.id, "document_id": document.id},
        ) for c in (document.chunks or []) if (c.content or "").strip()]
        if _lcdocs:
            _rag.save_chunks(document.id, _lcdocs)
    except Exception as _bridge_exc:
        import logging as _logging
        _logging.getLogger("aria.connect").info(
            "RAG store mirroring skipped (%s).", type(_bridge_exc).__name__)

    save_session(user["user_id"], session)
    
    return {
        "ok": True,
        "provider": provider,
        "source_type": "document",
        "file": filename,
        "type": "pdf",
        "document_id": document.id,
        "document_type": document.document_type.value if document.document_type else "unknown",
        "page_count": document.page_count,
        "element_count": len(document.elements),
        "chunk_count": len(document.chunks),
        "table_count": len(document.tables),
        "tables_loaded": pdf_tables_loaded,
        "queryable": bool(pdf_tables_loaded),
        "status": document.status.value,
        "processing_method": document.processing_method,
        "failed_pages": result.failed_pages,
        "warnings": result.warnings,
    }


@router.get("/api/session/status")
def session_status(user: dict = Depends(get_current_user)):
    """Return the current session's connectivity and DB info so the frontend can restore state."""
    session = get_session(user.get("user_id"))
    is_connected = bool(session.get("db") or session.get("db_uri") or
                        session.get("source_type") == "semi-structured")
    # Never expose credentials: db_uri embeds user:password (§41).
    raw_uri = session.get("db_uri", "") or ""
    safe_uri = re.sub(r"://([^:/@]+):[^@/]*@", r"://\1:***@", raw_uri)
    linked = session.get("linked_db") or {}
    return {
        "ok": True,
        "connection_status": "connected" if is_connected else "not-connected",
        "db_name": session.get("db_name", ""),
        "source_type": session.get("source_type", ""),
        "db_uri": safe_uri,
        # Multi-source (§7): a linked database and/or document stay visible
        # so the UI can show what ARIA can reason over.
        "document_id": session.get("document_id", ""),
        "document_name": session.get("document_name", ""),
        "linked_db_name": linked.get("db_name", "") if isinstance(linked, dict) else "",
        "multi_source": bool(linked and session.get("document_id")),
    }


@router.post("/api/disconnect")
def disconnect_source(user: dict = Depends(require_writable)):
    """Remove the active data source while retaining the user's LLM settings."""
    session = get_session(user["user_id"])
    for key in (
        "source_type", "db", "db_uri", "db_name", "dialect", "schema_path",
        "processed_path", "insights_path", "schema_status", "file_type",
        "document_id", "document_name", "document_type", "linked_db",
        "conversation_id", "conversation_history",
        "pending_history_id",
    ):
        session.pop(key, None)
    save_session(user["user_id"], session)
    return {"ok": True, "message": "Data source disconnected"}

class DatabaseTestRequest(BaseModel):
    host: str = "localhost"
    port: int = 5432
    db: str = ""
    user: str = ""
    password: str = ""
    dbType: str = "postgresql"


@router.post("/api/database/test")
async def test_database_connection(req: DatabaseTestRequest, _user: dict = Depends(require_writable)):
    """Test a database connection before actually connecting (writable sessions only)."""
    # Validate host/port/db to block SSRF probing (cloud metadata, unexpected schemes).
    host = (req.host or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", host) or len(host) > 253:
        raise HTTPException(status_code=400, detail="Invalid host.")
    if host.lower() in {"169.254.169.254", "metadata.google.internal"} or host.startswith("169.254."):
        raise HTTPException(status_code=400, detail="Host is blocked.")
    try:
        port = int(req.port)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid port.")
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail="Invalid port.")
    if req.dbType not in ("postgresql", "mysql"):
        raise HTTPException(status_code=400, detail="Unsupported dbType.")
    if len(req.db or "") > 128 or len(req.user or "") > 128:
        raise HTTPException(status_code=400, detail="Invalid database/user.")
    try:
        from sqlalchemy import create_engine, text
        from core.secret_box import decrypt as _decrypt_secret

        password = req.password
        if password:
            try:
                password = _decrypt_secret(password)
            except Exception:
                pass

        if req.dbType == "mysql":
            url = f"mysql+pymysql://{quote_plus(str(req.user))}:{quote_plus(str(password))}@{req.host}:{req.port}/{req.db}"
        else:
            url = f"postgresql+psycopg2://{quote_plus(str(req.user))}:{quote_plus(str(password))}@{req.host}:{req.port}/{req.db}"

        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        return {"ok": True, "message": "Connection successful"}
    except Exception as e:
        from core.errors import sanitize_error

        return {"ok": False, "message": f"Connection failed: {sanitize_error(e)}"}



