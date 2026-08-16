"""Schema Agent routes: schema extraction and retrieval."""

import json
import types

from fastapi import APIRouter, Depends, HTTPException, Request

import schema_agent
from core.config import SCHEMA_DIR, get_session
from core.deps import get_current_user, require_data, require_writable

router = APIRouter()


def _extract_schema_impl(request: Request, user: dict, db_type: str = "postgresql") -> dict:
    """Run the Schema Agent against the connected source for `db_type`.

    For file sources (CSV / PDF) the mapping was already built at connect time,
    so this returns the saved mapping counts.
    """
    session = get_session(user["user_id"])
    require_data(request)

    if session["source_type"] != "relational":
        mapping = json.loads(session["schema_path"].read_text(encoding="utf-8"))
        return {
            "ok": True,
            "provider": session["provider_name"],
            "snapshot_id": mapping.get("snapshot_id"),
            "tables": len(mapping.get("tables", {})),
            "declared_relationships": len(mapping.get("declared_relationships", [])),
            "inferred_relationships": len(mapping.get("inferred_relationships", [])),
            "source": session.get("file_type") or "file",
        }

    session_db_type = session.get("db_type") or "postgresql"
    if db_type != session_db_type:
        raise HTTPException(
            status_code=400,
            detail=f"Schema extraction endpoint /api/extract_schema/{db_type} requires a {db_type} "
                   f"connection, but the session is connected to {session_db_type}. "
                   f"Re-connect via /api/connect/{db_type} first.",
        )

    config = session["db"]
    schema_filter = config["db"] if db_type == "mysql" else config["db_schema"]
    try:
        conn = schema_agent.get_connection(types.SimpleNamespace(**config))
        try:
            mapping = schema_agent.build_schema_mapping(
                conn, schema_filter, db_type=db_type, llm=session.get("provider")
            )
            if not mapping.get("tables"):
                hint = ""
                if db_type == "postgresql":
                    try:
                        alt = schema_agent.find_schema_with_tables(conn)
                        if alt and alt != schema_filter:
                            hint = f" (tables were found in schema '{alt}' instead)"
                    except Exception:
                        pass
                raise HTTPException(
                    status_code=400,
                    detail=f"No tables found in {db_type} schema '{schema_filter}'. "
                           f"The schema is empty or does not exist{hint}; nothing was mapped.",
                )
            mapping["database"] = session["db_name"]
        finally:
            conn.close()
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Schema extraction failed: {exc}")

    user_schema_dir = SCHEMA_DIR / f"user_{user['user_id']}"
    output_path, snapshot_path, latest_path, snapshot_id = schema_agent.get_output_paths(
        str(user_schema_dir / "schema_mapping.json"),
        db_name=session["db_name"],
        snapshot_id=mapping.get("snapshot_id"),
    )
    mapping["snapshot_id"] = snapshot_id
    for path in (output_path, snapshot_path, latest_path):
        path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    session["schema_path"] = latest_path

    return {
        "ok": True,
        "provider": session["provider_name"],
        "snapshot_id": mapping["snapshot_id"],
        "tables": len(mapping["tables"]),
        "declared_relationships": len(mapping["declared_relationships"]),
        "inferred_relationships": len(mapping["inferred_relationships"]),
    }


@router.post("/api/extract_schema")
def extract_schema(request: Request, user: dict = Depends(require_writable)):
    """Run the Schema Agent against the connected source (db type from session)."""
    session = get_session(user["user_id"])
    return _extract_schema_impl(request, user, session.get("db_type") or "postgresql")


@router.post("/api/extract_schema/postgresql")
def extract_schema_postgresql(request: Request, user: dict = Depends(require_writable)):
    """Run the Schema Agent for a PostgreSQL source (explicit route)."""
    return _extract_schema_impl(request, user, "postgresql")


@router.post("/api/extract_schema/mysql")
def extract_schema_mysql(request: Request, user: dict = Depends(require_writable)):
    """Run the Schema Agent for a MySQL source (explicit route)."""
    return _extract_schema_impl(request, user, "mysql")


@router.get("/api/schema")
def get_schema(request: Request, user: dict = Depends(get_current_user)):
    """Return the current schema mapping (tables, columns, relationships)."""
    session = get_session(user["user_id"])
    require_data(request)
    path = session["schema_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="No schema extracted yet. Call POST /api/extract_schema first.")
    return json.loads(path.read_text(encoding="utf-8"))
