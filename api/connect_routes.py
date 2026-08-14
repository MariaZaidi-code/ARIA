"""Data source connection routes: relational databases + CSV/PDF file uploads."""

import json
import re
import types
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import schema_agent
from core.config import BASE_DIR, DB_TYPES, PROVIDER_NAMES, SOURCE_TYPES, SESSION
from core.db import build_db_uri, safe_db_name
from core.deps import require_writable
from llm_provider import create_provider

router = APIRouter()


class ProviderSwitchRequest(BaseModel):
    provider: str = "local"
    api_key: str | None = None      # optional override for hosted providers
    base_url: str | None = None     # optional base URL for 'openai_compat'


@router.post("/api/provider/switch")
def switch_provider(request: ProviderSwitchRequest, user: dict = Depends(require_writable)):
    """Explicitly switch the LLM backend for this session.

    POLICY: there are NO automatic backend fallbacks. Switching to a hosted
    provider only happens through this endpoint, which the frontend calls AFTER
    the user confirms the privacy trade-off in a dialog. Local is never upgraded
    to a hosted backend silently, and a hosted backend is never downgraded to
    Local silently.
    """
    if request.provider not in PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{request.provider}'. Choose from {sorted(PROVIDER_NAMES)}.")
    current = SESSION.get("provider_name")
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

    SESSION["provider"] = llm
    SESSION["provider_name"] = request.provider
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
    llm_api_key: str | None = None   # optional key override for hosted providers
    llm_base_url: str | None = None  # optional base URL for 'openai_compat'


@router.post("/api/connect")
def connect(request: ConnectRequest, user: dict = Depends(require_writable)):
    """Connect to a source.

    - relational      -> Schema Agent path (handled here)
    - semi-structured -> routed to the other engine (group member's scope),
                         only orchestrated here.
    """
    if request.provider not in PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{request.provider}'. Choose from {sorted(PROVIDER_NAMES)}.")
    if request.source_type not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown source type '{request.source_type}'. Choose from {sorted(SOURCE_TYPES)}.")
    if request.source_type == "relational" and request.db_type not in DB_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown database type '{request.db_type}'. Choose from {sorted(DB_TYPES)}.")

    # Build the LLM provider for the chosen backend.
    try:
        llm = create_provider(
            provider=request.provider,
            api_key=request.llm_api_key,
            base_url=request.llm_base_url,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{request.provider}' LLM provider: {exc}")

    SESSION["provider"] = llm
    SESSION["provider_name"] = request.provider
    SESSION["source_type"] = request.source_type
    SESSION["db"] = None
    SESSION["db_type"] = "postgresql"
    SESSION["db_uri"] = None
    SESSION["db_name"] = None
    # Per-database schema file: reset until the DB is resolved below.
    SESSION["schema_path"] = BASE_DIR / "schema_mapping_latest.json"
    SESSION["processed_path"] = BASE_DIR / "processed_data.json"
    SESSION["insights_path"] = BASE_DIR / "insights.json"

    if request.source_type != "relational":
        # Orchestration point for CSV/PDF: the actual file handling lives in
        # POST /api/connect_file below; this branch is kept for the old flow.
        return {
            "ok": True,
            "provider": request.provider,
            "source_type": request.source_type,
            "routed_to": "semi-structured-module (CSV/PDF extractor)",
            "note": "Semi-structured handling is orchestrated but implemented in the CSV/PDF module (group scope).",
        }

    # Relational: verify the PostgreSQL connection.
    if not (request.db and request.user and request.password is not None):
        raise HTTPException(status_code=400, detail="Relational source requires db, user, and password.")

    config = request.model_dump()
    config["port"] = int(config["port"])
    try:
        conn = schema_agent.get_connection(types.SimpleNamespace(**config))
        with conn.cursor() as cur:
            if request.db_type == "mysql":
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
        raise HTTPException(status_code=400, detail=f"Connection failed: {exc}")

    SESSION["db"] = config
    SESSION["db_type"] = request.db_type
    SESSION["db_uri"] = build_db_uri(config, request.db_type)
    SESSION["db_name"] = db_name
    SESSION["dialect"] = request.db_type

    # A fresh schema JSON is (re)created per connected database below in
    # /api/extract_schema; here we just prepare its path.
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", db_name)
    per_db_path = BASE_DIR / f"schema_mapping_{safe}_latest.json"
    # Restore a previously extracted mapping for this database if one exists,
    # so reconnecting does not silently drop an already-extracted schema.
    SESSION["schema_path"] = per_db_path if per_db_path.exists() else BASE_DIR / "schema_mapping_latest.json"
    SESSION["processed_path"] = BASE_DIR / f"processed_data_{safe}.json"
    SESSION["insights_path"] = BASE_DIR / f"insights_{safe}.json"

    return {
        "ok": True,
        "provider": request.provider,
        "source_type": "relational",
        "database": db_name,
        "schema": current_db_schema,
        "schema_file": SESSION["schema_path"].name,
    }


@router.post("/api/connect_file")
def connect_file(provider: str = Form("local"), file: UploadFile = File(...),
                 llm_api_key: str | None = Form(None),
                 llm_base_url: str | None = Form(None),
                 user: dict = Depends(require_writable)):
    """Connect a semi-structured source: upload a CSV or tabular PDF file.

    The file is validated, its schema is inferred deterministically, the rows are
    loaded into a file-based SQLite database, and the session is pointed at it so
    the Goal Agent can query it with the same pipeline as relational data.
    """
    if provider not in PROVIDER_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'. Choose from {sorted(PROVIDER_NAMES)}.")

    if not file or not (file.filename or "").lower().endswith((".csv", ".pdf")):
        raise HTTPException(status_code=400, detail="Only .csv and .pdf files are accepted. Please select a CSV or PDF file.")

    try:
        llm = create_provider(provider=provider, api_key=llm_api_key, base_url=llm_base_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not initialise '{provider}' LLM provider: {exc}")

    upload_dir = BASE_DIR / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(file.filename).stem) or "upload"
    ext = Path(file.filename).suffix.lower()
    file_path = upload_dir / f"{safe_name}_{stamp}{ext}"
    file_path.write_bytes(file.file.read())

    try:
        if ext == ".csv":
            mapping = schema_agent.build_csv_schema(file_path)
            table_name = next(iter(mapping["tables"]))
            sqlite_path = upload_dir / f"{safe_name}_{stamp}.db"
            db_uri, table_name, row_count = schema_agent.load_csv_to_sqlite(file_path, sqlite_path, table_name)
            tables = {table_name: row_count}
            primary = table_name
        else:
            tables_df = schema_agent.extract_pdf_tables(file_path)
            if not tables_df:
                if schema_agent.pdf_has_text(file_path):
                    raise RuntimeError("No tables found in the PDF. Only tabular (report-style) PDFs are supported.")
                # No text layer -> scanned/handwritten: requires the cloud vision model.
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
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"File processing failed: {exc}")

    schema_path = BASE_DIR / f"schema_mapping_{safe_name}_latest.json"
    schema_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    SESSION["provider"] = llm
    SESSION["provider_name"] = provider
    SESSION["source_type"] = "semi-structured"
    SESSION["db"] = {ext: str(file_path)}
    SESSION["db_uri"] = db_uri
    SESSION["db_name"] = table_name
    SESSION["schema_path"] = schema_path
    SESSION["processed_path"] = BASE_DIR / f"processed_data_{safe_name}.json"
    SESSION["insights_path"] = BASE_DIR / f"insights_{safe_name}.json"
    SESSION["dialect"] = "sqlite"

    columns = [c["column"] for c in mapping["tables"][primary]["columns"]]
    return {
        "ok": True,
        "provider": provider,
        "source_type": "semi-structured",
        "file": file.filename,
        "type": ext.lstrip("."),
        "tables": tables,
        "table": primary,
        "rows": sum(tables.values()),
        "columns": columns,
        "schema_file": schema_path.name,
    }
