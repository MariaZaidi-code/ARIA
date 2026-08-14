"""Schema Agent routes: schema extraction and retrieval."""

import json
import types

from fastapi import APIRouter, Depends, HTTPException

import schema_agent
from core.config import BASE_DIR, SESSION
from core.deps import get_current_user, require_data, require_writable

router = APIRouter()


@router.post("/api/extract_schema")
def extract_schema(user: dict = Depends(require_writable)):
    """Run the Schema Agent against the connected source."""
    require_data()

    # CSV schema is already inferred at upload time.
    if SESSION["source_type"] != "relational":
        mapping = json.loads(SESSION["schema_path"].read_text(encoding="utf-8"))
        return {
            "ok": True,
            "provider": SESSION["provider_name"],
            "snapshot_id": mapping.get("snapshot_id"),
            "tables": len(mapping.get("tables", {})),
            "declared_relationships": len(mapping.get("declared_relationships", [])),
            "inferred_relationships": len(mapping.get("inferred_relationships", [])),
            "source": "csv",
        }

    config = SESSION["db"]
    db_type = SESSION.get("db_type", "postgresql")
    # MySQL has no separate schema: its "schema" IS the database name.
    schema_filter = config["db"] if db_type == "mysql" else config["db_schema"]
    try:
        conn = schema_agent.get_connection(types.SimpleNamespace(**config))
        try:
            mapping = schema_agent.build_schema_mapping(conn, schema_filter, db_type=db_type)
            # If the configured schema is empty (e.g. the UI default "public"
            # while the data lives in another schema), fall back to the first
            # non-system schema that actually contains tables.
            if not mapping.get("tables") and db_type == "postgresql":
                fallback = schema_agent.find_schema_with_tables(conn)
                if fallback != schema_filter:
                    mapping = schema_agent.build_schema_mapping(conn, fallback, db_type=db_type)
            mapping["database"] = SESSION["db_name"]
        finally:
            conn.close()
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Schema extraction failed: {exc}")

    # Fresh per-database schema files: canonical + latest + timestamped snapshot.
    output_path, _ts_path, latest_path = schema_agent.get_output_paths(
        str(BASE_DIR / "schema_mapping.json"), db_name=SESSION["db_name"]
    )
    for path in (output_path, latest_path, _ts_path):
        path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    # Point the session at this database's schema file so the Goal Agent
    # uses the correct mapping (not a previous database's).
    SESSION["schema_path"] = latest_path

    return {
        "ok": True,
        "provider": SESSION["provider_name"],
        "snapshot_id": mapping["snapshot_id"],
        "tables": len(mapping["tables"]),
        "declared_relationships": len(mapping["declared_relationships"]),
        "inferred_relationships": len(mapping["inferred_relationships"]),
    }


@router.get("/api/schema")
def get_schema(user: dict = Depends(get_current_user)):
    """Return the current schema mapping (tables, columns, relationships)."""
    require_data()
    path = SESSION["schema_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="No schema extracted yet. Call POST /api/extract_schema first.")
    return json.loads(path.read_text(encoding="utf-8"))
