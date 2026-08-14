"""Shared application configuration and the single in-memory session state."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
SCHEMA_PATH = BASE_DIR / "schema_mapping_latest.json"
PROCESSED_PATH = BASE_DIR / "processed_data.json"
INSIGHTS_PATH = BASE_DIR / "insights.json"

SOURCE_TYPES = {"relational", "semi-structured"}
PROVIDER_NAMES = {"local", "cloud", "openai_compat"}
DB_TYPES = {"postgresql", "mysql"}

# Global in-memory session state describing the currently connected source.
# Shared across all users for now; a per-user session is a future refinement.
SESSION = {
    "provider": None,       # LLMProvider instance
    "provider_name": None,  # 'local' | 'cloud' | 'openai_compat'
    "source_type": None,    # 'relational' | 'semi-structured'
    "db": None,             # relational DB config
    "db_type": "postgresql",  # 'postgresql' | 'mysql' (relational sources only)
    "db_uri": None,
    "db_name": None,        # name of the connected database / table
    "schema_path": SCHEMA_PATH,   # schema file for the active database
    "processed_path": PROCESSED_PATH,
    "insights_path": INSIGHTS_PATH,
    "dialect": "postgresql",     # 'postgresql'|'mysql' for relational, 'sqlite' for CSV/PDF
    "pending_history_id": None,  # most recent history row awaiting insights
}
