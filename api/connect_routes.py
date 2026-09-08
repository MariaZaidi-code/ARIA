"""Data source connection routes: relational databases (PostgreSQL / MySQL) + CSV files + PDF documents."""

import json
import re
import time
import types
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import csv_orchestrator
import schema_agent
from core.config import DB_TYPES, PROVIDER_NAMES, SOURCE_TYPES, SCHEMA_DIR, PROCESSED_DIR, INSIGHTS_DIR, DATA_DIR, get_session, save_session
from core.db import build_db_uri
from core.deps import require_writable, get_current_user
from csv_handler import CsvValidationError
from llm_provider import create_provider
from document_processor import create_document_processor

router = APIRouter()

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
async def stream_upload_progress(user: dict = Depends(get_current_user)):
    """SSE stream of ingestion progress for the user."""
    async def event_stream():
        uid = user["user_id"]
        last_ts = 0
        for _ in range(300):  # max 5 minutes
            prog = _upload_progress.get(uid)
            if prog and prog.get("timestamp", 0) > last_ts:
                last_ts = prog["timestamp"]
                yield f"data: {json.dumps({k: v for k, v in prog.items() if k != 'timestamp'})}\n\n"
                if prog.get("done") or prog.get("error"):
                    break
            await asyncio.sleep(1)
    import asyncio
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

    session["provider"] = llm
    session["provider_name"] = request.provider
    if request.api_key:
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
    user_key = session.get("api_keys", {}).get(request.provider) if request.provider == "cloud" else None
    try:
        llm = create_provider(provider=request.provider, api_key=user_key or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{request.provider}' LLM provider: {exc}")

    # Preserve existing cloud provider if set — don't downgrade to local on reconnect.
    existing = session.get("provider")
    if existing and not isinstance(existing, str) and getattr(existing, "provider", None) == "cloud":
        session["provider"] = existing
    else:
        session["provider"] = llm
    session["source_type"] = request.source_type
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
        detail = f"Connection failed: {exc}"
        if db_type == "mysql":
            detail += (" Hint: is the MySQL server running, and is pymysql installed "
                       "(pip install pymysql)? Verify host/port, database, user, password.")
        else:
            detail += (" Hint: is the PostgreSQL service running on that host/port? "
                       "Verify the database name, user, and password are correct.")
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
    try:
        config = dict(session.get("db", {}))
        if "password" in config and config.get("password"):
            try:
                config["password"] = _decrypt_secret(config["password"])
            except Exception:
                pass
        conn = schema_agent.get_connection(types.SimpleNamespace(**config))
        try:
            db_type = session.get("db_type", "postgresql")
            schema_filter = config.get("db_schema", "public") if db_type == "postgresql" else config.get("db", "")
            mapping = schema_agent.build_schema_mapping(conn, schema_filter, db_type=db_type)
            conn.close()
            if mapping.get("tables"):
                user_schema_dir = SCHEMA_DIR / f"user_{user['user_id']}"
                user_schema_dir.mkdir(parents=True, exist_ok=True)
                safe_name_for_file = re.sub(r"[^a-zA-Z0-9_-]+", "_", db_name)[:64] or "db"
                user_path = user_schema_dir / f"schema_mapping_{safe_name_for_file}_latest.json"
                user_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
                session["schema_path"] = user_path
                save_session(user["user_id"], session)
        except Exception:
            pass
    except SystemExit:
        pass
    except Exception:
        pass

    _set_progress(uid, "ready", 100, "Connected", done=True)

    return {
        "ok": True,
        "provider": request.provider,
        "source_type": "relational",
        "database": db_name,
        "schema": current_db_schema,
        "db_type": db_type,
        "schema_file": session["schema_path"].name,
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

    upload_dir = DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(filename).stem)[:64] or "upload"
    file_path = upload_dir / f"{safe_name}_{stamp}{ext}"
    with open(file_path, 'wb') as _f:
        while True:
            _chunk = file.file.read(1024 * 1024)
            if not _chunk:
                break
            _f.write(_chunk)

    _set_progress(uid, "validating", 25, "Validating CSV structure...")

    try:
        table_name = csv_orchestrator.safe_table_name(safe_name)
        mapping = csv_orchestrator.build_csv_schema_mapping(file_path, table_name=table_name)
    except CsvValidationError as exc:
        _set_progress(uid, "error", 0, f"Invalid CSV: {exc}", error=str(exc))
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}")
    except Exception as exc:
        _set_progress(uid, "error", 0, f"Validation failed: {exc}", error=str(exc))
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"CSV processing failed: {exc}")

    _set_progress(uid, "extracting", 45, "Extracting schema and structure...")

    try:
        sqlite_path = upload_dir / f"{safe_name}_{stamp}.db"
        db_uri, table_name, row_count = csv_orchestrator.load_csv_to_sqlite(
            file_path, sqlite_path, table_name=table_name
        )
    except Exception as exc:
        _set_progress(uid, "error", 0, f"Processing failed: {exc}", error=str(exc))
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"CSV processing failed: {exc}")

    _set_progress(uid, "profiling", 65, f"Profiling {row_count} rows...")

    uid_dir = f"user_{uid}"
    safe_db_name = mapping["database"]
    schema_path = SCHEMA_DIR / uid_dir / f"schema_mapping_{safe_db_name}_latest.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    _set_progress(uid, "understanding", 80, "Understanding data structure...")

    session = get_session(uid)
    existing = session.get("provider")
    if existing and not isinstance(existing, str) and getattr(existing, "provider", None) == "cloud":
        session["provider"] = existing
    else:
        session["provider"] = llm
    session["source_type"] = "semi-structured"
    session["db"] = {".csv": str(file_path)}
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
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="No file received.")
    ext = Path(filename).suffix.lower()
    if ext != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Only .pdf files are accepted for document sources.",
        )
    
    try:
        llm = create_provider(provider=provider, api_key=llm_api_key, base_url=llm_base_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{provider}' LLM provider: {exc}")
    
    upload_dir = DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(filename).stem)[:64] or "upload"
    file_path = upload_dir / f"{safe_name}_{stamp}{ext}"
    with open(file_path, 'wb') as _f:
        while True:
            _chunk = file.file.read(1024 * 1024)
            if not _chunk:
                break
            _f.write(_chunk)
    
    # Create document processor
    processed_dir = PROCESSED_DIR / f"user_{user['user_id']}" / "documents"
    vector_index_dir = PROCESSED_DIR / f"user_{user['user_id']}" / "vector_store"
    
    processor = create_document_processor(
        upload_dir=upload_dir,
        processed_dir=processed_dir,
        llm_provider=llm if provider == "cloud" else None,
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
    existing = session.get("provider")
    if existing and not isinstance(existing, str) and getattr(existing, "provider", None) == "cloud":
        session["provider"] = existing
    else:
        session["provider"] = llm
    session["source_type"] = "document"
    session["db"] = {".pdf": str(file_path)}
    session["db_type"] = "document"
    session["db_uri"] = f"document://{document.id}"
    session["db_name"] = document.id
    session["dialect"] = "document"
    session["document_id"] = document.id
    session["document_type"] = document.document_type.value if document.document_type else "unknown"
    
    # Ensure processed directories exist
    processed_dir.mkdir(parents=True, exist_ok=True)
    vector_index_dir.mkdir(parents=True, exist_ok=True)
    
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
        "status": document.status.value,
        "processing_method": document.processing_method,
        "failed_pages": result.failed_pages,
        "warnings": result.warnings,
    }


@router.get("/api/session/status")
def session_status(user: dict = Depends(get_current_user)):
    """Return the current session's connectivity and DB info so the frontend can restore state."""
    session = get_session(user.get("user_id"))
    is_connected = bool(session.get("db") or session.get("db_uri") or session.get("source_type") == "semi-structured")
    return {
        "ok": True,
        "connection_status": "connected" if is_connected else "not-connected",
        "db_name": session.get("db_name", ""),
        "source_type": session.get("source_type", ""),
        "db_uri": session.get("db_uri", ""),
    }


class DatabaseTestRequest(BaseModel):
    host: str = "localhost"
    port: int = 5432
    db: str = ""
    user: str = ""
    password: str = ""
    dbType: str = "postgresql"


@router.post("/api/database/test")
async def test_database_connection(req: DatabaseTestRequest, _user: dict = Depends(get_current_user)):
    """Test a database connection before actually connecting."""
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
            url = f"mysql+pymysql://{req.user}:{password}@{req.host}:{req.port}/{req.db}"
        else:
            url = f"postgresql+psycopg2://{req.user}:{password}@{req.host}:{req.port}/{req.db}"

        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        return {"ok": True, "message": "Connection successful"}
    except Exception as e:
        return {"ok": False, "message": f"Connection failed: {str(e)}"}



