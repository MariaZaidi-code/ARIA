"""Database-aware SQL engine for Copilot.

Generates, validates and executes read-only analytical SQL against PostgreSQL,
MySQL or SQLite using the same code path. Reuses ARIA's existing read-only
guard (core.validation) and the shared SQLAlchemy engine built by the session,
so there is ONE database abstraction — not one per engine.

Dialect differences (date truncation, identifier quoting, LIMIT) are handled
in the prompt and the validator, never with per-schema hardcoding.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import create_engine, text

from core.validation import (
    strip_code_fences,
    unknown_sql_columns,
    unknown_sql_tables,
)

log = logging.getLogger(__name__)


# Bounded engine cache: avoids pinning credential-bearing URIs forever
# (previous @lru_cache never closed/expired). TTL + explicit dispose keep
# memory bounded; cache key is a redacted fingerprint, never the raw URI.
_ENGINE_CACHE: dict = {}
_ENGINE_CACHE_TTL_S = 600
_ENGINE_CACHE_MAX = 8
try:
    import threading as _threading
    _ENGINE_LOCK = _threading.Lock()
except Exception:  # pragma: no cover
    _ENGINE_LOCK = None


def _cache_key(db_uri: str) -> str:
    import hashlib as _hl
    try:
        return _hl.sha256(db_uri.encode("utf-8")).hexdigest()[:32]
    except Exception:
        return str(abs(hash(db_uri)))


def _get_engine(db_uri: str):
    import time as _time
    key = _cache_key(db_uri)
    now = _time.monotonic()
    lock = _ENGINE_LOCK
    try:
        if lock is not None:
            lock.acquire()
        entry = _ENGINE_CACHE.get(key)
        if entry is not None:
            eng, _stored_uri, ts = entry
            if now - ts < _ENGINE_CACHE_TTL_S:
                return eng
            try:
                eng.dispose()
            except Exception:
                pass
            _ENGINE_CACHE.pop(key, None)
        eng = create_engine(db_uri, pool_pre_ping=True, pool_recycle=1800)
        if len(_ENGINE_CACHE) >= _ENGINE_CACHE_MAX:
            try:
                oldest = min(_ENGINE_CACHE.items(), key=lambda kv: kv[1][2])[0]
                try:
                    _ENGINE_CACHE[oldest][0].dispose()
                except Exception:
                    pass
                _ENGINE_CACHE.pop(oldest, None)
            except Exception:
                pass
        _ENGINE_CACHE[key] = (eng, db_uri, now)
        return eng
    finally:
        try:
            if lock is not None:
                lock.release()
        except Exception:
            pass


def dispose_engines() -> None:
    """Close all cached engines (tests / shutdown). Never raises."""
    try:
        if _ENGINE_LOCK is not None:
            _ENGINE_LOCK.acquire()
        for _k, (eng, _u, _t) in list(_ENGINE_CACHE.items()):
            try:
                eng.dispose()
            except Exception:
                pass
        _ENGINE_CACHE.clear()
    except Exception:
        pass
    finally:
        try:
            if _ENGINE_LOCK is not None:
                _ENGINE_LOCK.release()
        except Exception:
            pass

# Deterministic read-only guard: reject anything that can mutate data/schema.
_LIMIT_RE = re.compile(r"\blimit\s+\d+", re.IGNORECASE)
_GROUP_BY_RE = re.compile(r"\bgroup\s+by\b", re.IGNORECASE)
_AGG_RE = re.compile(r"\b(count|sum|avg|min|max)\s*\(", re.IGNORECASE)


@dataclass
class SqlResult:
    ok: bool
    sql: str | None = None
    columns: list[str] = None
    rows: list[dict] = None
    row_count: int = 0
    error: str | None = None
    attempts: int = 1
    dialect: str = "postgresql"

    def __post_init__(self):
        if self.columns is None:
            self.columns = []
        if self.rows is None:
            self.rows = []


def is_read_only(sql: str) -> bool:
    """True only for SELECT / WITH ... SELECT statements. Deterministic.

    Delegates to the single shared guard in core.validation so Copilot and
    the Goal Agent enforce the same contract.
    """
    from core.validation import is_read_only_sql as _shared_is_read_only
    return _shared_is_read_only(sql)


def clean_sql(raw: str) -> str:
    """Extract a single SQL statement from possibly fenced/chatty LLM output."""
    if not raw:
        return ""
    candidate = strip_code_fences(raw) or raw
    # Keep everything from the first SELECT/WITH keyword onward.
    m = re.search(r"\b(select|with)\b", candidate, re.IGNORECASE)
    if not m:
        return candidate.strip()
    stmt = candidate[m.start():].strip()
    # For CTEs (WITH ... ; SELECT ...), find the last semicolon-terminated
    # statement so the full CTE + final SELECT is preserved.
    semi = stmt.rfind(";")
    if semi != -1:
        stmt = stmt[:semi]
    return stmt.strip()


def _dialect_rules(dialect: str) -> str:
    if dialect == "mysql":
        return (
            "MySQL syntax: quote identifiers with backticks (always quote names "
            "containing spaces or special characters, e.g. `Order Date`), use "
            "DATE_FORMAT(col, '%Y-%m') for month grouping and CURDATE()/NOW() "
            "for current time. There is no ILIKE; use LIKE. Use LIMIT for row caps."
        )
    if dialect == "sqlite":
        return (
            "SQLite syntax: use strftime('%Y-%m', col) for month grouping and "
            "date('now') for current date. Column names may contain spaces — "
            "always wrap such names in double quotes (e.g. \"Order Date\"). "
            "Use LIMIT for row caps."
        )
    return (
        "PostgreSQL syntax: use date_trunc('month', col) for month grouping and "
        "CURRENT_DATE for today. You may use ILIKE for case-insensitive match. "
        "Always double-quote identifiers containing spaces or mixed case. Use LIMIT."
    )


def build_sql_prompt(question: str, ctx, dialect: str, feedback: str | None = None) -> str:
    """Compose the SQL-generation prompt from retrieved context only."""
    schema_block = ctx.to_prompt() if hasattr(ctx, "to_prompt") else str(ctx)
    retry_block = ""
    if feedback:
        retry_block = (
            "\nThe previous attempt failed with this error — fix the SQL:\n"
            f"{feedback}\n"
        )
    return (
        "You are a senior data analyst. Write ONE read-only SQL query that answers "
        "the user's business question using ONLY the tables and relationships below.\n\n"
        f"DATABASE DIALECT: {dialect}\n{_dialect_rules(dialect)}\n\n"
        f"SCHEMA CONTEXT (retrieved, not the full schema):\n{schema_block}\n\n"
        f"QUESTION: {question}\n{retry_block}\n"
        "Rules:\n"
        "- Return aggregation at the granularity the question asks for "
        "(one row per group, month, product, customer, etc.).\n"
        "- Use only SELECT (never modify data).\n"
        "- Reference only the tables/columns provided; join via the relationships shown.\n"
        "- Lines starting with 'Previous ' are conversation context from an earlier "
        "question, never schema: FROM/JOIN only tables named under SCHEMA CONTEXT.\n"
        "- Add a LIMIT (<= 1000) unless the question is a single summary value.\n"
        "- Output ONLY the SQL statement, no explanation, no markdown fences.\n"
    )


class SqlEngine:
    """Runs validated read-only SQL against a SQLAlchemy URI."""

    def __init__(self, db_uri: str, dialect: str = "postgresql",
                 max_rows: int = 1000, max_attempts: int = 3):
        self.db_uri = db_uri
        self.dialect = dialect or "postgresql"
        self.max_rows = int(max_rows)
        self.max_attempts = int(max_attempts)

    # -- validation ------------------------------------------------------

    def validate(self, sql: str, tables: dict | None = None) -> tuple[bool, str | None]:
        if not sql:
            return False, "No SQL generated."
        if not is_read_only(sql):
            return False, "Rejected: only read-only SELECT statements are allowed."
        if tables:
            bad_tables = unknown_sql_tables(sql, list(tables.keys()))
            if bad_tables:
                return False, f"Unknown table(s): {', '.join(bad_tables)}."
            cols_by_table = {}
            for t, info in tables.items():
                cols = info.get("columns", [])
                if isinstance(cols, list):
                    cols_by_table[t] = [c.get("column") if isinstance(c, dict) else c for c in cols]
                elif isinstance(cols, dict):
                    cols_by_table[t] = list(cols.keys())
            bad_cols = unknown_sql_columns(sql, cols_by_table)
            if bad_cols:
                return False, f"Unknown column reference(s): {', '.join(bad_cols[:5])}."
        return True, None

    # -- execution -------------------------------------------------------

    def execute(self, sql: str, tables: dict | None = None) -> SqlResult:
        ok, reason = self.validate(sql, tables)
        if not ok:
            return SqlResult(ok=False, sql=sql, error=reason, dialect=self.dialect)

        safe_sql = sql
        # Row cap without rewriting grouped/aggregate semantics: only append
        # SQL LIMIT to plain row queries. Grouped/aggregate queries keep their
        # grain; fetchmany() still bounds returned rows.
        if not _LIMIT_RE.search(sql) and self.dialect in ("postgresql", "mysql", "sqlite"):
            if not (_GROUP_BY_RE.search(sql) or _AGG_RE.search(sql)):
                safe_sql = f"{sql.rstrip(';')} LIMIT {self.max_rows}"

        try:
            engine = _get_engine(self.db_uri)
            with engine.connect() as conn:
                result = conn.execute(text(safe_sql))
                columns = list(result.keys())
                rows = [dict(zip(columns, r)) for r in result.fetchmany(self.max_rows)]
            return SqlResult(ok=True, sql=safe_sql, columns=columns, rows=rows,
                             row_count=len(rows), dialect=self.dialect)
        except Exception as exc:
            try:
                from core.errors import sanitize_error as _san
                err = _san(exc)
            except Exception:
                err = "Database query failed."
            return SqlResult(ok=False, sql=safe_sql, error=str(err)[:400],
                             dialect=self.dialect)

    def generate_and_run(self, question: str, ctx, llm, tables: dict | None = None,
                         model_role: str = "sql") -> SqlResult:
        """Generate SQL via the (provider-independent) LLM, then execute.

        One bounded repair attempt on failure — no infinite loop, and failures
        are surfaced gracefully rather than crashing the Copilot.
        """
        feedback = None
        last = SqlResult(ok=False, error="not started", dialect=self.dialect)
        for attempt in range(1, self.max_attempts + 1):
            prompt = build_sql_prompt(question, ctx, self.dialect, feedback)
            try:
                # SQL answers are short: cap tokens so CPU inference finishes
                # well inside the timeout instead of timing out mid-generation.
                # Repair attempts use light sampling so an empty first pass
                # does not repeat identically.
                raw = llm.complete(model_role, prompt, temperature=0.0 if attempt == 1 else 0.2,
                                   num_predict=300)
            except Exception as exc:
                return SqlResult(ok=False, error=f"LLM SQL generation failed: {exc}",
                                 attempts=attempt, dialect=self.dialect)
            sql = clean_sql(raw)
            result = self.execute(sql, tables)
            result.attempts = attempt
            if result.ok:
                return result
            last = result
            feedback = result.error
            # Point the repair at the valid tables so a hallucinated table
            # name gets replaced instead of repeated.
            if tables and "Unknown table" in (result.error or ""):
                feedback += f" Valid tables: {', '.join(sorted(tables.keys()))}."
            log.info("Copilot SQL attempt %d failed: %s", attempt, result.error)
        return last