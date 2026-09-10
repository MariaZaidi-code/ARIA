"""CSV orchestration for ARIA: validated CSV -> SQLite + Goal-Agent schema mapping.

Composes Aryan's deterministic CSV handler (``csv_handler``) with the rest of
ARIA without modifying the Schema Agent or Goal Agent:

- ``build_csv_schema_mapping`` converts the CSV handler's profile into a schema
  mapping JSON in the ``tables`` format the Goal Agent consumes (columns /
  data_type / nullable / inferred_primary_key / row_count / empty).
- ``load_csv_to_sqlite`` loads the raw rows (typed, null-preserving) into a
  file-based SQLite database so the Goal Agent can execute SQL against it with
  ``dialect="sqlite"``, and the Insight Agent can analyse query results through
  the normal processed-data path.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from csv_handler import CsvSchemaExtractor

# Inferred logical types from the CSV handler -> SQLite storage types.
_SQLITE_TYPE = {
    "INTEGER": "INTEGER",
    "DECIMAL": "REAL",
    "BOOLEAN": "INTEGER",
    "DATE": "TEXT",
    "DATETIME": "TEXT",
    "STRING": "TEXT",
    "UNKNOWN": "TEXT",
}

_TRUE_TOKENS = {"true", "yes", "y", "1"}
_FALSE_TOKENS = {"false", "no", "n", "0"}

_INSERT_BATCH = 5_000

_DATE_NAME_HINTS = ("date", "time", "day", "month", "year", "created",
                    "updated", "timestamp", "period", "shipped", "ordered")

_SLASH_DATE_RE = re.compile(
    r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})"
    r"(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*"
)


def _resolve_slash_date_format(samples: list[str]) -> str | None:
    """Resolve ambiguous slash dates via the >12 rule.

    Returns "MDY"/"DMY", or None when inconsistent, contradictory, or fully
    ambiguous (all components ≤ 12 — guessing would fabricate meaning).
    """
    mdy_evidence = dmy_evidence = False
    seen = False
    for raw in samples:
        s = str(raw).strip()
        if not s:
            continue
        m = _SLASH_DATE_RE.fullmatch(s)
        if not m:
            return None
        seen = True
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b > 12:
            return None
        if a > 12:
            dmy_evidence = True
        elif b > 12:
            mdy_evidence = True
    if not seen or (mdy_evidence and dmy_evidence):
        return None
    if mdy_evidence:
        return "MDY"
    if dmy_evidence:
        return "DMY"
    return None


def _slash_to_iso(value: str, fmt: str) -> str | None:
    """Convert a resolved slash date to ISO (YYYY-MM-DD[ HH:MM:SS])."""
    m = _SLASH_DATE_RE.fullmatch(str(value).strip())
    if not m:
        return None
    a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    month, day = (a, b) if fmt == "MDY" else (b, a)
    if year < 100:
        year += 2000 if year < 70 else 1900
    hh, mm, ss = m.group(4), m.group(5), m.group(6)
    try:
        if hh is None:
            datetime(year, month, day)
            return f"{year:04d}-{month:02d}-{day:02d}"
        datetime(year, month, day, int(hh), int(mm), int(ss or 0))
        return f"{year:04d}-{month:02d}-{day:02d} {int(hh):02d}:{int(mm):02d}:{int(ss or 0):02d}"
    except ValueError:
        return None


def _normalize_date_columns(df, column_logical_types: dict) -> dict[str, str]:
    """Normalize resolvable non-ISO date columns to ISO in place.

    Only touches STRING columns with date-like names whose slash format is
    provably resolved. Ambiguous columns are left untouched (values preserved).
    Returns {column: note} for observability.
    """
    notes: dict[str, str] = {}
    for name, logical in column_logical_types.items():
        if logical != "STRING" or name not in df.columns:
            continue
        low = str(name).lower()
        if not any(h in low for h in _DATE_NAME_HINTS):
            continue
        samples = [v for v in df[name].dropna().astype(str).tolist() if v.strip()][:200]
        if not samples or any("-" in s and "/" not in s for s in samples[:5]):
            continue  # already ISO-like or empty
        fmt = _resolve_slash_date_format(samples)
        if not fmt:
            notes[name] = "non-ISO date format left as-is (ambiguous)"
            continue
        converted = 0
        iso_vals = []
        for v in df[name].tolist():
            if v is None or (isinstance(v, str) and not v.strip()):
                iso_vals.append(v)
                continue
            iso = _slash_to_iso(v, fmt)
            if iso is None:
                iso_vals.append(v)
            else:
                iso_vals.append(iso)
                converted += 1
        if converted:
            df[name] = iso_vals
            notes[name] = f"normalized {converted} values from {fmt} to ISO"
    return notes


def _safe_db_name(name: str) -> str:
    normalised = re.sub(r"[^0-9a-zA-Z]+", "_", str(name)).strip("_").lower()
    return normalised or "file_upload"


def safe_table_name(name: str) -> str:
    normalised = re.sub(r"[^0-9a-zA-Z]+", "_", str(name)).strip("_").lower()
    return normalised or "csv_table"


def build_csv_schema_mapping(csv_path: str | Path, table_name: str | None = None) -> dict[str, Any]:
    """Build a Goal-Agent-compatible schema mapping from a validated CSV file.

    Candidate keys detected by the CSV handler become ``inferred_primary_key``
    (they are suggested, never forced, matching the CSV handler's contract);
    ``row_count``/``empty`` let the Goal Agent distinguish truly empty tables.
    """
    extractor = CsvSchemaExtractor(csv_path)
    profile = extractor.extract()
    table = safe_table_name(table_name or profile["table_name"])

    columns: list[dict[str, Any]] = []
    null_stats: dict[str, dict[str, Any]] = {}
    inferred_pk: list[str] = []
    for column in profile["columns"]:
        name = column["name"]
        columns.append({
            "column": name,
            "data_type": _SQLITE_TYPE.get(column["inferred_type"], "TEXT"),
            "nullable": column["null_count"] > 0,
        })
        null_stats[name] = {
            "total_rows": profile["row_count"],
            "nulls": column["null_count"],
            "null_pct": column["null_percentage"],
        }
        if column["candidate_key"]:
            inferred_pk.append(name)

    tables_mapping = {
        table: {
            "columns": columns,
            "primary_key": [],
            "inferred_primary_key": inferred_pk,
            "null_stats": null_stats,
            "row_count": int(profile["row_count"]),
            "empty": int(profile["row_count"]) == 0,
            "source": str(csv_path),
            "csv_profile": {
                "size_bytes": profile["file"]["size_bytes"],
                "sha256": profile["file"]["sha256"],
                "encoding": profile["file"]["encoding"],
                "delimiter": profile["file"]["delimiter"],
                "quality": profile["quality"],
            },
        }
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "database": _safe_db_name(Path(csv_path).stem),
        "schema": "file",
        "tables": tables_mapping,
        "declared_relationships": [],
        "inferred_relationships": [],
        "relationship_edges": [],
        "semi_structured_sources": {
            str(csv_path): {"tables": sorted(tables_mapping)},
        },
    }


def _coerce_value(raw: Any, logical_type: str) -> Any:
    """Cast one raw string cell to its SQLite value (NULL for missing values).

    ``logical_type`` is the CSV handler's inferred type (INTEGER, DECIMAL,
    BOOLEAN, DATE, DATETIME, STRING, UNKNOWN) so bools are stored as 0/1 and
    identifiers/ISO dates stay as text.
    """
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if logical_type == "BOOLEAN":
        lowered = value.lower()
        if lowered in _TRUE_TOKENS:
            return 1
        if lowered in _FALSE_TOKENS:
            return 0
        return None
    if logical_type == "INTEGER":
        try:
            return int(value)
        except ValueError:
            return None
    if logical_type == "DECIMAL":
        try:
            return float(value)
        except ValueError:
            return None
    return value


def _quote_ident(name: str) -> str:
    """Quote a SQLite identifier safely (escape embedded double quotes)."""
    return '"' + str(name).replace('"', '""') + '"'


def load_csv_to_sqlite(csv_path: str | Path, sqlite_path: str | Path,
                       table_name: str | None = None) -> tuple[str, str, int]:
    """Load a validated CSV into a file-based SQLite database.

    Uses the CSV handler's detected encoding/dialect and inferred column
    types. Numeric and boolean columns are stored as INTEGER/REAL values so
    aggregate SQL works; date/string columns stay TEXT (ISO strings and
    identifiers with leading zeros are preserved); missing tokens are NULL.

    Returns (db_uri, table_name, row_count).
    """
    extractor = CsvSchemaExtractor(csv_path)
    profile = extractor.extract()
    df = extractor.load_dataframe()
    table = safe_table_name(table_name or profile["table_name"])

    sqlite_path = Path(sqlite_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        sqlite_path.unlink(missing_ok=True)
    except PermissionError:
        pass

    column_logical_types = {
        column["name"]: column["inferred_type"]
        for column in profile["columns"]
    }
    # Normalize provably-resolvable non-ISO dates to ISO so time SQL works.
    # Never breaks ingestion: wrapped defensively, ambiguous formats untouched.
    try:
        _date_notes = _normalize_date_columns(df, column_logical_types)
    except Exception:
        _date_notes = {}
    column_types = {
        name: _SQLITE_TYPE.get(logical, "TEXT")
        for name, logical in column_logical_types.items()
    }
    col_names = list(column_types)

    ddl_cols = ", ".join(f'{_quote_ident(name)} {column_types[name]}' for name in col_names)
    col_sql = ", ".join(_quote_ident(name) for name in col_names)
    placeholders = ", ".join("?" for _ in col_names)

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute(f'CREATE TABLE {_quote_ident(table)} ({ddl_cols})')
        batch: list[list[Any]] = []
        for record in df.to_dict(orient="records"):
            batch.append([_coerce_value(record.get(name), column_logical_types[name]) for name in col_names])
            if len(batch) >= _INSERT_BATCH:
                conn.executemany(
                    f'INSERT INTO {_quote_ident(table)} ({col_sql}) VALUES ({placeholders})',
                    batch,
                )
                batch = []
        if batch:
            conn.executemany(
                f'INSERT INTO {_quote_ident(table)} ({col_sql}) VALUES ({placeholders})',
                batch,
            )
        conn.commit()
    finally:
        conn.close()

    return f"sqlite:///{sqlite_path}", table, len(df)