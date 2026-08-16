"""Data source connection routes: relational databases + CSV/PDF file uploads."""

import json
import re
import types
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import schema_agent
from core.config import BASE_DIR, DB_TYPES, PROVIDER_NAMES, SOURCE_TYPES, SCHEMA_DIR, PROCESSED_DIR, INSIGHTS_DIR, get_session
from core.db import build_db_uri, safe_db_name
from core.deps import require_writable
from llm_provider import create_provider

router = APIRouter()


class ProviderSwitchRequest(BaseModel):
    provider: str = "local"
    api_key: str | None = None      # optional key override for hosted providers


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
    session = get_session(user["user_id"])
    if request.provider not in PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{request.provider}'. Choose from {sorted(PROVIDER_NAMES)}.")
    if request.source_type not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown source type '{request.source_type}'. Choose from {sorted(SOURCE_TYPES)}.")
    if request.source_type == "relational" and db_type not in DB_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown database type '{db_type}'. Choose from {sorted(DB_TYPES)}.")

    try:
        llm = create_provider(provider=request.provider)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{request.provider}' LLM provider: {exc}")

    session["provider"] = llm
    session["provider_name"] = request.provider
    session["source_type"] = request.source_type
    session["db"] = None
    session["db_type"] = db_type
    session["db_uri"] = None
    session["db_name"] = None
    uid_dir = f"user_{user['user_id']}"
    session["schema_path"] = SCHEMA_DIR / uid_dir / "schema_mapping_latest.json"
    session["processed_path"] = PROCESSED_DIR / uid_dir / "processed_data.json"
    session["insights_path"] = INSIGHTS_DIR / uid_dir / "insights.json"

    if request.source_type != "relational":
        return {
            "ok": True,
            "provider": request.provider,
            "source_type": request.source_type,
            "routed_to": "semi-structured-module (CSV/PDF extractor)",
            "note": "Semi-structured handling is orchestrated but implemented in the CSV/PDF module (group scope).",
        }

    if not (request.db and request.user and request.password is not None):
        raise HTTPException(status_code=400, detail="Relational source requires db, user, and password.")

    config = request.model_dump()
    config["db_type"] = db_type
    config["port"] = int(config["port"])
    try:
        conn = schema_agent.get_connection(types.SimpleNamespace(**config))
        with conn.cursor() as cur:
            if db_type == "mysql":
                cur.execute("SELECT DATABASE();")
                db_name = cur.fetchone()[0]
                current_db_schema = db_name
            else:
                cur.execute("SELECT current_database(), current_schema();")
                db_name, current_db_schema = cur.fetchone()
        conn.close()
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        detail = f"Connection failed: {exc}"
        if db_type == "mysql":
            detail += (" Hint: is the MySQL server running, and is pymysql installed "
                       "(pip install pymysql)? Verify host/port, database, user, password.")
        else:
            detail += (" Hint: is the PostgreSQL service running on that host/port? "
                       "Verify the database name, user, and password are correct.")
        raise HTTPException(status_code=400, detail=detail)

    session["db"] = config
    session["db_type"] = db_type
    session["db_uri"] = build_db_uri(config, db_type)
    session["db_name"] = db_name
    session["dialect"] = db_type

    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", db_name)
    uid_dir = f"user_{user['user_id']}"
    session["schema_path"] = SCHEMA_DIR / uid_dir / "schema_mapping_latest.json"
    session["processed_path"] = PROCESSED_DIR / uid_dir / f"processed_data_{safe}.json"
    session["insights_path"] = INSIGHTS_DIR / uid_dir / f"insights_{safe}.json"

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


def _do_connect_file(user: dict, provider: str, file: UploadFile) -> dict:
    """Shared file-source connect logic for CSV / tabular PDF uploads."""
    session = get_session(user["user_id"])
    if provider not in PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'. Choose from {sorted(PROVIDER_NAMES)}.")

    ext = Path(file.filename).suffix.lower() if file and file.filename else ""
    if ext not in (".csv", ".pdf"):
        raise HTTPException(status_code=400, detail="Only .csv and .pdf files are accepted. Please select a supported file.")

    try:
        llm = create_provider(provider=provider)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{provider}' LLM provider: {exc}")

    upload_dir = BASE_DIR / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(file.filename).stem) or "upload"
    file_path = upload_dir / f"{safe_name}_{stamp}{ext}"
    file_path.write_bytes(file.file.read())

    try:
        if ext == ".csv":
            database = safe_db_name(safe_name)
            mapping = schema_agent.build_csv_schema(file_path, database)
            sqlite_path = upload_dir / f"{safe_name}_{stamp}.db"
            db_uri, table_name, _row_count = schema_agent.load_csv_to_sqlite(file_path, sqlite_path, database)
            tables = {table_name: _row_count}
            primary = table_name
            file_type = "csv"
            mapping = schema_agent.enrich_with_llm(mapping, llm)
        else:
            tables_df = schema_agent.extract_pdf_tables(file_path)
            if not tables_df:
                if schema_agent.pdf_has_text(file_path):
                    raise RuntimeError("No tables found in the PDF. Only tabular (report-style) PDFs are supported.")
                if provider != "cloud":
                    raise RuntimeError(
                        "This PDF looks scanned/handwritten. Extracting it requires the Cloud provider "
                        "(Groq vision model) — select Cloud and retry."
                    )
                try:
                    tables_df = schema_agent.extract_handwritten_pdf(file_path, llm)
                except RuntimeError as exc:
                    raise HTTPException(status_code=400, detail=str(exc))
                if not tables_df:
                    raise RuntimeError("No records could be read from the handwritten PDF. The file was rejected.")
            database = safe_db_name(safe_name)
            mapping = schema_agent.build_tables_schema(tables_df, file_path, database)
            sqlite_path = upload_dir / f"{safe_name}_{stamp}.db"
            db_uri, loaded = schema_agent.load_tables_to_sqlite(tables_df, sqlite_path)
            tables = dict(loaded)
            table_name = database
            primary = sorted(tables)[0]
            file_type = "pdf"
            mapping = schema_agent.enrich_with_llm(mapping, llm)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"File processing failed: {exc}")

    schema_path, snapshot_path, latest_path, snapshot_id = schema_agent.get_output_paths(
        str(SCHEMA_DIR / f"user_{user['user_id']}" / "schema_mapping.json"),
        db_name=safe_name or table_name,
        snapshot_id=mapping.get("snapshot_id"),
    )
    mapping["snapshot_id"] = snapshot_id
    for path in (schema_path, snapshot_path, latest_path):
        path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    schema_path = latest_path

    session["provider"] = llm
    session["provider_name"] = provider
    session["source_type"] = "semi-structured"
    session["file_type"] = file_type
    session["db"] = {ext: str(file_path)}
    session["db_uri"] = db_uri
    session["db_name"] = table_name
    session["schema_path"] = schema_path
    session["processed_path"] = PROCESSED_DIR / f"user_{user['user_id']}" / f"processed_data_{safe_name}.json"
    session["insights_path"] = INSIGHTS_DIR / f"user_{user['user_id']}" / f"insights_{safe_name}.json"
    session["dialect"] = "sqlite"

    columns = [c["column"] for c in mapping["tables"][primary]["columns"]]
    return {
        "ok": True,
        "provider": provider,
        "source_type": "semi-structured",
        "file": file.filename,
        "type": file_type,
        "tables": tables,
        "table": primary,
        "rows": sum(tables.values()),
        "columns": columns,
        "schema_file": schema_path.name,
    }


@router.post("/api/connect_file")
def connect_file(provider: str = Form("local"), file: UploadFile = File(...),
                 user: dict = Depends(require_writable)):
    """Connect a semi-structured source: a CSV or a tabular PDF file."""
    return _do_connect_file(user, provider, file)
