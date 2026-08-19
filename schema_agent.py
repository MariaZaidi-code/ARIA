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
    python schema_agent.py --host localhost --port 5432 --db northwind --user postgres --password 12345
"""

import argparse
import json
import logging
import os
import re
import sys
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

from llm_provider import LLMProvider, create_provider
from core.config import SCHEMA_DIR

logger = logging.getLogger("aria.schema_agent")


# Read-only introspection must never hang indefinitely on one huge table:
# bound every statement on the session (30s) so a slow table degrades
# gracefully instead of stalling the whole run.
QUERY_TIMEOUT_MS = 30_000


def _apply_session_timeout(conn, db_type="postgresql"):
    """Set a session-level statement timeout for read-only introspection.

    PostgreSQL: `statement_timeout` applies to every statement.
    MySQL: `MAX_EXECUTION_TIME` applies to SELECTs (MySQL 5.7.8+). If the
    server is older and rejects it, the timeout is skipped (query still runs,
    just unbounded — better than failing the connection).
    """
    try:
        cur = conn.cursor()
        if db_type == "mysql":
            cur.execute(f"SET SESSION MAX_EXECUTION_TIME = {QUERY_TIMEOUT_MS}")
        else:
            cur.execute(f"SET statement_timeout = {QUERY_TIMEOUT_MS}")
        conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------

def get_connection(args):
    """Build a database connection (PostgreSQL or MySQL) from CLI args / env vars."""
    db_type = getattr(args, "db_type", None) or "postgresql"
    host = args.host or os.getenv("DB_HOST", "localhost")
    # The port must never leak across engine types: DB_PORT in .env targets
    # PostgreSQL, so MySQL must not inherit it. Only --port (or MYSQL_PORT) can
    # override MySQL's default.
    if db_type == "mysql":
        port = args.port or os.getenv("MYSQL_PORT", "3306")
    else:
        port = args.port or os.getenv("DB_PORT", "5432")
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
            sys.exit(
                f"ERROR: could not connect to MySQL at {host}:{port}/{dbname} as {user}: {e}\n"
                "Check: is the MySQL server running on that host/port? Are the "
                "database name, user, and password correct, and does the server "
                "accept TCP connections?"
            )
        _apply_session_timeout(conn, "mysql")
        return conn

    try:
        conn = psycopg2.connect(
            host=host, port=port, dbname=dbname, user=user, password=password,
            connect_timeout=10,
        )
        # Read-only introspection: autocommit prevents one failed query from
        # leaving the connection in the "current transaction is aborted" state,
        # which would silently fail every later query on the same connection.
        conn.autocommit = True
    except psycopg2.OperationalError as e:
        sys.exit(
            f"ERROR: could not connect to PostgreSQL at {host}:{port}/{dbname} as {user}: {e}\n"
            "Check: is the PostgreSQL service running on that host/port? Are the "
            "database name, user, and password correct? Does pg_hba.conf allow "
            "TCP connections from this host?"
        )
    _apply_session_timeout(conn, "postgresql")

    return conn


def _dict_cursor(conn, db_type="postgresql"):
    """Return a dictionary-row cursor for the connected database type."""
    if db_type == "mysql":
        return conn.cursor(pymysql.cursors.DictCursor)
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _lower_keys(row):
    """Normalize a dict row's keys to lowercase.

    PostgreSQL's information_schema returns lowercase column names, but MySQL
    returns UPPERCASE ones (TABLE_NAME, COLUMN_NAME, ...). All downstream code
    reads lowercase keys, so MySQL rows must be normalized or every
    information_schema query fails with KeyError.
    """
    if not row:
        return row
    return {str(k).lower(): v for k, v in row.items()}


def _quote_ident(db_type, name):
    """Return a SQL-safe quoted identifier (double quotes for PG, backticks for MySQL)."""
    if db_type == "mysql":
        return "`" + str(name).replace("`", "") + "`"
    return '"' + str(name).replace('"', "") + '"'


# ---------------------------------------------------------------------------
# Metadata extraction (pure SQL, no LLM)
# ---------------------------------------------------------------------------

def get_tables_and_columns(conn, schema="public", db_type="postgresql"):
    """Return {table_name: [{column, data_type, nullable}, ...]}

    Only BASE TABLEs are profiled; views are skipped (their PK/uniqueness
    checks can be slow or meaningless against a complex view query).
    """
    query = """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name IN (
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
          )
        ORDER BY table_name, ordinal_position;
    """
    with _dict_cursor(conn, db_type) as cur:
        cur.execute(query, (schema, schema))
        rows = cur.fetchall()

    tables = {}
    for row in rows:
        row = _lower_keys(row)
        tables.setdefault(row["table_name"], []).append({
            "column": row["column_name"],
            "data_type": row["data_type"],
            "nullable": row["is_nullable"] == "YES",
        })
    return tables


def get_primary_keys(conn, schema="public", db_type="postgresql"):
    """Return {table_name: [pk_column, ...]}"""
    # NOTE: the join must include tc.table_name. In MySQL every primary key
    # constraint is literally named 'PRIMARY', so joining on constraint_name
    # alone cross-joins every table's PK columns to every other table.
    query = """
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s
        ORDER BY tc.table_name, kcu.ordinal_position;
    """
    with _dict_cursor(conn, db_type) as cur:
        cur.execute(query, (schema,))
        rows = cur.fetchall()

    pks = {}
    for row in rows:
        row = _lower_keys(row)
        pks.setdefault(row["table_name"], []).append(row["column_name"])
    return pks


def get_unique_keys(conn, schema="public", db_type="postgresql"):
    """Return {table_name: [[col, ...], ...]} — one entry per UNIQUE constraint.

    Declared UNIQUE constraints are authoritative: a column covered by one is
    already known to be unique, so it should never be re-inferred or treated as
    a duplicate/weak key downstream.
    """
    query = """
        SELECT tc.table_name, kcu.column_name, tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.constraint_type = 'UNIQUE'
          AND tc.table_schema = %s
        ORDER BY tc.table_name, tc.constraint_name, kcu.ordinal_position;
    """
    with _dict_cursor(conn, db_type) as cur:
        cur.execute(query, (schema,))
        rows = cur.fetchall()

    uniques = {}
    for row in rows:
        row = _lower_keys(row)
        uniques.setdefault(row["table_name"], {})
        uniques[row["table_name"]].setdefault(row["constraint_name"], []).append(
            row["column_name"]
        )
    return {t: list(cols.values()) for t, cols in uniques.items()}


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
              AND kcu.table_schema = %s
            ORDER BY kcu.table_name, kcu.ordinal_position;
        """
    else:
        # PostgreSQL: join pg_constraint directly and align conkey/confkey by
        # ordinal position. Joining information_schema.key_column_usage to
        # constraint_column_usage on the constraint name alone would cross-produce
        # composite foreign keys (a 2-column FK would yield 4 wrong pairs).
        query = """
            SELECT
                refcon.relname AS table_name,
                refatt.attname AS column_name,
                conrel.relname AS references_table,
                conatt.attname AS references_column
            FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            JOIN pg_class refcon ON refcon.oid = c.conrelid
            JOIN pg_class conrel ON conrel.oid = c.confrelid
            JOIN unnest(c.conkey) WITH ORDINALITY AS srckeys(attnum, ord) ON TRUE
            JOIN unnest(c.confkey) WITH ORDINALITY AS tgtkeys(attnum, ord) ON srckeys.ord = tgtkeys.ord
            JOIN pg_attribute refatt ON refatt.attrelid = c.conrelid AND refatt.attnum = srckeys.attnum
            JOIN pg_attribute conatt ON conatt.attrelid = c.confrelid AND conatt.attnum = tgtkeys.attnum
            WHERE c.contype = 'f'
              AND n.nspname = %s
            ORDER BY refcon.relname, srckeys.ord;
        """
    with _dict_cursor(conn, db_type) as cur:
        cur.execute(query, (schema,))
        return [dict(row) for row in cur.fetchall()]


def get_null_stats(conn, tables, schema="public", db_type="postgresql"):
    """Return {table_name: {column_name: {"total_rows": n, "nulls": n, "null_pct": p}}}

    ONE aggregate query per table computes every column's null count (PART 9):
    the old per-column COUNT pattern is an N+1 anti-pattern that issued
    len(columns)+1 round trips per table. A table that cannot be counted
    (permission error, exotic type, huge cost) reports UNKNOWN for every column
    rather than zeros and never kills the run (missing != negative).
    """
    stats = {}
    with conn.cursor() as cur:
        for table_name, columns in tables.items():
            if not columns:
                continue
            table_stats = {}
            try:
                col_names = [c["column"] for c in columns]
                if db_type == "mysql":
                    qualified = f"{_quote_ident(db_type, schema)}.{_quote_ident(db_type, table_name)}"
                    select_parts = ", ".join(
                        f"COUNT({_quote_ident(db_type, c)}) AS c{i}" for i, c in enumerate(col_names)
                    )
                    cur.execute(f"SELECT COUNT(*) AS total, {select_parts} FROM {qualified}")
                    row = cur.fetchone()
                else:
                    select_parts = ", ".join(
                        f"COUNT({_quote_ident(db_type, c)}) AS c{i}" for i, c in enumerate(col_names)
                    )
                    cur.execute(
                        sql.SQL("SELECT COUNT(*) AS total, {} FROM {}.{}").format(
                            sql.SQL(select_parts),
                            sql.Identifier(schema),
                            sql.Identifier(table_name),
                        )
                    )
                    row = cur.fetchone()
                if row:
                    total = row[0]
                    for i, col_name in enumerate(col_names):
                        non_null = row[i + 1]
                        nulls = total - (non_null or 0)
                        null_pct = round((nulls / total) * 100, 2) if total else 0.0
                        table_stats[col_name] = {
                            "total_rows": total,
                            "nulls": nulls,
                            "null_pct": null_pct,
                        }
            except Exception:
                # A single unreadable table must not poison the whole mapping;
                # every column reports UNKNOWN (missing evidence, not zero).
                logger.debug("null stats failed for table %s", table_name, exc_info=True)
                stats[table_name] = {}
                continue
            stats[table_name] = table_stats
    return stats


# ---------------------------------------------------------------------------
# Heuristic relationship inference (fills the gap for "messy" databases)
# ---------------------------------------------------------------------------

def normalize_identifier(value):
    """Normalize names to compare database identifiers across styles."""
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _singularize(name):
    """Best-effort singular of an English identifier (for PK/name matching)."""
    if name.endswith("ies") and len(name) > 4:
        return name[:-3] + "y"
    if name.endswith("s") and not name.endswith("ss") and len(name) > 2:
        return name[:-1]
    return name


# Tokens that signal "this word is about identifiers/keys", never content words.
_ID_TOKENS = {"id", "no", "num", "number", "code", "key", "fk", "ref", "uuid", "sk", "nk"}


def _tokenize_words(name):
    """Split an identifier into lowercase word tokens (snake_case, camelCase, acronyms).

    "MediaTypeId" -> ["media", "type", "id"]; "support_rep_id" -> ["support", "rep", "id"].
    This is what lets name matching work on ANY naming convention, not just X_id.
    """
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name))
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [w for w in re.split(r"[^a-zA-Z0-9]+", s.lower()) if w]


def _is_reference_to_other_table(col_name, table_name, tables):
    """True when `col_name` (X_id style) names ANOTHER table (X / Xs / Xes / Xies).

    A column like `order_id` in a table that also has an `orders` table is
    almost certainly a foreign key, NOT the table's own primary key. Promoting
    it to a PK turns a reference into a target: it then wins overlap
    tiebreakers over the real referenced table (e.g. olist payments.order_id
    vs orders.order_id) and hides genuine relationships. This guard keeps
    FK-like columns out of PK inference.

    Matching is token-based (txt item 1: name-match evidence), so it works for
    ANY naming convention — plain `orders`, prefixed `olist_orders_dataset`,
    suffixed `tbl_order_items`, snake/camel — without per-database patches.
    """
    base = col_name[:-3].lower() if col_name.endswith("_id") else col_name.lower()
    if not base or base in _ID_TOKENS:
        return False
    base = _singularize(base)
    forms = {base, base + "s", base + "es"}
    if base.endswith("y") and len(base) > 1:
        forms.add(base[:-1] + "ies")
    forms.add(_singularize(base))

    def _matches(t):
        """Does any word-token of table `t` (or its whole name) singularize to base?"""
        if normalize_identifier(t) in forms:
            return True
        return any(_singularize(tok) in forms for tok in _tokenize_words(t))

    # Find the MOST SPECIFIC table the base could name (shortest name that
    # still contains the base as a token). `orders` names `olist_orders_dataset`
    # but `order` inside `olist_order_payments_dataset` is just a qualifier —
    # the shorter/simpler name wins. If that most-specific match is the table's
    # OWN table, the column is its own identity; otherwise it is a reference.
    best = None
    for t in tables:
        if not _matches(t):
            continue
        if best is None or len(t) < len(best):
            best = t
    return best is not None and best != table_name


def infer_primary_keys(tables, declared_primary_keys):
    """Return likely PKs when the database does not declare them explicitly."""
    inferred = {}

    for table_name, columns in tables.items():
        if declared_primary_keys.get(table_name):
            inferred[table_name] = declared_primary_keys[table_name]
            continue

        table_norm = normalize_identifier(table_name)
        table_singular = _singularize(table_norm)
        candidates = []
        for col in columns:
            col_name = col["column"]
            normalized = normalize_identifier(col_name)
            if (normalized == "id"
                    or normalized == table_norm + "id"
                    or normalized == table_singular + "id"):
                candidates.append(col_name)

        if len(candidates) == 1:
            inferred[table_name] = candidates
            continue

        non_null_columns = [col["column"] for col in columns if not col["nullable"]]
        if len(non_null_columns) == 1:
            # Never trust a single non-null column as PK if it looks like a
            # foreign key (e.g. a table whose only NOT NULL column is
            # `customer_id` almost certainly points elsewhere). Only accept it
            # when it does not look like a reference to another table.
            candidate = non_null_columns[0]
            normalized = normalize_identifier(candidate)
            is_id_like = normalized.endswith("id") and normalized not in ("id", normalize_identifier(table_name) + "id")
            if not is_id_like:
                inferred[table_name] = non_null_columns
            continue

        id_like = [col["column"] for col in columns if col["column"].lower().endswith("_id") or col["column"].lower() == "id"]
        if len(id_like) == 1:
            candidate = id_like[0]
            if not _is_reference_to_other_table(candidate, table_name, tables):
                inferred[table_name] = id_like

    return inferred


def _qname(db_type, name):
    """SQL-safe quoted identifier (double quotes for PG, backticks for MySQL)."""
    if db_type == "mysql":
        return "`" + str(name).replace("`", "") + "`"
    return '"' + str(name).replace('"', "") + '"'


def _table_rows(conn, table_name, schema, db_type):
    """Best-effort row-count for the table (None when unknown).

    PostgreSQL uses pg_class.reltuples (a planner estimate, cheap and stable).
    MySQL uses a real COUNT(*) — information_schema.TABLES.TABLE_ROWS is an
    InnoDB estimate that can be 0 right after a bulk load or stale, which would
    wrongly gate PK verification. The session statement_timeout bounds the cost.
    """
    try:
        if db_type == "postgresql":
            cur = conn.cursor()
            cur.execute(
                "SELECT c.reltuples::bigint FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relname = %s",
                (schema, table_name),
            )
            row = cur.fetchone()
            return row[0] if row else None
        cur = conn.cursor()
        table_ref = _qname(db_type, table_name)
        cur.execute(f"SELECT COUNT(*) FROM {table_ref}")
        row = cur.fetchone()
        return row[0] if row else None
    except Exception as exc:
        logger.debug("row count failed for %s.%s: %s", schema, table_name, exc)
        return None


def _column_is_unique_key(conn, table_name, column, schema, db_type):
    """Return True when the column is fully populated and every value is unique."""
    try:
        cur = conn.cursor()
        table_ref = (f"{_qname(db_type, schema)}.{_qname(db_type, table_name)}"
                     if db_type == "postgresql" else _qname(db_type, table_name))
        col_ref = _qname(db_type, column)
        cur.execute(
            f"SELECT count(*) AS total, count({col_ref}) AS non_null, "
            f"count(DISTINCT {col_ref}) AS distinct_values FROM {table_ref}"
        )
        row = cur.fetchone()
        if not row:
            return False
        total, non_null, distinct_values = row[0], row[1], row[2]
        return (total is not None and total > 0
                and non_null == total and distinct_values == total)
    except Exception as exc:
        logger.debug("uniqueness check failed for %s.%s: %s", table_name, column, exc)
        return False


def _column_is_empty(conn, table_name, column, schema, db_type):
    """Return True when a column holds no populated values (all NULL or blank).

    A primary key or foreign key built entirely on such a column carries no
    information, so it is dropped from the mapping instead of being reported as
    a real key.
    """
    try:
        cur = conn.cursor()
        table_ref = (f"{_qname(db_type, schema)}.{_qname(db_type, table_name)}"
                     if db_type == "postgresql" else _qname(db_type, table_name))
        col_ref = _qname(db_type, column)
        if db_type == "mysql":
            cur.execute(
                f"SELECT COUNT({col_ref}) AS non_null, "
                f"COUNT(NULLIF(TRIM(CAST({col_ref} AS CHAR)), '')) AS non_blank "
                f"FROM {table_ref}"
            )
        else:
            cur.execute(
                f"SELECT COUNT({col_ref}) AS non_null, "
                f"COUNT(NULLIF(TRIM(CAST({col_ref} AS TEXT)), '')) AS non_blank "
                f"FROM {table_ref}"
            )
        row = cur.fetchone()
        return row is not None and (row[0] or 0) == 0 and (row[1] or 0) == 0
    except Exception as exc:
        logger.debug("empty-column check failed for %s.%s: %s", table_name, column, exc)
        return False


def infer_primary_keys_from_data(conn, tables, schema, db_type, existing_pks, max_rows=500000, exclude_columns=None):
    """Data-backed PK inference for tables the name heuristics could not resolve.

    When a table declares no PK and no column *name* points to one, look at the
    actual data: an id-like column that is fully populated and whose every value
    is unique (distinct count == row count) is the de-facto key. This handles
    flat/denormalized tables whose natural key is a prefixed text id
    (e.g. 'T0000001'), which naming conventions cannot detect, and never guesses
    for a column that is merely shared with other tables (customer_id, ...).

    `exclude_columns` ((table, column) pairs) lets confirmed foreign-key columns
    be ruled out as key candidates — a column that provably references another
    table is a reference, not the table's own identity.
    """
    exclude_columns = exclude_columns or set()
    inferred = {}
    for table_name, columns in tables.items():
        if existing_pks.get(table_name):
            continue
        id_like = [c["column"] for c in columns
                   if str(c["column"]).lower().endswith("_id") or str(c["column"]).lower() == "id"]
        id_like = [c for c in id_like
                   if (table_name, c) not in exclude_columns
                   # A column whose name matches ANOTHER table (order_id -> orders)
                   # is a disguised FK, not this table's identity. Never promote
                   # it to a primary key from data alone.
                   and not _is_reference_to_other_table(c, table_name, tables)]
        if not id_like:
            continue
        rows = _table_rows(conn, table_name, schema, db_type)
        if rows is not None and rows > max_rows:
            # Too large to verify with a scan; don't guess on partial evidence.
            continue
        unique = [col for col in id_like
                  if _column_is_unique_key(conn, table_name, col, schema, db_type)]
        if not unique:
            continue
        if len(unique) == 1:
            inferred[table_name] = unique
            continue
        # Several unique id columns: only commit when exactly one carries the
        # primary-looking name (id / <table>id / <table_singular>id).
        table_norm = normalize_identifier(table_name)
        primary_named = [c for c in unique if normalize_identifier(c) in
                         ("id", table_norm + "id", _singularize(table_norm) + "id")]
        if len(primary_named) == 1:
            inferred[table_name] = primary_named
    return inferred


def infer_relationships(tables, primary_keys, declared_fks, conn=None, schema="public", db_type="postgresql", null_stats=None):
    """Infer relationships for columns with no declared FK constraint.

    Phase C: delegates to the schema_engine pipeline (candidates -> evidence
    -> classifier -> acceptance policy -> registry), the single acceptance
    authority (RULE 6). Returns (inferred, ambiguous) legacy-shaped dicts.
    """
    from schema_engine.relationships import infer_relationships as _pipeline

    inferred, ambiguous, _registry = _pipeline(
        tables, primary_keys, declared_fks,
        conn=conn, schema=schema, db_type=db_type, null_stats=null_stats,
    )
    return inferred, ambiguous


# ---------------------------------------------------------------------------
# LLM-assisted schema reasoning (optional enrichment over the heuristics)
#
# Runs a single structured pass with whichever LLM backend is active — local
# (Ollama via `aria-goal`) or cloud (Groq) — through the unified
# LLMProvider.chat() interface. The LLM:
#   * confirms or disproves the heuristic candidate relationships,
#   * may add genuine FK-like links the heuristics missed,
#   * suggests a primary key only when none was declared or inferred,
#   * attaches plain-English table descriptions and measure/dimension hints.
#
# Every suggestion is validated against the real schema before it is merged, so
# a hallucinated table/column is never accepted. Any timeout, failure or
# non-JSON response leaves the deterministic mapping untouched.
# ---------------------------------------------------------------------------

_SCHEMA_REASONING_ROLE = "schema"

_SCHEMA_REASONING_PROMPT = """\
You are a careful database schema analyst for a BI system. Below is a schema
summary (tables, columns, data types, nullability, declared/inferred primary
keys, and UNVERIFIED candidate relationships). Reason about it and return STRICT
JSON only, with exactly this shape:

{
  "tables": {
    "<table_name>": {
      "description": "one-line plain-English purpose of this table",
      "pk_candidates": ["column names likely to be a primary key, ONLY if the table has none declared or inferred; else []"],
      "measures": ["numeric columns that are business measurements to aggregate (never ids, codes, flags or timestamps)"],
      "dimensions": ["categorical/text columns useful for grouping and filtering"]
    }
  },
  "relationships": [
    {"table": "...", "column": "...", "references_table": "...", "references_column": "...",
     "kind": "confirm", "reason": "short justification"}
  ]
}

Rules:
- Refer ONLY to tables and columns that exist in the schema above. Never invent names.
- "kind": "confirm" for a candidate relationship you believe is a real foreign key;
  "add" for a genuine FK-like link the candidates missed. Skip same-name columns
  that merely coincide (e.g. two unrelated "amount" columns).
- CRITICAL: Look for foreign keys beyond X_id naming. Columns like reports_to,
  ship_via, created_by, parent_id, managed_by, etc. may reference other tables.
  A column referencing the same table (self-reference) is valid (e.g. reports_to
  in employees referencing employee_id).
- Use exact, case-sensitive table and column names.
- When unsure, omit rather than guess. No markdown, no prose, JSON only.
"""


_SCHEMA_REASONING_PROMPT_TAIL = "\nSchema:\n"


def enrich_with_llm(mapping, llm, schema=None):
    """Optional LLM-assisted reasoning pass over a built schema mapping.

    Works identically for every provider (Ollama 'local' or Groq 'cloud').
    Returns the mapping unchanged when no LLM is given, the call fails/times
    out, or the response is unusable.
    """
    if llm is None:
        return mapping

    summary = _build_reasoning_brief(mapping)
    if not summary.strip():
        return mapping

    try:
        timeout = 300 if getattr(llm, "provider", None) == "local" else 60
        content = llm.chat(
            _SCHEMA_REASONING_ROLE,
            messages=[{"role": "user", "content": _SCHEMA_REASONING_PROMPT + _SCHEMA_REASONING_PROMPT_TAIL + summary}],
            temperature=0.0,
            num_predict=2500,
            timeout=timeout,
        )
    except Exception as exc:
        print(f"WARNING: schema LLM reasoning skipped ({exc}); keeping heuristic results.")
        return mapping

    parsed = _parse_schema_reasoning(content)
    if not parsed or not (isinstance(parsed.get("tables"), dict)
                          or isinstance(parsed.get("relationships"), list)):
        print("WARNING: schema LLM reasoning returned no usable JSON; keeping heuristic results.")
        return mapping

    try:
        model = llm.model_for(_SCHEMA_REASONING_ROLE)
    except Exception:
        model = None
    mapping["llm_reasoning"] = {
        "provider": getattr(llm, "provider", None),
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _apply_schema_reasoning(mapping, parsed, schema=schema)
    return mapping


def _build_reasoning_brief(mapping, max_candidates=40):
    """Focused briefing for the reasoning LLM (PART 16).

    Deterministic candidate generation and evidence collection have already
    happened before this point. The LLM is only asked for SEMANTIC evidence on
    the genuinely ambiguous/high-value candidates plus descriptions / PK
    suggestions for tables that lack a key. This is NOT a lossy whole-schema
    dump: the payload is bounded by the number of candidates under review, so
    the LLM is never treated as an oracle over the entire database. Everything
    it returns is still routed through the deterministic classifier + policy
    (RULE 5).
    """
    tables = mapping.get("tables", {})
    if not tables:
        return ""
    lines = [f"Database: {mapping.get('database', 'unknown')} "
             f"(schema: {mapping.get('schema', '?')})"]

    def _pk(table_name):
        info = tables.get(table_name, {}) or {}
        pk = info.get("primary_key") or info.get("inferred_primary_key") or []
        return ", ".join(pk) if isinstance(pk, (list, tuple)) and pk else "none"

    lines.append("TABLES:")
    for table_name in tables:
        lines.append(f"  {table_name} (PK: {_pk(table_name)})")

    missing_pk = sorted(t for t in tables if _pk(t) == "none")
    declared = mapping.get("declared_relationships", []) or []
    inferred = mapping.get("inferred_relationships", []) or []
    ambiguous = mapping.get("ambiguous_relationships", []) or []
    candidates = inferred + ambiguous

    review_tables = set()
    for r in candidates:
        review_tables.add(r.get("table"))
        review_tables.add(r.get("references_table"))

    detail_tables = sorted((set(missing_pk) | review_tables) & set(tables))
    if detail_tables:
        lines.append("COLUMN CONTEXT (tables under review / lacking a key):")
        for t in detail_tables:
            cols = ", ".join(c["column"] for c in tables[t].get("columns", []))
            lines.append(f"  {t}: {cols}")

    if declared:
        lines.append("DECLARED FOREIGN KEYS (authoritative - do not second-guess):")
        for d in declared:
            lines.append(f"  {d['table_name']}.{d['column_name']} -> "
                         f"{d['references_table']}.{d['references_column']}")

    if candidates:
        lines.append(f"CANDIDATES FOR SEMANTIC REVIEW ({len(candidates)}):")
        for r in candidates[:max_candidates]:
            src = r.get("table", r.get("table_name"))
            col = r.get("column", r.get("column_name"))
            tgt_t = r.get("references_table")
            tgt_c = r.get("references_column")
            extra = ""
            state = r.get("relationship_state")
            if state:
                extra += f" state={state}"
            if r.get("confidence"):
                extra += f" confidence={r.get('confidence')}"
            score = r.get("confidence_score")
            if score is not None:
                extra += f" score={score}"
            lines.append(f"  {src}.{col} -> {tgt_t}.{tgt_c}{extra}")
        if len(candidates) > max_candidates:
            lines.append(f"... ({len(candidates) - max_candidates} more candidates omitted)")

    return "\n".join(lines)


def _parse_schema_reasoning(content):
    """Robustly parse the reasoning response into a dict ({} on any failure).

    Falls back to the largest object-bounded prefix when the model's reply is
    truncated mid-JSON (the token cap can be hit before the closing brace), so
    a partial but otherwise-correct answer is not discarded wholesale.
    """
    if not content or not isinstance(content, str):
        return {}
    text = content.strip()
    text = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    candidate = text[start:end + 1]
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    # Truncation salvage: try each `{` boundary before the final `}` and keep
    # the largest prefix that still parses as a dict.
    for open_idx in range(start, end):
        if text[open_idx] != "{":
            continue
        try:
            data = json.loads(text[open_idx:end + 1])
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


_NUMERIC_TYPE_HINTS = (
    "int", "numeric", "decimal", "float", "real", "double", "serial", "money",
)


def _is_numeric_type(data_type):
    t = (data_type or "").lower()
    return any(h in t for h in _NUMERIC_TYPE_HINTS)


def _column_data_type(table_info, col_name):
    for c in table_info.get("columns", []):
        if c["column"] == col_name:
            return c.get("data_type", "")
    return ""


def _apply_schema_reasoning(mapping, parsed, schema=None):
    """Merge validated LLM suggestions into the mapping (never invents names)."""
    tables = mapping.setdefault("tables", {})
    declared = mapping.get("declared_relationships", [])
    declared_pairs = {(d["table_name"], d["column_name"]) for d in declared}
    inferred = mapping.setdefault("inferred_relationships", [])
    edges = mapping.setdefault("relationship_edges", [])

    def pair(r):
        return (r.get("table"), r.get("column"), r.get("references_table"), r.get("references_column"))

    # -- table-level annotations ------------------------------------------
    llm_tables = parsed.get("tables") or {}
    if isinstance(llm_tables, dict):
        for table_name, info in llm_tables.items():
            if table_name not in tables or not isinstance(info, dict):
                continue
            table_info = tables[table_name]
            real_columns = {c["column"] for c in table_info.get("columns", [])}

            desc = info.get("description")
            if isinstance(desc, str) and desc.strip():
                table_info["description"] = desc.strip()

            measures = [c for c in (info.get("measures") or []) if isinstance(c, str)]
            dims = [c for c in (info.get("dimensions") or []) if isinstance(c, str)]
            measures = [c for c in measures if c in real_columns and _is_numeric_type(_column_data_type(table_info, c))]
            dims = [c for c in dims if c in real_columns and c not in measures]
            if measures or dims:
                table_info.setdefault("semantic_tags", {}).update(
                    {"measures": measures, "dimensions": dims}
                )

            existing_pk = table_info.get("primary_key") or table_info.get("inferred_primary_key") or []
            pk_cands = [c for c in (info.get("pk_candidates") or []) if isinstance(c, str) and c in real_columns]
            if not existing_pk and len(pk_cands) == 1:
                cand = pk_cands[0]
                nullable = next((c.get("nullable") for c in table_info.get("columns", []) if c["column"] == cand), True)
                null_pct = table_info.get("null_stats", {}).get(cand, {}).get("null_pct")
                if nullable is False or null_pct in (0, 0.0):
                    table_info["inferred_primary_key"] = [cand]
                    if not table_info.get("primary_key"):
                        table_info["primary_key"] = [cand]

    # -- relationship confirm / add ----------------------------------------
    llm_rels = parsed.get("relationships") or []
    if isinstance(llm_rels, list):
        from schema_engine.classifier import classify
        from schema_engine.policy import AcceptancePolicy

        policy = AcceptancePolicy()
        table_pk = {t: list(info.get("primary_key") or []) for t, info in tables.items()}
        null_stats = {t: (info.get("null_stats") or {}) for t, info in tables.items()}
        review_stash = mapping.setdefault("_llm_review", [])

        for rel in llm_rels:
            if not isinstance(rel, dict):
                continue
            table = rel.get("table")
            column = rel.get("column")
            ref_table = rel.get("references_table")
            ref_col = rel.get("references_column")
            kind = rel.get("kind")
            if not all(isinstance(x, str) and x for x in (table, column, ref_table, ref_col)):
                continue
            if table not in tables or ref_table not in tables:
                continue  # hallucinated table
            if column not in {c["column"] for c in tables[table].get("columns", [])}:
                continue
            if ref_col not in {c["column"] for c in tables[ref_table].get("columns", [])}:
                continue
            # The source column must look like a reference (id-like name, FK
            # pattern like _by/_to/_via, or an exact match to the target column):
            # this stops the LLM from "confirming" a numeric measure (e.g.
            # `total`) as a foreign key.
            col_norm = normalize_identifier(column)
            ref_norm = normalize_identifier(ref_col)
            col_dtype = _column_data_type(tables.get(table, {}), column).lower()
            is_id_like = col_norm.endswith("id")
            is_fk_pattern = column.lower().endswith(("_id", "_by", "_to", "_from", "_via", "_for", "_at", "_with", "_against", "_on", "_of", "_type"))
            is_numeric_type = any(tok in col_dtype for tok in ("int", "numeric", "decimal", "serial"))
            if not (is_id_like or is_fk_pattern or col_norm == ref_norm or is_numeric_type):
                continue
            if (table, column) in declared_pairs:
                continue  # already constrained; don't second-guess the DB

            new_pair = (table, column, ref_table, ref_col)
            if kind == "confirm":
                existing = [r for r in inferred
                            if r.get("table") == table and r.get("column") == column]
                if existing:
                    # Only upgrade confidence if LLM agrees with the existing
                    # heuristic target. Never replace a heuristic target with
                    # the LLM's guess — small LLMs often pick wrong targets.
                    for r in existing:
                        if (r.get("references_table") == ref_table
                                and r.get("references_column") == ref_col):
                            r["confidence"] = "llm-confirmed"
                            r["note"] = ("Confirmed by LLM reasoning "
                                         "(no FK constraint declared in the database).")
                            policy.corroborate(r, 20, "LLM reasoning corroborates this target")
                            for e in edges:
                                if (e.get("source_table") == table
                                        and e.get("source_column") == column
                                        and e.get("target_table") == ref_table):
                                    e["confidence"] = "llm-confirmed"
                                    e["confidence_score"] = r.get("confidence_score")
                                    e["confidence_band"] = r.get("confidence_band")
                                    e["relationship_state"] = r.get("relationship_state")
                                    e["review_status"] = r.get("review_status")
                else:
                    # No existing heuristic — LLM is the only signal; the
                    # policy decides whether it is strong enough to emit.
                    new_rel, _amb = classify(
                        None, table_pk, null_stats, schema,
                        table, column, ref_table, ref_col,
                        "llm-confirmed",
                        "Confirmed by LLM reasoning (no FK constraint declared in the database).",
                        name_hint=False, llm_signal="confirm",
                    )
                    if new_rel["relationship_state"] == "UNCERTAIN":
                        new_rel["review_status"] = "review"
                        review_stash.append(new_rel)
                    else:
                        inferred.append(new_rel)
                        edges.append({
                            "source_table": table, "source_column": column,
                            "target_table": ref_table, "target_column": ref_col,
                            "type": "inferred", "confidence": "llm-confirmed",
                            "confidence_score": new_rel.get("confidence_score"),
                            "confidence_band": new_rel.get("confidence_band"),
                            "relationship_state": new_rel.get("relationship_state"),
                            "review_status": new_rel.get("review_status"),
                        })
            elif kind == "add" and new_pair not in {pair(r) for r in inferred}:
                # Only add when this column has no inferred FK yet (no ambiguity);
                # the policy decides the state from LLM + name + PK evidence.
                if not any(r.get("table") == table and r.get("column") == column for r in inferred):
                    new_rel, _amb = classify(
                        None, table_pk, null_stats, schema,
                        table, column, ref_table, ref_col,
                        "llm-reasoned",
                        "Proposed by LLM reasoning (no FK constraint declared in the database).",
                        name_hint=False, llm_signal="add",
                    )
                    if new_rel["relationship_state"] == "UNCERTAIN":
                        new_rel["review_status"] = "review"
                        review_stash.append(new_rel)
                    else:
                        inferred.append(new_rel)
                        edges.append({
                            "source_table": table, "source_column": column,
                            "target_table": ref_table, "target_column": ref_col,
                            "type": "inferred", "confidence": "llm-reasoned",
                            "confidence_score": new_rel.get("confidence_score"),
                            "confidence_band": new_rel.get("confidence_band"),
                            "relationship_state": new_rel.get("relationship_state"),
                            "review_status": new_rel.get("review_status"),
                        })


def _canonicalize_mapping(mapping):
    """Validation pass: every relationship/edge must reference real objects.

    Runs AFTER all sources (declared FKs, heuristics, LLM) have merged so the
    final payload is guaranteed internally consistent:
      * tables/columns in relationships exist in `mapping["tables"]`
      * relationship_edges mirror declared+inferred relationships (no strays)
      * no duplicate relationship entries
    """
    tables = mapping.get("tables", {})
    known_columns = {
        t: {c["column"] for c in info.get("columns", [])}
        for t, info in tables.items()
    }

    def valid_rel(r, kind):
        if kind == "declared":
            src, src_col = r.get("table_name"), r.get("column_name")
            tgt, tgt_col = r.get("references_table"), r.get("references_column")
        else:
            src, src_col = r.get("table"), r.get("column")
            tgt, tgt_col = r.get("references_table"), r.get("references_column")
        if src not in known_columns or tgt not in known_columns:
            return False
        # Composite relationships carry a LIST of columns.
        cols = src_col if isinstance(src_col, list) else [src_col]
        ref_cols = tgt_col if isinstance(tgt_col, list) else [tgt_col]
        if any(c not in known_columns[src] for c in cols):
            return False
        if any(c not in known_columns[tgt] for c in ref_cols):
            return False
        return True

    mapping["declared_relationships"] = [
        r for r in mapping.get("declared_relationships", []) if valid_rel(r, "declared")
    ]
    mapping["inferred_relationships"] = [
        r for r in mapping.get("inferred_relationships", []) if valid_rel(r, "inferred")
    ]

    # Rebuild edges from the authoritative relationship lists.
    edges = []
    seen_edges = set()
    for r in mapping["declared_relationships"]:
        edges.append({
            "source_table": r["table_name"], "source_column": r["column_name"],
            "target_table": r["references_table"], "target_column": r["references_column"],
            "type": "declared", "confidence": "declared",
        })
    for r in mapping["inferred_relationships"]:
        edges.append({
            "source_table": r["table"], "source_column": r["column"],
            "target_table": r["references_table"], "target_column": r["references_column"],
            "type": "inferred", "confidence": r.get("confidence", "inferred"),
            "cardinality": r.get("cardinality"),
        })
    for e in edges:
        key = (e["source_table"], str(e["source_column"]), e["target_table"], str(e["target_column"]))
        if key not in seen_edges:
            seen_edges.add(key)
    deduped = []
    for e in edges:
        key = (e["source_table"], str(e["source_column"]), e["target_table"], str(e["target_column"]))
        if key in seen_edges:
            deduped.append(e)
            seen_edges.discard(key)
    mapping["relationship_edges"] = deduped


def _build_relationship_graph(mapping):
    """Build an explicit per-table relationship graph (txt item 9).

    For every table: its primary key, columns, and separately its OUTGOING
    (this table references others) and INCOMING (others reference this table)
    relationships. Also detects MANY-TO-MANY (txt item 2) via junction tables:
    a table whose composite primary key columns each reference another table is
    a join table; the referenced tables get a many-to-many link through it.
    """
    tables = mapping.get("tables", {})
    edges = mapping.get("relationship_edges", [])
    graph = {}

    # Normalize an edge to (table, column) -> (target, target_column).
    def _out_edges(t):
        out = []
        for e in edges:
            if e.get("source_table") == t:
                out.append(e)
        return out

    def _in_edges(t):
        incoming = []
        for e in edges:
            if e.get("target_table") == t:
                incoming.append(e)
        return incoming

    for t, info in tables.items():
        pks = info.get("primary_key") or info.get("inferred_primary_key") or []
        graph[t] = {
            "primary_key": pks,
            "columns": [c["column"] for c in info.get("columns", [])],
            "outgoing_relationships": [],
            "incoming_relationships": [],
            "many_to_many": [],
        }
        for e in _out_edges(t):
            graph[t]["outgoing_relationships"].append({
                "source_column": e.get("source_column"),
                "target_table": e.get("target_table"),
                "target_column": e.get("target_column"),
                "type": e.get("type"),
                "confidence": e.get("confidence"),
                "cardinality": e.get("cardinality"),
                "ambiguous": e.get("ambiguous"),
            })
        for e in _in_edges(t):
            graph[t]["incoming_relationships"].append({
                "source_table": e.get("source_table"),
                "source_column": e.get("source_column"),
                "target_column": e.get("target_column"),
                "type": e.get("type"),
                "confidence": e.get("confidence"),
                "cardinality": e.get("cardinality"),
                "ambiguous": e.get("ambiguous"),
            })

    # Many-to-many via junction tables (composite PK, each PK column a FK).
    for t, info in tables.items():
        pks = info.get("primary_key") or info.get("inferred_primary_key") or []
        if len(pks) < 2:
            continue
        refs = {}
        for e in _out_edges(t):
            if e.get("source_column") in pks and e.get("target_table") != t:
                refs[e["source_column"]] = e["target_table"]
        if len(refs) >= 2:
            # A junction: every PK column points at a different table.
            involved = sorted(set(refs.values()))
            if len(involved) >= 2:
                junction = {
                    "junction_table": t,
                    "columns": list(refs.keys()),
                    "tables": involved,
                }
                for parent in involved:
                    graph[parent]["many_to_many"].append(junction)
    return graph


# ---------------------------------------------------------------------------
# Assemble & write schema_mapping.json
# ---------------------------------------------------------------------------

def schema_has_tables(conn, schema):
    """Return True when the given Postgres schema contains at least one base table."""
    if not schema:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
            )
            """,
            (schema,),
        )
        return bool(cur.fetchone()[0])


def list_schemas_with_tables(conn):
    """Return non-system schemas that contain at least one base table (Postgres)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND table_schema NOT LIKE 'pg_%'
              AND table_type = 'BASE TABLE'
            GROUP BY table_schema
            ORDER BY count(*) DESC, table_schema
            """
        )
        return [row[0] for row in cur.fetchall()]


def detect_schema_mode(conn):
    """Classify a database as single-schema or multi-schema.

    Returns {"mode": "single"|"multi", "schemas": [...], "count": n}.
    Databases like northwind use only 'public' (single); AdventureWorks-style
    databases spread tables across several schemas (multi). The caller picks
    the matching extraction path so the single-schema flow is untouched.
    """
    schemas = list_schemas_with_tables(conn)
    return {
        "mode": "multi" if len(schemas) > 1 else "single",
        "schemas": schemas,
        "count": len(schemas),
    }


def find_schema_with_tables(conn):
    """Return the largest non-system Postgres schema that contains base tables.

    Prefers the schema with the most tables (best signal for relationship
    inference). Falls back to 'public' when only it has tables.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND table_schema NOT LIKE 'pg_%'
              AND table_type = 'BASE TABLE'
            GROUP BY table_schema
            ORDER BY count(*) DESC, table_schema
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return row[0] if row else "public"


def _drop_empty_key_columns(mapping, conn, schema, db_type):
    """Remove any primary/foreign key whose source column is fully empty.

    A key built on a column with no populated values (all NULL or blank) cannot
    identify or reference anything, so it is dropped from the mapping. The
    removals are recorded under mapping["empty_key_columns_removed"] so the
    decision is transparent. On any query failure the column is kept (safe).
    """
    tables = mapping.setdefault("tables", {})
    removed_pks, removed_fks = [], []

    for table_name, info in tables.items():
        col_names = {c["column"] for c in info.get("columns", [])}
        for key_field in ("primary_key", "inferred_primary_key"):
            kept = []
            for pk in info.get(key_field, []):
                if pk in col_names and _column_is_empty(conn, table_name, pk, schema, db_type):
                    removed_pks.append((table_name, pk))
                else:
                    kept.append(pk)
            info[key_field] = kept
        if not info.get("primary_key"):
            info["primary_key"] = []

    def source_pair(rel, declared):
        if declared:
            return rel.get("table_name"), rel.get("column_name")
        return rel.get("table"), rel.get("column")

    removed_fk_pairs = set()
    for rel_list, declared in ((mapping.get("declared_relationships", []), True),
                               (mapping.get("inferred_relationships", []), False)):
        kept = []
        for rel in rel_list:
            table_name, col_name = source_pair(rel, declared)
            col_names = {c["column"] for c in tables.get(table_name, {}).get("columns", [])}
            if isinstance(col_name, str) and (table_name in tables and col_name in col_names
                    and _column_is_empty(conn, table_name, col_name, schema, db_type)):
                removed_fk_pairs.add((table_name, col_name))
                removed_fks.append((table_name, col_name, declared))
            else:
                kept.append(rel)
        rel_list[:] = kept

    if removed_fk_pairs:
        mapping["relationship_edges"] = [
            e for e in mapping.get("relationship_edges", [])
            if (e.get("source_table"), e.get("source_column")) not in removed_fk_pairs
        ]

    mapping["empty_key_columns_removed"] = {
        "primary_keys": sorted(set(removed_pks)),
        "foreign_keys": sorted(set(removed_fks)),
    }
    return mapping


def detect_schema_drift(previous, current):
    """Compare two schema mappings (txt item 5) and report what changed.

    Detects new/removed tables, added/removed columns, changed data types,
    changed PK/FK structure, and newly inferred relationships. Used when the
    agent runs repeatedly against a live database whose schema evolves.
    """
    prev_tables = previous.get("tables", {}) if previous else {}
    curr_tables = current.get("tables", {}) if current else {}

    def _norm(rel, source_side):
        return {
            "table": rel[source_side],
            "column": rel["column"] if source_side == "table" else rel["column"],
            "references_table": rel["references_table"],
            "references_column": rel["references_column"],
        }

    def _edge_set(mapping, declared=True):
        out = set()
        for rel in mapping.get("declared_relationships", []):
            if declared:
                out.add((rel["table_name"], str(rel["column_name"]),
                         rel["references_table"], str(rel["references_column"])))
        return out

    def _inferred_set(mapping):
        out = set()
        for rel in mapping.get("inferred_relationships", []):
            col = rel.get("column")
            if isinstance(col, list):
                col = ",".join(col)
            ref = rel.get("references_column")
            if isinstance(ref, list):
                ref = ",".join(ref)
            out.add((rel.get("table"), str(col),
                     rel.get("references_table"), str(ref)))
        return out

    drift = {"has_changes": False, "changed_tables": []}

    new_tables = sorted(set(curr_tables) - set(prev_tables))
    removed_tables = sorted(set(prev_tables) - set(curr_tables))
    if new_tables:
        drift["new_tables"] = new_tables
        drift["has_changes"] = True
    if removed_tables:
        drift["removed_tables"] = removed_tables
        drift["has_changes"] = True

    added_columns = {}
    removed_columns = {}
    datatype_changed = {}
    pk_changed = {}
    for table in sorted(set(curr_tables) & set(prev_tables)):
        prev_cols = {c["column"]: c for c in prev_tables[table].get("columns", [])}
        curr_cols = {c["column"]: c for c in curr_tables[table].get("columns", [])}
        new_cols = sorted(set(curr_cols) - set(prev_cols))
        gone_cols = sorted(set(prev_cols) - set(curr_cols))
        type_changes = {}
        for col in sorted(set(curr_cols) & set(prev_cols)):
            if str(prev_cols[col].get("data_type", "")).lower() != str(curr_cols[col].get("data_type", "")).lower():
                type_changes[col] = {
                    "from": prev_cols[col].get("data_type"),
                    "to": curr_cols[col].get("data_type"),
                }
        prev_pk = sorted(prev_tables[table].get("primary_key", []) or [])
        curr_pk = sorted(curr_tables[table].get("primary_key", []) or [])
        table_changed = new_cols or gone_cols or type_changes or (prev_pk != curr_pk)
        if table_changed:
            added_columns[table] = new_cols
            removed_columns[table] = gone_cols
            datatype_changed[table] = type_changes
            pk_changed[table] = {"from": prev_pk, "to": curr_pk}
            drift["changed_tables"].append(table)
            drift["has_changes"] = True

    if added_columns:
        drift["columns_added"] = added_columns
    if removed_columns:
        drift["columns_removed"] = removed_columns
    if datatype_changed:
        drift["datatypes_changed"] = datatype_changed
    if pk_changed:
        drift["primary_keys_changed"] = pk_changed

    # FK structure: declared constraints added/removed.
    prev_declared = _edge_set(previous)
    curr_declared = _edge_set(current)
    declared_added = sorted(prev_declared - curr_declared, key=str)
    declared_removed = sorted(curr_declared - prev_declared, key=str)
    if declared_added:
        drift["declared_fk_removed"] = declared_added
        drift["has_changes"] = True
    if declared_removed:
        drift["declared_fk_added"] = declared_removed
        drift["has_changes"] = True

    # Inferred relationships added/removed.
    prev_inferred = _inferred_set(previous)
    curr_inferred = _inferred_set(current)
    inf_added = sorted(curr_inferred - prev_inferred, key=str)
    inf_removed = sorted(prev_inferred - curr_inferred, key=str)
    if inf_added:
        drift["relationships_inferred_added"] = inf_added
        drift["has_changes"] = True
    if inf_removed:
        drift["relationships_inferred_removed"] = inf_removed
        drift["has_changes"] = True

    return drift


def build_schema_mapping(conn, schema="public", db_type="postgresql", llm=None, database_name=None,
                         previous_mapping=None):
    tables = get_tables_and_columns(conn, schema, db_type)
    primary_keys = get_primary_keys(conn, schema, db_type)
    unique_keys = get_unique_keys(conn, schema, db_type)
    inferred_primary_keys = infer_primary_keys(tables, primary_keys)
    inferred_primary_keys.update(infer_primary_keys_from_data(
        conn, tables, schema, db_type,
        {**primary_keys, **inferred_primary_keys},
    ))
    declared_fks = get_declared_foreign_keys(conn, schema, db_type)
    null_stats = get_null_stats(conn, tables, schema, db_type)

    from schema_engine.relationships import infer_relationships as _pipeline

    merged_primary_keys = {**primary_keys, **inferred_primary_keys}
    inferred_fks, ambiguous_fks, registry = _pipeline(
        tables, merged_primary_keys, declared_fks,
        conn=conn, schema=schema, db_type=db_type,
        null_stats=null_stats,
    )

    # Refinement: a column confirmed (by data) to reference another table is a
    # foreign key, not the table's own identity. Ruling those out can resolve
    # ambiguous key candidates (e.g. a warranty table where both claim_id and
    # sale_id are unique — sale_id provably points at sales, so claim_id wins).
    fk_sources = {(r["table"], r["column"]) for r in inferred_fks
                  if r.get("confidence") in ("data-confirmed", "data-inferred")}
    if fk_sources:
        refined = infer_primary_keys_from_data(
            conn, tables, schema, db_type,
            {**primary_keys, **inferred_primary_keys},
            exclude_columns=fk_sources,
        )
        if refined:
            inferred_primary_keys.update(refined)
            merged_primary_keys = {**primary_keys, **inferred_primary_keys}
            inferred_fks, ambiguous_fks, registry = _pipeline(
                tables, merged_primary_keys, declared_fks,
                conn=conn, schema=schema, db_type=db_type,
            )

    mapping = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "database": database_name or os.getenv("DB_NAME") or "unknown_database",
        "schema": schema,
        "tables": {},
        "unique_keys": unique_keys,
        "declared_relationships": declared_fks,
        "inferred_relationships": inferred_fks,
        "ambiguous_relationships": ambiguous_fks,
        "relationship_edges": [],
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
            "confidence_score": rel.get("confidence_score"),
            "review_status": rel.get("review_status"),
            "ambiguous": rel.get("ambiguous"),
            "self_referencing": rel.get("self_referencing"),
            "cardinality": rel.get("cardinality"),
        })

    for table_name, columns in tables.items():
        table_primary_key = primary_keys.get(table_name, inferred_primary_keys.get(table_name, []))
        mapping["tables"][table_name] = {
            "columns": columns,
            "primary_key": table_primary_key,
            "inferred_primary_key": inferred_primary_keys.get(table_name, []),
            "unique_keys": unique_keys.get(table_name, []),
            "null_stats": null_stats.get(table_name, {}),
        }

    # Track all tables discovered in the DB (before dropping empties).
    all_db_tables = set(tables.keys())

    # Empty tables (0 rows) stay in the mapping with their structure intact so
    # the schema is fully described, but they are excluded from relationship
    # inference (a key built on no data cannot be confirmed).
    empty_tables = {
        t for t, col_stats in null_stats.items()
        if col_stats and all(s.get("total_rows", 1) == 0 for s in col_stats.values())
    }
    if empty_tables:
        for t in empty_tables:
            if t in mapping["tables"]:
                mapping["tables"][t]["empty"] = True
                mapping["tables"][t]["row_count"] = 0
        mapping["declared_relationships"] = [
            r for r in mapping["declared_relationships"]
            if r["table_name"] not in empty_tables and r["references_table"] not in empty_tables
        ]
        mapping["inferred_relationships"] = [
            r for r in mapping["inferred_relationships"]
            if r.get("table") not in empty_tables and r.get("references_table") not in empty_tables
        ]
        mapping["relationship_edges"] = [
            e for e in mapping["relationship_edges"]
            if e["source_table"] not in empty_tables and e["target_table"] not in empty_tables
        ]

    # Build summary metadata for the API response.
    mapping["summary"] = {
        "total_db_tables": len(all_db_tables),
        "tables_used": len(mapping["tables"]),
        "empty_tables": sorted(empty_tables),
        "declared_fk_count": len(mapping["declared_relationships"]),
        "inferred_fk_count": len(mapping["inferred_relationships"]),
        "edge_count": len(mapping["relationship_edges"]),
        "tables_with_pk": sorted(
            t for t in mapping["tables"]
            if mapping["tables"][t].get("primary_key")
        ),
        "tables_without_pk": sorted(
            t for t in mapping["tables"]
            if not mapping["tables"][t].get("primary_key")
        ),
    }

    if llm is not None:
        mapping = enrich_with_llm(mapping, llm)

    if mapping.get("tables"):
        _drop_empty_key_columns(mapping, conn, schema, db_type)

    _canonicalize_mapping(mapping)

    # Item 9: build the explicit relationship graph (per-table outgoing and
    # incoming relationships) ARIA can consume directly for SQL generation /
    # RAG / query planning. Also detects many-to-many via junction tables
    # (item 2).
    mapping["relationship_graph"] = _build_relationship_graph(mapping)

    # Rich health report (drives the UI dashboard / QA checks).
    # Strong vs weak uses the STRUCTURED state (PART 12); the legacy confidence
    # strings remain only as provenance on each record.
    inferred = mapping.get("inferred_relationships", [])
    strong = [r for r in inferred
              if r.get("relationship_state") in ("CONFIRMED", "PROBABLE")]
    weak = [r for r in inferred
            if r.get("relationship_state") not in ("CONFIRMED", "PROBABLE")]
    # Item 10: human-review list for uncertain relationships.
    review_list = [
        {
            "table": r.get("table"),
            "column": r.get("column"),
            "references_table": r.get("references_table"),
            "references_column": r.get("references_column"),
            "confidence_score": r.get("confidence_score"),
            "confidence": r.get("confidence"),
            "confidence_level": r.get("confidence_level"),
            "relationship_state": r.get("relationship_state"),
            "evidence": r.get("evidence", []),
        }
        for r in inferred if r.get("review_status") in ("flagged", "review")
    ]
    # Ambiguous candidates (data cannot distinguish the real target) also go to
    # review so a human can arbitrate, but they never enter the accepted set.
    for r in mapping.get("ambiguous_relationships", []):
        review_list.append({
            "table": r.get("table"),
            "column": r.get("column"),
            "references_table": r.get("references_table"),
            "references_column": r.get("references_column"),
            "confidence_score": r.get("confidence_score"),
            "confidence": r.get("confidence"),
            "confidence_level": r.get("confidence_level"),
            "relationship_state": r.get("relationship_state"),
            "evidence": r.get("evidence", []),
        })
    review_list.sort(key=lambda x: (x.get("table") or "", x.get("column") or ""))

    # Truthful profiling budget (PART 8) - never hardcoded.
    budget_summary = registry.summary() if registry is not None else {}
    health = {
        "strong_inferred_fk_count": len(strong),
        "weak_inferred_fk_count": len(weak),
        "empty_table_count": len(empty_tables),
        "profile_budget_exhausted": budget_summary.get("profile_budget_exhausted", False),
        "profiling_status": budget_summary.get("profiling_status", "unknown"),
        "queries_used": budget_summary.get("queries_used"),
        "queries_remaining": budget_summary.get("queries_remaining"),
        "warning": None,
    }
    mapping["summary"]["health"] = health
    mapping["summary"]["review_list"] = review_list
    mapping["summary"]["review_count"] = len(review_list)
    # PART 14: rejected candidates are retained internally for debugging and
    # benchmarking even though they never enter the relationship lists.
    from schema_engine.serializer import serialize_rejected
    mapping["rejected_candidates"] = serialize_rejected(registry) if registry is not None else []

    # Item 5: schema drift vs the previous run of this database (when supplied).
    if previous_mapping:
        mapping["drift"] = detect_schema_drift(previous_mapping, mapping)

    return mapping


def _all_schemas_foreign_keys(conn, schemas):
    """Declared FKs across every mapped schema, with schema-qualified names.

    Runs once for the merged multi-schema mapping so cross-schema foreign keys
    (e.g. purchasing.productvendor -> production.product) survive qualification
    and join paths can span schemas.
    """
    query = """
        SELECT
            refn.nspname AS table_schema,
            refcon.relname AS table_name,
            refatt.attname AS column_name,
            conn.nspname AS references_schema,
            conrel.relname AS references_table,
            conatt.attname AS references_column
        FROM pg_constraint c
        JOIN pg_namespace refn ON refn.oid = c.connamespace
        JOIN pg_class refcon ON refcon.oid = c.conrelid
        JOIN pg_namespace conn ON conn.oid = (SELECT relnamespace FROM pg_class WHERE oid = c.confrelid)
        JOIN pg_class conrel ON conrel.oid = c.confrelid
        JOIN unnest(c.conkey) WITH ORDINALITY AS srckeys(attnum, ord) ON TRUE
        JOIN unnest(c.confkey) WITH ORDINALITY AS tgtkeys(attnum, ord) ON srckeys.ord = tgtkeys.ord
        JOIN pg_attribute refatt ON refatt.attrelid = c.conrelid AND refatt.attnum = srckeys.attnum
        JOIN pg_attribute conatt ON conatt.attrelid = c.confrelid AND conatt.attnum = tgtkeys.attnum
        WHERE c.contype = 'f'
          AND refn.nspname = ANY(%s)
        ORDER BY refn.nspname, refcon.relname, srckeys.ord;
    """
    with _dict_cursor(conn) as cur:
        cur.execute(query, (list(schemas),))
        rows = cur.fetchall()
        rels = []
        for r in rows:
            rel = {
                "table_name": f"{r['table_schema']}.{r['table_name']}",
                "column_name": r["column_name"],
                "references_table": f"{r['references_schema']}.{r['references_table']}",
                "references_column": r["references_column"],
                "schema": r["table_schema"],
                "references_schema": r["references_schema"],
            }
            rel["same_schema"] = bool(r["table_schema"] == r["references_schema"])
            rels.append(rel)
        return rels


def _infer_cross_schema_relationships(mapping, conn, db_type="postgresql"):
    """Global relationship inference across ALL schemas after the per-schema merge.

    Each schema's own pass already found intra-schema relationships. This pass
    searches for cross-schema edges (e.g. purchasing.productvendor.productid ->
    production.product.productid) that no single-schema pass could see, using the
    SAME generic evidence as normal inference (datatype compatibility, value
    overlap, uniqueness/PK-likeness, cardinality, null patterns, name and
    semantic similarity) on fully-qualified `schema.table.column` names.

    Only edges whose source and target schemas DIFFER are added, so intra-schema
    results are not duplicated. Edges already declared or already inferred are
    never re-emitted. Requires the mapping's tables to be schema-qualified and
    the connection to be available (no-op otherwise).
    """
    if conn is None:
        return
    tables = {
        qualified: info.get("columns", [])
        for qualified, info in mapping.get("tables", {}).items()
        if not info.get("empty")
    }
    if not tables:
        return
    schemas = {t.split(".", 1)[0] for t in tables if "." in t}
    if len(schemas) < 2:
        return  # single schema -> nothing cross-schema to find

    primary_keys = {
        qualified: list(info.get("primary_key", []) or [])
        for qualified, info in mapping.get("tables", {}).items()
    }
    declared = mapping.get("declared_relationships", [])
    from schema_engine.relationships import infer_relationships as _xs_pipeline
    cross, cross_ambiguous, cross_registry = _xs_pipeline(
        tables, primary_keys, declared,
        conn=conn, schema="", db_type=db_type,
    )

    existing = {
        (r.get("table"), r.get("column"), r.get("references_table"))
        for r in mapping.get("inferred_relationships", [])
    }
    existing |= {
        (r.get("table_name"), r.get("column_name"), r.get("references_table"))
        for r in declared
    }

    # Cross-schema candidates use the SAME pipeline and the SAME acceptance
    # state as intra-schema ones (PART 15): there is no separate cross-schema
    # acceptance rule. Only the structured relationship_state decides whether
    # an edge is emitted; everything else is surfaced for human review.
    added = []
    for r in cross:
        src_schema = r.get("schema")
        tgt_schema = r.get("references_schema")
        if src_schema and tgt_schema and src_schema == tgt_schema:
            continue  # intra-schema; already found by the per-schema pass
        key = (r.get("table"), r.get("column"), r.get("references_table"))
        if key in existing:
            continue
        if r.get("relationship_state") not in ("CONFIRMED", "PROBABLE"):
            r["relationship_state"] = "UNCERTAIN"
            r["review_status"] = "review"
            mapping.setdefault("_cross_schema_review", []).append(r)
            continue
        r["same_schema"] = False
        r["note"] = (r.get("note") or "") + (
            " Detected by the global cross-schema inference pass."
        )
        added.append(r)

    if added:
        mapping["inferred_relationships"].extend(added)
        for rel in added:
            mapping["relationship_edges"].append({
                "source_table": rel["table"],
                "source_column": rel["column"],
                "target_table": rel["references_table"],
                "target_column": rel["references_column"],
                "type": "inferred",
                "confidence": rel.get("confidence", "heuristic"),
                "confidence_score": rel.get("confidence_score"),
                "confidence_band": rel.get("confidence_band"),
                "relationship_state": rel.get("relationship_state"),
                "review_status": rel.get("review_status"),
                "ambiguous": rel.get("ambiguous"),
                "self_referencing": rel.get("self_referencing"),
                "cardinality": rel.get("cardinality"),
            })

    # Ambiguous cross-schema candidates: keep them visible for human review
    # even though they are never accepted as edges (same pipeline, same rule).
    for r in cross_ambiguous:
        r["relationship_state"] = "UNCERTAIN"
        r["review_status"] = "review"
        mapping.setdefault("_cross_schema_review", []).append(r)
    # Rejected cross-schema candidates are also retained (PART 14) rather than
    # disappearing, so benchmarks/debugging can explain every non-edge.
    if cross_registry is not None and cross_registry.rejected:
        mapping.setdefault("_cross_schema_rejected", []).extend(
            cross_registry.rejected)


def build_schema_mapping_all(conn, db_type="postgresql", llm=None, database_name=None,
                             previous_mapping=None):
    """Build a merged mapping across every populated schema in a database.

    Used only when `detect_schema_mode` reports more than one schema (e.g.
    AdventureWorks). Each schema is extracted with the existing single-schema
    pipeline, then merged with schema-qualified table names
    (`sales.salesorderheader`) so the Goal Agent can answer questions that span
    schemas. Single-schema databases never hit this path.
    """
    schemas = list_schemas_with_tables(conn)
    schema_health = []
    mapping = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "database": database_name or os.getenv("DB_NAME") or "unknown_database",
        "schema": "*",
        "schemas": schemas,
        "tables": {},
        "unique_keys": {},
        "declared_relationships": [],
        "inferred_relationships": [],
        "relationship_edges": [],
    }

    for schema in schemas:
        sub = build_schema_mapping(
            conn, schema, db_type=db_type, llm=None,
            database_name=database_name, previous_mapping=None,
        )
        # Aggregate truthful profiling budget per schema (PART 8).
        _h = (sub.get("summary") or {}).get("health") or {}
        schema_health.append(_h)
        for table_name, info in sub.get("tables", {}).items():
            qualified = f"{schema}.{table_name}"
            mapping["tables"][qualified] = info
            mapping["unique_keys"].update(
                {f"{schema}.{t}": v for t, v in sub.get("unique_keys", {}).items()}
            )
        for rel in sub.get("declared_relationships", []):
            mapping["declared_relationships"].append({
                "table_name": f"{schema}.{rel['table_name']}",
                "column_name": rel["column_name"],
                "references_table": f"{schema}.{rel['references_table']}",
                "references_column": rel["references_column"],
            })
        for rel in sub.get("inferred_relationships", []):
            mapping["inferred_relationships"].append({
                "table": f"{schema}.{rel['table']}",
                "column": rel["column"],
                "references_table": f"{schema}.{rel['references_table']}",
                "references_column": rel["references_column"],
                "confidence": rel.get("confidence", "heuristic"),
                "confidence_score": rel.get("confidence_score"),
                "confidence_band": rel.get("confidence_band"),
                "relationship_state": rel.get("relationship_state"),
                "review_status": rel.get("review_status"),
                "ambiguous": rel.get("ambiguous"),
                "self_referencing": rel.get("self_referencing"),
                "cardinality": rel.get("cardinality"),
                "evidence": rel.get("evidence", []),
                "evidence_detail": rel.get("evidence_detail"),
                "note": rel.get("note", ""),
                "schema": schema,
                "references_schema": schema,
                "same_schema": True,
            })
        for rel in sub.get("ambiguous_relationships", []):
            mapping.setdefault("_cross_schema_review", []).append({
                "table": f"{schema}.{rel['table']}",
                "column": rel["column"],
                "references_table": f"{schema}.{rel['references_table']}",
                "references_column": rel["references_column"],
                "confidence": rel.get("confidence", "heuristic"),
                "confidence_score": rel.get("confidence_score"),
                "confidence_band": rel.get("confidence_band"),
                "relationship_state": "uncertain",
                "review_status": "review",
                "ambiguous": rel.get("ambiguous"),
                "evidence": rel.get("evidence", []),
                "note": "Ambiguous candidate - data cannot distinguish best target.",
                "schema": schema,
                "references_schema": schema,
            })

    # Cross-schema declared FKs replace the per-schema (same-schema-only) list,
    # so join paths can span schemas and qualification is consistent.
    mapping["declared_relationships"] = _all_schemas_foreign_keys(conn, schemas)

    for rel in mapping["declared_relationships"]:
        mapping["relationship_edges"].append({
            "source_table": rel["table_name"],
            "source_column": rel["column_name"],
            "target_table": rel["references_table"],
            "target_column": rel["references_column"],
            "type": "declared",
        })
    for rel in mapping["inferred_relationships"]:
        mapping["relationship_edges"].append({
            "source_table": rel["table"],
            "source_column": rel["column"],
            "target_table": rel["references_table"],
            "target_column": rel["references_column"],
            "type": "inferred",
            "confidence": rel.get("confidence", "heuristic"),
            "confidence_score": rel.get("confidence_score"),
            "confidence_band": rel.get("confidence_band"),
            "relationship_state": rel.get("relationship_state"),
            "review_status": rel.get("review_status"),
            "ambiguous": rel.get("ambiguous"),
            "self_referencing": rel.get("self_referencing"),
            "cardinality": rel.get("cardinality"),
        })

    empty_tables = {
        t for t, info in mapping["tables"].items()
        if info.get("empty")
    }
    for t in empty_tables:
        if t in mapping["tables"]:
            mapping["tables"][t]["empty"] = True
            mapping["tables"][t]["row_count"] = 0
    mapping["declared_relationships"] = [
        r for r in mapping["declared_relationships"]
        if r["table_name"] not in empty_tables and r["references_table"] not in empty_tables
    ]
    mapping["inferred_relationships"] = [
        r for r in mapping["inferred_relationships"]
        if r.get("table") not in empty_tables and r.get("references_table") not in empty_tables
    ]
    mapping["relationship_edges"] = [
        e for e in mapping["relationship_edges"]
        if e["source_table"] not in empty_tables and e["target_table"] not in empty_tables
    ]

    # Global cross-schema inference (txt): after per-schema extraction and
    # merge, search across ALL schemas for edges no single-schema pass can see
    # (e.g. purchasing.productvendor -> production.product). Uses the same
    # generic evidence as normal inference on schema-qualified names.
    _infer_cross_schema_relationships(mapping, conn, db_type)

    _canonicalize_mapping(mapping)
    mapping["relationship_graph"] = _build_relationship_graph(mapping)

    inferred = mapping.get("inferred_relationships", [])
    strong = [r for r in inferred if r.get("confidence") in
              ("data-confirmed", "llm-confirmed", "composite-data-confirmed")]
    weak = [r for r in inferred if r.get("confidence") not in
            ("data-confirmed", "llm-confirmed", "composite-data-confirmed")]
    review_list = [
        {
            "table": r.get("table"),
            "column": r.get("column"),
            "references_table": r.get("references_table"),
            "references_column": r.get("references_column"),
            "confidence_score": r.get("confidence_score"),
            "confidence": r.get("confidence"),
            "evidence": r.get("evidence", []),
        }
        for r in inferred if r.get("review_status") in ("flagged", "review")
    ]
    # Cross-schema candidates that lacked strong evidence are surfaced as
    # review items too, so a human can confirm genuine cross-schema FKs without
    # the engine auto-declaring weak value-overlap edges.
    for r in mapping.get("_cross_schema_review", []):
        review_list.append({
            "table": r.get("table"),
            "column": r.get("column"),
            "references_table": r.get("references_table"),
            "references_column": r.get("references_column"),
            "confidence_score": r.get("confidence_score"),
            "confidence": r.get("confidence"),
            "evidence": r.get("evidence", []),
            "note": r.get("note"),
        })
    review_list.sort(key=lambda x: (x.get("table") or "", x.get("column") or ""))
    mapping["summary"] = {
        "total_db_tables": len(mapping["tables"]),
        "tables_used": len(mapping["tables"]),
        "empty_tables": sorted(empty_tables),
        "declared_fk_count": len(mapping["declared_relationships"]),
        "inferred_fk_count": len(inferred),
        "edge_count": len(mapping["relationship_edges"]),
        "tables_with_pk": sorted(
            t for t in mapping["tables"]
            if mapping["tables"][t].get("primary_key")
        ),
        "tables_without_pk": sorted(
            t for t in mapping["tables"]
            if not mapping["tables"][t].get("primary_key")
        ),
        "health": {
            "strong_inferred_fk_count": len(strong),
            "weak_inferred_fk_count": len(weak),
            "empty_table_count": len(empty_tables),
            "profile_budget_exhausted": bool(
                any(h.get("profile_budget_exhausted") for h in schema_health)
            ),
            "profiling_status": (
                "exhausted" if any(h.get("profile_budget_exhausted") for h in schema_health)
                else "active" if schema_health else "unknown"
            ),
            "queries_used": sum(h.get("queries_used") or 0 for h in schema_health),
            "queries_remaining": sum(h.get("queries_remaining") or 0 for h in schema_health),
            "warning": None,
        },
        "review_list": review_list,
        "review_count": len(review_list),
    }

    if llm is not None:
        mapping = enrich_with_llm(mapping, llm)

    if previous_mapping:
        mapping["drift"] = detect_schema_drift(previous_mapping, mapping)

    mapping.pop("_cross_schema_review", None)
    return mapping


SNAPSHOT_KEEP = 20  # max snapshot files retained per (user, database) file set


def _prune_snapshots(directory, stem, suffix, keep=SNAPSHOT_KEEP):
    """Delete the oldest snapshot files for a file set, keeping the newest `keep`.

    Never touches the base file ({stem}{suffix}) or the {stem}_latest alias.
    """
    try:
        snapshots = [
            p for p in Path(directory).glob(f"{stem}_*.json")
            if p.name != f"{stem}_latest{suffix}"
        ]
        if len(snapshots) <= keep:
            return
        snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in snapshots[keep:]:
            try:
                stale.unlink()
            except OSError:
                pass
    except OSError:
        pass


def get_output_paths(output_path, db_name=None, snapshot_id=None):
    """Return the base output, a unique snapshot, the latest alias, and the snapshot id.

    Every database (when `db_name` is given) gets its own file set:

        schema_mapping_<db>.json          - canonical base (overwritten each run)
        schema_mapping_<db>_latest.json   - stable pointer for the active session
        schema_mapping_<db>_<id>.json     - unique snapshot, never overwritten

    The snapshot file name embeds the same `snapshot_id` that the mapping JSON
    carries, so the JSON and its file are always correlated. Old snapshots beyond
    SNAPSHOT_KEEP are pruned. Returns (base, snapshot, latest, snapshot_id).
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    stem, suffix = output.stem, output.suffix or ".json"

    if db_name:
        safe_db = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(db_name))[:64] or "db"
        stem = f"{stem}_{safe_db}"

    if not snapshot_id:
        snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    # Guarantee a filename that does not already exist, so a snapshot is never
    # overwritten (unique within and across users, DBs, and processes).
    candidate = f"{stem}_{snapshot_id}{suffix}"
    counter = 1
    while (output.parent / candidate).exists():
        candidate = f"{stem}_{snapshot_id}_{counter}{suffix}"
        counter += 1

    base = output.with_name(f"{stem}{suffix}")
    snapshot = output.with_name(candidate)
    latest = output.with_name(f"{stem}_latest{suffix}")

    _prune_snapshots(output.parent, stem, suffix)
    used_id = candidate[len(stem) + 1:-len(suffix)]
    return base, snapshot, latest, used_id


# ---------------------------------------------------------------------------
# File source handling (semi-structured path: CSV / tabular PDF)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ARIA Schema Agent - relational database schema understanding")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--schema", default=None)
    parser.add_argument("--db-type", choices=["postgresql", "mysql"], default="postgresql")
    parser.add_argument("--output", default=str(SCHEMA_DIR / "schema_mapping.json"))
    parser.add_argument(
        "--provider", choices=["local", "cloud"], default=None,
        help="Enable LLM-assisted reasoning over the extracted schema via this backend "
             "(local = Ollama, cloud = Groq). "
             "When omitted, only deterministic heuristics are used.",
    )
    args = parser.parse_args()

    # MySQL has no named schemas separate from the database: its
    # information_schema uses the database name as the "schema". Resolve the
    # filter the same way the API route does, so `--db-type mysql --db X`
    # works out of the box instead of silently returning zero tables.
    schema = args.schema or (args.db if args.db_type == "mysql" else "public")

    llm = None
    if args.provider:
        llm = create_provider(provider=args.provider)

    conn = get_connection(args)
    try:
        # PostgreSQL: if no schema was requested, auto-detect the one that
        # actually contains tables (public is the default but many databases
        # put their tables in app / core / dbo-equivalent schemas). When the
        # database spans several populated schemas, map all of them with
        # schema-qualified table names instead of picking just the largest.
        multi_schema = False
        if not args.schema and args.db_type != "mysql":
            mode = detect_schema_mode(conn)
            multi_schema = mode["mode"] == "multi"
            if multi_schema:
                schema = "*"
            else:
                schema = mode["schemas"][0] if mode["schemas"] else "public"
            print(f"Detected schema mode '{mode['mode']}' "
                  f"({len(mode['schemas'])} schema(s): {', '.join(mode['schemas']) or 'none'}).")
        print(f"Connected ({args.db_type}). Extracting schema for '{schema}' schema...")

        # Item 5: seed drift detection from the previous run of this database
        # (the {stem}_latest.json alias), if one exists.
        previous_mapping = None
        try:
            prev_base = Path(args.output)
            prev_stem = prev_base.stem
            if args.db:
                safe_db = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(args.db))[:64] or "db"
                prev_stem = f"{prev_stem}_{safe_db}"
            prev_latest = prev_base.with_name(f"{prev_stem}_latest{prev_base.suffix or '.json'}")
            if prev_latest.exists():
                with open(prev_latest, encoding="utf-8") as fh:
                    previous_mapping = json.load(fh)
        except Exception as exc:
            logger.debug("could not load previous schema for drift detection: %s", exc)

        if multi_schema:
            mapping = build_schema_mapping_all(conn, db_type=args.db_type, llm=llm,
                                               database_name=args.db,
                                               previous_mapping=previous_mapping)
        else:
            mapping = build_schema_mapping(conn, schema, db_type=args.db_type, llm=llm,
                                           database_name=args.db,
                                           previous_mapping=previous_mapping)
        if not mapping.get("tables"):
            sys.exit(
                f"ERROR: no tables found in schema '{schema}' ({args.db_type}). "
                "The schema is empty or does not exist; nothing was mapped."
            )
        db_name = mapping.get("database", args.db or "unknown")
    finally:
        conn.close()

    output_path, timestamped_path, latest_path, snapshot_id = get_output_paths(
        args.output, db_name or None, snapshot_id=mapping.get("snapshot_id")
    )
    mapping["snapshot_id"] = snapshot_id

    for path in (output_path, timestamped_path, latest_path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)

    n_tables = len(mapping["tables"])
    n_declared = len(mapping["declared_relationships"])
    n_inferred = len(mapping["inferred_relationships"])
    print(f"Done. {n_tables} tables, {n_declared} declared relationships, "
          f"{n_inferred} inferred relationships.")
    if mapping.get("llm_reasoning"):
        print(f"LLM-assisted reasoning applied via {mapping['llm_reasoning'].get('provider')} "
              f"(model {mapping['llm_reasoning'].get('model')}).")
    drift = mapping.get("drift")
    if drift:
        if drift.get("has_changes"):
            print(f"Schema drift detected: {len(drift.get('new_tables', []))} new table(s), "
                  f"{len(drift.get('removed_tables', []))} removed, "
                  f"{len(drift.get('columns_added', {}))} table(s) with column changes, "
                  f"{len(drift.get('relationships_inferred_added', []))} new inferred relationship(s).")
        else:
            print("Schema drift: no changes since the previous run.")
    print(f"Written to {output_path}")
    print(f"Saved fresh snapshot to {timestamped_path}")
    print(f"Updated latest copy at {latest_path}")


if __name__ == "__main__":
    main()
