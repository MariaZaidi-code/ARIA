"""
ARIA Schema Agent
-----------------
Role: Data Understanding

Runs once (or on schema change) to parse and map messy/undocumented relational
databases and semi-structured (JSON/CSV/PDF) sources. It identifies tables,
columns, data types, null patterns, primary keys, declared foreign keys, and
INFERRED relationships for columns that look like foreign keys but have no
formal constraint declared.

Semi-structured sources (JSON/CSV/PDF) are parsed with the Qwen3-4B model via
Ollama, which extracts entities/fields and maps them into the unified schema.
Qwen3-4B is used exclusively here — never for SQL generation or storytelling.

Output: schema_mapping.json  (single source of truth for the Goal Agent)

Usage:
    python schema_agent.py
    python schema_agent.py --json-source reports/export.json --csv-source exports/stock.csv
    python schema_agent.py --host localhost --port 5432 --db northwind --user postgres --password 12345
"""

import argparse
import json
import os
import re
import sys
import csv
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from psycopg2 import sql

try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from llm_provider import LLMProvider, create_provider


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------

def get_connection(args):
    """Build a database connection (PostgreSQL or MySQL) from CLI args / env vars."""
    db_type = getattr(args, "db_type", None) or "postgresql"
    host = args.host or os.getenv("DB_HOST", "localhost")
    port = args.port or os.getenv("DB_PORT", "5432" if db_type == "postgresql" else "3306")
    dbname = args.db or os.getenv("DB_NAME")
    user = args.user or os.getenv("DB_USER")
    password = args.password or os.getenv("DB_PASSWORD")

    missing = [name for name, val in
               [("database", dbname), ("user", user), ("password", password)]
               if not val]
    if missing:
        sys.exit(
            f"ERROR: missing required connection info: {', '.join(missing)}.\n"
            f"Set them via .env or pass --db --user --password on the command line."
        )

    if db_type == "mysql":
        if not MYSQL_AVAILABLE:
            sys.exit("ERROR: pymysql is not installed. Run: pip install pymysql")
        try:
            conn = pymysql.connect(
                host=host, port=int(port), user=user, password=password,
                database=dbname, charset="utf8mb4", connect_timeout=10,
            )
        except pymysql.MySQLError as e:
            sys.exit(f"ERROR: could not connect to MySQL database: {e}")
        return conn

    try:
        conn = psycopg2.connect(
            host=host, port=port, dbname=dbname, user=user, password=password,
            connect_timeout=10,
        )
    except psycopg2.OperationalError as e:
        sys.exit(f"ERROR: could not connect to database: {e}")

    return conn


def _dict_cursor(conn, db_type="postgresql"):
    """Return a dictionary-row cursor for the connected database type."""
    if db_type == "mysql":
        return conn.cursor(pymysql.cursors.DictCursor)
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _quote_ident(db_type, name):
    """Return a SQL-safe quoted identifier (double quotes for PG, backticks for MySQL)."""
    if db_type == "mysql":
        return "`" + str(name).replace("`", "") + "`"
    return str(name)


# ---------------------------------------------------------------------------
# Metadata extraction (pure SQL, no LLM)
# ---------------------------------------------------------------------------

def get_tables_and_columns(conn, schema="public", db_type="postgresql"):
    """Return {table_name: [{column, data_type, nullable}, ...]}"""
    query = """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position;
    """
    with _dict_cursor(conn, db_type) as cur:
        cur.execute(query, (schema,))
        rows = cur.fetchall()

    tables = {}
    for row in rows:
        tables.setdefault(row["table_name"], []).append({
            "column": row["column_name"],
            "data_type": row["data_type"],
            "nullable": row["is_nullable"] == "YES",
        })
    return tables


def get_primary_keys(conn, schema="public", db_type="postgresql"):
    """Return {table_name: [pk_column, ...]}"""
    query = """
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s;
    """
    with _dict_cursor(conn, db_type) as cur:
        cur.execute(query, (schema,))
        rows = cur.fetchall()

    pks = {}
    for row in rows:
        pks.setdefault(row["table_name"], []).append(row["column_name"])
    return pks


def get_declared_foreign_keys(conn, schema="public", db_type="postgresql"):
    """Return list of {table_name, column_name, references_table, references_column}"""
    if db_type == "mysql":
        # MySQL exposes the referenced table/column directly on key_column_usage.
        query = """
            SELECT
                kcu.table_name AS table_name,
                kcu.column_name AS column_name,
                kcu.referenced_table_name AS references_table,
                kcu.referenced_column_name AS references_column
            FROM information_schema.key_column_usage kcu
            WHERE kcu.referenced_table_name IS NOT NULL
              AND kcu.table_schema = %s;
        """
    else:
        query = """
            SELECT
                tc.table_name AS table_name,
                kcu.column_name AS column_name,
                ccu.table_name AS references_table,
                ccu.column_name AS references_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s;
        """
    with _dict_cursor(conn, db_type) as cur:
        cur.execute(query, (schema,))
        return [dict(row) for row in cur.fetchall()]


def get_null_stats(conn, tables, schema="public", db_type="postgresql"):
    """Return {table_name: {column_name: {"total_rows": n, "nulls": n, "null_pct": p}}}"""
    stats = {}
    with conn.cursor() as cur:
        for table_name, columns in tables.items():
            table_stats = {}
            if db_type == "mysql":
                qualified = f"{_quote_ident(db_type, schema)}.{_quote_ident(db_type, table_name)}"
                cur.execute(f"SELECT COUNT(*) FROM {qualified}")
                total_rows = cur.fetchone()[0]

                for col in columns:
                    col_name = col["column"]
                    qcol = _quote_ident(db_type, col_name)
                    cur.execute(
                        f"SELECT COUNT(*) - COUNT({qcol}) FROM {qualified}"
                    )
                    nulls = cur.fetchone()[0]
                    null_pct = round((nulls / total_rows) * 100, 2) if total_rows else 0.0
                    table_stats[col_name] = {
                        "total_rows": total_rows,
                        "nulls": nulls,
                        "null_pct": null_pct,
                    }
            else:
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.{}")
                       .format(sql.Identifier(schema), sql.Identifier(table_name))
                )
                total_rows = cur.fetchone()[0]

                for col in columns:
                    col_name = col["column"]
                    cur.execute(
                        sql.SQL("SELECT COUNT(*) - COUNT({}) FROM {}.{}")
                           .format(sql.Identifier(col_name), sql.Identifier(schema), sql.Identifier(table_name))
                    )
                    nulls = cur.fetchone()[0]
                    null_pct = round((nulls / total_rows) * 100, 2) if total_rows else 0.0
                    table_stats[col_name] = {
                        "total_rows": total_rows,
                        "nulls": nulls,
                        "null_pct": null_pct,
                    }
            stats[table_name] = table_stats
    return stats


# ---------------------------------------------------------------------------
# Heuristic relationship inference (fills the gap for "messy" databases)
# ---------------------------------------------------------------------------

def normalize_identifier(value):
    """Normalize names to compare database identifiers across styles."""
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def infer_primary_keys(tables, declared_primary_keys):
    """Return likely PKs when the database does not declare them explicitly."""
    inferred = {}

    for table_name, columns in tables.items():
        if declared_primary_keys.get(table_name):
            inferred[table_name] = declared_primary_keys[table_name]
            continue

        candidates = []
        for col in columns:
            col_name = col["column"]
            normalized = normalize_identifier(col_name)
            if normalized == "id" or normalized == normalize_identifier(table_name) + "id":
                candidates.append(col_name)

        if len(candidates) == 1:
            inferred[table_name] = candidates
            continue

        non_null_columns = [col["column"] for col in columns if not col["nullable"]]
        if len(non_null_columns) == 1:
            inferred[table_name] = non_null_columns
            continue

        id_like = [col["column"] for col in columns if col["column"].lower().endswith("_id") or col["column"].lower() == "id"]
        if len(id_like) == 1:
            inferred[table_name] = id_like

    return inferred


def infer_relationships(tables, primary_keys, declared_fks):
    """
    For every column that looks like a foreign key (ends in _id, or matches
    another table's primary key column name) but has NO declared FK constraint,
    propose an inferred relationship.
    """
    declared_pairs = {(fk["table_name"], fk["column_name"]) for fk in declared_fks}

    pk_owner = {}
    table_pk = {}
    for table_name, pk_cols in primary_keys.items():
        table_pk[table_name] = pk_cols
        for pk_col in pk_cols:
            pk_owner.setdefault(pk_col, []).append(table_name)

    def table_name_candidates(col_name):
        """For 'X_id', return tables whose name (singular or plural) is X."""
        if not col_name.endswith("_id"):
            return []
        base = col_name[:-3].lower()
        return [
            t for t in tables
            if t.lower() in (base, base + "s", base + "es")
        ]

    inferred = []
    for table_name, columns in tables.items():
        for col in columns:
            col_name = col["column"]

            if (table_name, col_name) in declared_pairs:
                continue
            if col_name in primary_keys.get(table_name, []):
                continue
            if not (col_name.endswith("_id") or col_name.endswith("id") or col_name.lower() == "id"):
                continue

            candidate_tables = set(pk_owner.get(col_name, []))
            table_cands = set(table_name_candidates(col_name))
            if not table_cands:
                # Fallback: exact same-name column match, only when unambiguous.
                same_name = [
                    other_table
                    for other_table, other_cols in tables.items()
                    if other_table != table_name
                    for other_col in other_cols
                    if normalize_identifier(col_name) == normalize_identifier(other_col["column"])
                ]
                if len(same_name) == 1:
                    candidate_tables.update(same_name)
            candidate_tables.update(table_cands)
            candidate_tables.discard(table_name)

            for candidate_table in sorted(candidate_tables):
                ref_cols = table_pk.get(candidate_table) or [col_name]
                for ref_col in ref_cols:
                    inferred.append({
                        "table": table_name,
                        "column": col_name,
                        "references_table": candidate_table,
                        "references_column": ref_col,
                        "confidence": "heuristic-name-match",
                        "note": "No FK constraint declared in the database; relationship inferred from column naming convention.",
                    })
    return inferred


# ---------------------------------------------------------------------------
# Semi-structured source extraction (JSON / CSV / PDF) via Qwen3-4B
# ---------------------------------------------------------------------------

def _read_sample_rows(path, max_rows=20):
    """Return a small text sample of a JSON or CSV file for LLM extraction."""
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = [row for _, row in zip(range(max_rows + 1), reader)]
        if not rows:
            return ""
        return "\n".join("|".join(r) for r in rows)

    if suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return content[:4000]

    # PDF or anything else: fall back to the first chunk of raw text.
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()[:4000]


def extract_semi_structured_schema(source_path, model=None, llm=None):
    """
    Ask the configured LLM (Qwen3 locally, Llama via Groq) to extract
    entities/fields from a semi-structured source and map them to the unified
    schema. Returns a dict describing the discovered table(s) plus declared
    relationships from the source.
    """
    llm = llm or create_provider()
    sample = _read_sample_rows(source_path)
    if not sample:
        print(f"WARNING: could not read sample from {source_path}")
        return {}

    prompt = f"""
You are the Schema Agent of a BI system. Analyse the following semi-structured
data sample and extract its schema. Return JSON only (no markdown) with this shape:
{{
  "tables": {{
    "table_name": {{
      "columns": [{{"column": "...", "data_type": "...", "nullable": true}}],
      "primary_key": ["..."],
      "source": "filename"
    }}
  }},
  "relationships": [{{"table": "...", "column": "...", "references_table": "...", "references_column": "..."}}]
}}

Data sample:
{sample}
"""
    try:
        content = llm.chat("semi", messages=[{"role": "user", "content": prompt}],
                           temperature=0.0, num_predict=800)
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        return json.loads(content)
    except Exception as exc:
        print(f"WARNING: semi-structured extraction failed for {source_path}: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Assemble & write schema_mapping.json
# ---------------------------------------------------------------------------

def find_schema_with_tables(conn):
    """Return the first non-system Postgres schema that contains tables."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND table_schema NOT LIKE 'pg_%'
              AND table_schema <> 'public'
            GROUP BY table_schema
            ORDER BY count(*) DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return row[0] if row else "public"


def build_schema_mapping(conn, schema="public", semi_sources=None, db_type="postgresql"):
    tables = get_tables_and_columns(conn, schema, db_type)
    primary_keys = get_primary_keys(conn, schema, db_type)
    inferred_primary_keys = infer_primary_keys(tables, primary_keys)
    declared_fks = get_declared_foreign_keys(conn, schema, db_type)
    null_stats = get_null_stats(conn, tables, schema, db_type)

    merged_primary_keys = {**primary_keys, **inferred_primary_keys}
    inferred_fks = infer_relationships(tables, merged_primary_keys, declared_fks)

    mapping = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "database": os.getenv("DB_NAME") or "unknown_database",
        "schema": schema,
        "tables": {},
        "declared_relationships": declared_fks,
        "inferred_relationships": inferred_fks,
        "relationship_edges": [],
        "semi_structured_sources": {},
    }

    for rel in declared_fks:
        mapping["relationship_edges"].append({
            "source_table": rel["table_name"],
            "source_column": rel["column_name"],
            "target_table": rel["references_table"],
            "target_column": rel["references_column"],
            "type": "declared",
        })

    for rel in inferred_fks:
        mapping["relationship_edges"].append({
            "source_table": rel["table"],
            "source_column": rel["column"],
            "target_table": rel["references_table"],
            "target_column": rel["references_column"],
            "type": "inferred",
            "confidence": rel.get("confidence", "heuristic"),
        })

    for table_name, columns in tables.items():
        table_primary_key = primary_keys.get(table_name, inferred_primary_keys.get(table_name, []))
        mapping["tables"][table_name] = {
            "columns": columns,
            "primary_key": table_primary_key,
            "inferred_primary_key": inferred_primary_keys.get(table_name, []),
            "null_stats": null_stats.get(table_name, {}),
        }

    # Semi-structured sources: merge extracted tables/relationships into the map.
    for source_path in (semi_sources or []):
        extracted = extract_semi_structured_schema(source_path)
        if not extracted:
            continue
        for table_name, table_info in extracted.get("tables", {}).items():
            if table_name in mapping["tables"]:
                # Merge new columns that don't already exist.
                existing_cols = {c["column"] for c in mapping["tables"][table_name]["columns"]}
                for col in table_info.get("columns", []):
                    if col["column"] not in existing_cols:
                        mapping["tables"][table_name]["columns"].append(col)
            else:
                mapping["tables"][table_name] = {
                    "columns": table_info.get("columns", []),
                    "primary_key": table_info.get("primary_key", []),
                    "inferred_primary_key": table_info.get("primary_key", []),
                    "null_stats": {},
                    "source": table_info.get("source", source_path),
                }

        for rel in extracted.get("relationships", []):
            mapping["inferred_relationships"].append(rel)
            mapping["relationship_edges"].append({
                "source_table": rel["table"],
                "source_column": rel["column"],
                "target_table": rel["references_table"],
                "target_column": rel["references_column"],
                "type": "inferred",
                "confidence": "semi-structured-llm",
            })

        mapping["semi_structured_sources"][str(source_path)] = {
            "tables": list(extracted.get("tables", {}).keys()),
        }

    return mapping


def get_output_paths(output_path, db_name=None):
    """
    Return the canonical output, a timestamped snapshot, and a latest alias.
    A fresh file set is created for every connected database: the base name is
    prefixed with the database name when available (e.g. schema_mapping_northwind.json,
    schema_mapping_northwind_latest.json, schema_mapping_northwind_<ts>.json).
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    stem, suffix = output.stem, output.suffix or ".json"

    if db_name:
        # sanitize db name for filesystem use
        safe_db = re.sub(r"[^a-zA-Z0-9_-]+", "_", db_name)
        stem = f"{stem}_{safe_db}"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%fZ")
    timestamped = output.with_name(f"{stem}_{timestamp}{suffix}")
    latest = output.with_name(f"{stem}_latest{suffix}")
    return output.with_name(f"{stem}{suffix}"), timestamped, latest


# ---------------------------------------------------------------------------
# File source handling (semi-structured path: CSV / tabular PDF)
# ---------------------------------------------------------------------------

def _coerce_numeric(df):
    """Best-effort numeric coercion so SQLite SUM/AVG work on text-sourced columns."""
    out = df.copy()
    for col in out.columns:
        coerced = pd.to_numeric(out[col], errors="coerce")
        non_null = coerced.notna().sum()
        if non_null > 0 and non_null >= len(out) * 0.9:
            out[col] = coerced
    return out


def build_tables_schema(tables, source_path, database):
    """Build a schema mapping from a dict of {table_name: DataFrame} (deterministic, no LLM)."""
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required to read file sources.")

    tables_mapping = {}
    for table_name, df in tables.items():
        columns = []
        for col, dtype in df.dtypes.items():
            if pd.api.types.is_integer_dtype(dtype):
                data_type = "INTEGER"
            elif pd.api.types.is_float_dtype(dtype):
                data_type = "REAL"
            else:
                data_type = "TEXT"
            columns.append({"column": str(col), "data_type": data_type, "nullable": True})
        tables_mapping[table_name] = {
            "columns": columns,
            "primary_key": [],
            "inferred_primary_key": [],
            "null_stats": {},
            "source": str(source_path),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "database": database,
        "schema": "file",
        "tables": tables_mapping,
        "declared_relationships": [],
        "inferred_relationships": [],
        "relationship_edges": [],
        "semi_structured_sources": {str(source_path): {"tables": sorted(tables_mapping)}},
    }


def load_tables_to_sqlite(tables, sqlite_path):
    """Load a dict of {table_name: DataFrame} into a file-based SQLite DB.

    Returns (connection_uri, [(table_name, row_count), ...]).
    """
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas is required to load file sources.")

    sqlite_path = Path(sqlite_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path.exists():
        sqlite_path.unlink()

    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{sqlite_path}")
    result = []
    for table_name, df in tables.items():
        df = _coerce_numeric(df)
        df.to_sql(table_name, engine, if_exists="replace", index=False)
        result.append((table_name, len(df)))
    engine.dispose()
    return f"sqlite:///{sqlite_path}", result


def build_csv_schema(csv_path, table_name=None):
    """Build a schema mapping from a CSV file (deterministic, no LLM)."""
    df = pd.read_csv(csv_path)
    df.columns = [_normalize_csv_column(c) for c in df.columns]
    if table_name is None:
        table_name = _safe_identifier(Path(csv_path).stem)
    return build_tables_schema({table_name: df}, csv_path, table_name)


def load_csv_to_sqlite(csv_path, sqlite_path, table_name=None):
    """Load a CSV into a file-based SQLite database and return its connection URI."""
    df = pd.read_csv(csv_path)
    df.columns = [_normalize_csv_column(c) for c in df.columns]
    if table_name is None:
        table_name = _safe_identifier(Path(csv_path).stem)
    uri, tables = load_tables_to_sqlite({table_name: df}, sqlite_path)
    return uri, table_name, len(df)


def extract_pdf_tables(pdf_path):
    """Extract tables from a tabular PDF into {table_name: DataFrame} (no LLM).

    Uses pdfplumber: every detected table on every page becomes its own
    SQLite table (table_1, table_2, ...). Returns {} if none found.
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is required to read PDF sources. pip install pdfplumber")

    tables = {}
    table_index = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for raw in page.extract_tables():
                if not raw:
                    continue
                header = [str(c).strip() if c is not None else "" for c in raw[0]]
                rows = [[str(c).strip() if c is not None else "" for c in r] for r in raw[1:]]
                if len(rows) == 0:
                    continue
                ncols = max(len(header), max(len(r) for r in rows))
                header = (header + [""] * ncols)[:ncols]
                for r in rows:
                    r.extend([""] * (ncols - len(r)))
                header = [_normalize_csv_column(c) or f"col_{i + 1}" for i, c in enumerate(header)]
                table_index += 1
                table_name = _safe_identifier(f"{Path(pdf_path).stem}_table_{table_index}")
                df = pd.DataFrame(rows, columns=header)
                tables[table_name] = df
    return tables


def pdf_has_text(pdf_path):
    """True if the PDF has an extractable text layer (i.e. it is NOT scanned/handwritten)."""
    try:
        import pdfplumber
    except ImportError:
        return False
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                if (page.extract_text() or "").strip():
                    return True
    except Exception:
        return False
    return False


def extract_handwritten_pdf(pdf_path, llm, table_name=None):
    """Extract records from a scanned/handwritten PDF via a vision LLM.

    Renders every page to a PNG (pypdfium2 + Pillow), sends the images to a
    vision model asking for a structured JSON table, and returns
    {table_name: DataFrame}. Raises RuntimeError if no tabular records are found.
    """
    try:
        import base64
        import io

        import pypdfium2 as pdfium
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(f"Handwritten PDF extraction needs pypdfium2 + Pillow: {exc}")

    images = []
    doc = pdfium.PdfDocument(pdf_path)
    try:
        for i in range(len(doc)):
            page = doc[i]
            bitmap = page.render(scale=2.0)
            pil = bitmap.to_pil()
            buf = io.BytesIO()
            pil.convert("RGB").save(buf, format="PNG")
            images.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
    finally:
        doc.close()

    prompt = (
        "You are a careful data-entry clerk reading a scanned/handwritten document page.\n"
        "Extract ALL records from THIS page into tables and return ONLY valid JSON.\n"
        'The JSON must have a key "tables": a list of table objects, each with a short "name" '
        'and "rows": an array of objects, one per record. Every row object in a table must use '
        "the SAME keys (these become column names; infer them from the page headers/labels).\n"
        "Rules:\n"
        "- One JSON table object per distinct table/section on the page.\n"
        "- Transcribe the writing literally, preserving numbers and dates exactly.\n"
        "- Do not invent records that are not present. Empty cells become null.\n"
        '- If this page has NO recognizable records, return {"tables": []}.\n'
        'Example: {"tables": [{"name": "sales", "rows": [{"region": "North", "units": 120}]}]}\n'
        "Return nothing but the JSON:\n"
    )

    base = _safe_identifier(Path(pdf_path).stem)
    frames_by_schema: dict[tuple, list] = {}
    for idx, b64 in enumerate(images, start=1):
        page_prompt = f"This is page {idx} of the scanned document. {prompt}"
        try:
            text = llm.vision(page_prompt, [b64])
        except Exception as exc:
            raise RuntimeError(f"Vision model could not read the document: {exc}")
        for df in _parse_vision_frames(text):
            frames_by_schema.setdefault(tuple(df.columns), []).append(df)

    if not frames_by_schema:
        raise RuntimeError(
            "Could not recognize any tabular records in the handwritten PDF. "
            "The file was rejected — please upload a clearer scan or a text-based PDF."
        )

    tables = {}
    multi = len(frames_by_schema) > 1
    for i, (key, dfs) in enumerate(frames_by_schema.items(), start=1):
        merged = pd.concat(dfs, ignore_index=True)
        name = f"{base}_handwritten" if not multi else f"{base}_handwritten_{i}"
        tables[name] = merged
    return tables


def _parse_vision_frames(text):
    """Parse a vision response into one or more DataFrames (supports single 'rows'
    or multi-table 'tables' payloads)."""
    import re as _re

    if not text:
        return []
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return []
    candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
    except Exception:
        arr = _re.search(r"\[.*\]", candidate, _re.DOTALL)
        if not arr:
            return []
        try:
            data = json.loads(arr.group(0))
        except Exception:
            return []

    frames = []
    if isinstance(data, dict):
        tables = data.get("tables")
        if isinstance(tables, list) and tables:
            for tbl in tables:
                rows = tbl.get("rows", tbl) if isinstance(tbl, dict) else tbl
                if isinstance(rows, list) and rows:
                    frames.append(pd.DataFrame(rows))
        else:
            rows = data.get("rows", [])
            if isinstance(rows, dict):
                rows = rows.get("rows", [])
            if isinstance(rows, list) and rows:
                frames.append(pd.DataFrame(rows))
    elif isinstance(data, list) and data:
        frames.append(pd.DataFrame(data))

    cleaned = []
    for df in frames:
        if len(df.columns) == 0:
            continue
        df.columns = [_normalize_csv_column(c) for c in df.columns]
        cleaned.append(df)
    return cleaned


def _normalize_csv_column(name):
    return re.sub(r"[^a-z0-9_]+", "_", str(name).strip().lower()).strip("_") or "column"


def _safe_identifier(name):
    return re.sub(r"[^a-zA-Z0-9_]+", "_", str(name).strip()).strip("_") or "csv_table"


def main():
    parser = argparse.ArgumentParser(description="ARIA Schema Agent - automated schema understanding")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--schema", default="public")
    parser.add_argument("--db-type", choices=["postgresql", "mysql"], default="postgresql")
    parser.add_argument("--output", default="schema_mapping.json")
    parser.add_argument("--json-source", action="append", default=[], help="JSON file(s) to parse")
    parser.add_argument("--csv-source", action="append", default=[], help="CSV file(s) to parse")
    parser.add_argument("--pdf-source", action="append", default=[], help="PDF/report file(s) to parse")
    args = parser.parse_args()

    semi_sources = args.json_source + args.csv_source + args.pdf_source

    conn = get_connection(args)
    try:
        print(f"Connected ({args.db_type}). Extracting schema for '{args.schema}' schema...")
        mapping = build_schema_mapping(conn, args.schema, semi_sources, args.db_type)
        db_name = mapping.get("database", args.db or "unknown")
    finally:
        conn.close()

    output_path, timestamped_path, latest_path = get_output_paths(args.output, db_name or None)

    for path in (output_path, timestamped_path, latest_path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)

    n_tables = len(mapping["tables"])
    n_declared = len(mapping["declared_relationships"])
    n_inferred = len(mapping["inferred_relationships"])
    print(f"Done. {n_tables} tables, {n_declared} declared relationships, "
          f"{n_inferred} inferred relationships.")
    print(f"Written to {output_path}")
    print(f"Saved fresh snapshot to {timestamped_path}")
    print(f"Updated latest copy at {latest_path}")


if __name__ == "__main__":
    main()
