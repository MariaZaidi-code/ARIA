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

# Deterministic read-only guard: reject anything that can mutate data/schema.
_DESTRUCTIVE_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|replace|"
    r"merge|call|execute|copy|vacuum|attach|detach|pragma|set\s+role|commit|"
    r"rollback|into)\b",
    re.IGNORECASE,
)
_STRIP_STRINGS_RE = re.compile(r"'(?:''|[^'])*'")
_LIMIT_RE = re.compile(r"\blimit\s+\d+", re.IGNORECASE)


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
    """True only for SELECT / WITH ... SELECT statements. Deterministic."""
    if not sql:
        return False
    stripped = _STRIP_STRINGS_RE.sub(" ", sql)
    if _DESTRUCTIVE_RE.search(stripped):
        return False
    return bool(re.match(r"\s*(select|with)\b", stripped, re.IGNORECASE))


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
    # Cut a trailing explanation after the first semicolon-terminated statement.
    semi = stmt.find(";")
    if semi != -1:
        stmt = stmt[:semi]
    return stmt.strip()


def _dialect_rules(dialect: str) -> str:
    if dialect == "mysql":
        return (
            "MySQL syntax: quote identifiers with backticks, use DATE_FORMAT(col, '%Y-%m') "
            "for month grouping and CURDATE()/NOW() for current time. "
            "There is no ILIKE; use LIKE. Use LIMIT for row caps."
        )
    if dialect == "sqlite":
        return (
            "SQLite syntax: use strftime('%Y-%m', col) for month grouping and "
            "date('now') for current date. Use LIMIT for row caps."
        )
    return (
        "PostgreSQL syntax: use date_trunc('month', col) for month grouping and "
        "CURRENT_DATE for today. You may use ILIKE for case-insensitive match. Use LIMIT."
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
        "- Add a LIMIT (<= 1000) unless the question is a single summary value.\n"
        "- Output ONLY the SQL statement, no explanation, no markdown fences.\n"
    )


class SqlEngine:
    """Runs validated read-only SQL against a SQLAlchemy URI."""

    def __init__(self, db_uri: str, dialect: str = "postgresql",
                 max_rows: int = 1000, max_attempts: int = 2):
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
        if not _LIMIT_RE.search(sql) and self.dialect in ("postgresql", "mysql", "sqlite"):
            safe_sql = f"{sql.rstrip(';')} LIMIT {self.max_rows}"

        try:
            engine = create_engine(self.db_uri, pool_pre_ping=True)
            try:
                with engine.connect() as conn:
                    result = conn.execute(text(safe_sql))
                    columns = list(result.keys())
                    rows = [dict(zip(columns, r)) for r in result.fetchmany(self.max_rows)]
            finally:
                engine.dispose()
            return SqlResult(ok=True, sql=safe_sql, columns=columns, rows=rows,
                             row_count=len(rows), dialect=self.dialect)
        except Exception as exc:
            return SqlResult(ok=False, sql=safe_sql, error=str(exc)[:400],
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
                raw = llm.complete(model_role, prompt, temperature=0.0,
                                   num_predict=700, timeout=30)
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
            log.info("Copilot SQL attempt %d failed: %s", attempt, result.error)
        return last