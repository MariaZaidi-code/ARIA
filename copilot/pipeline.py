"""ARIA Copilot RAG pipeline (provider-independent).

    User question
      -> intent / question understanding (deterministic + conversation memory)
      -> RAG retrieval (schema index + hybrid ranking)
      -> context construction (selected tables/relationships only)
      -> LLM abstraction (Ollama OR Groq, same prompts)
      -> SQL generation
      -> SQL validation (read-only + known tables/columns)
      -> DB execution (PostgreSQL / MySQL / SQLite)
      -> result validation
      -> natural-language response
      -> dynamic chart-ready output

The LLM is passed in as an object exposing `.complete(role, prompt, ...)` /
`.chat(role, messages, ...)` — exactly the interface ARIA's existing
`llm_provider.LLMProvider` implements for BOTH Ollama and Groq. This module
never branches on the provider, and never touches the database directly.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from .conversation import ConversationMemory
from .retriever import SchemaRetriever, RetrievedContext
from .schema_index import build_schema_index
from .sql_engine import SqlEngine, clean_sql

log = logging.getLogger(__name__)

_MEASURE_HINTS = ("amount", "total", "revenue", "sales", "price", "cost",
                  "profit", "value", "quantity", "qty", "count", "sum")


@dataclass
class CopilotAnswer:
    """Result of one Copilot turn — the only shape the API/UI needs."""

    ok: bool
    answer: str
    sql: str | None = None
    rows: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    chart: dict | None = None
    error: str | None = None
    tables_used: list[str] = field(default_factory=list)
    retrieved: dict | None = None
    attempts: int = 1
    provider: str | None = None

    def to_public(self, include_rows: int = 50) -> dict:
        """The user-facing payload. Never leaks schema dumps or internals."""
        out = {
            "ok": self.ok,
            "answer": self.answer,
            "sql": self.sql,
            "columns": self.columns,
            "row_count": len(self.rows),
            "data": self.rows[:include_rows],
            "chart": self.chart,
            "tables_used": self.tables_used,
        }
        if self.error:
            out["error"] = self.error
        return out


def _numeric(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("$", "").replace("%", "")
        try:
            float(s)
            return True
        except ValueError:
            return False
    return False


def _datetime_name(name: str) -> bool:
    return bool(re.search(r"(date|time|month|year|period|day|week|quarter)",
                          str(name or ""), re.IGNORECASE))


def infer_chart(columns: list[str], rows: list[dict], question: str) -> dict | None:
    """Infer a chart-ready spec from the RETURNED data + question intent.

    Fully dynamic: no fixed chart mappings, no fixed column names. Ranking
    questions -> bar/horizontal bar; time questions -> line/area; two measures
    -> scatter; share questions -> pie when few categories.
    """
    if not rows or len(columns) < 2:
        return None
    sample = rows[0]
    numeric_cols = [c for c in columns if _numeric(sample.get(c))]
    date_cols = [c for c in columns if _datetime_name(c)]
    cat_cols = [c for c in columns if c not in numeric_cols and c not in date_cols]
    q = (question or "").lower()

    if not numeric_cols:
        return None

    wants_share = any(w in q for w in ("share", "percentage", "percent", "proportion", "pie", "donut"))
    wants_trend = any(w in q for w in ("trend", "over time", "monthly", "yearly", "by month", "by year", "growth"))
    wants_rank = any(w in q for w in ("top", "bottom", "best", "worst", "highest", "lowest", "most", "least", "rank"))

    x = (date_cols or cat_cols or [columns[0]])[0]
    y = numeric_cols[0]

    if date_cols and not wants_rank:
        chart_type = "area" if wants_trend else "line"
        return {"type": chart_type, "x": date_cols[0], "y": y,
                "reason": "time series detected in the returned data"}
    if len(numeric_cols) >= 2 and not cat_cols and not date_cols:
        return {"type": "scatter", "x": numeric_cols[0], "y": numeric_cols[1],
                "reason": "two measures returned — relationship view"}
    if wants_share and cat_cols and 1 < len(rows) <= 8:
        return {"type": "pie", "x": x, "y": y,
                "reason": "share question over few categories"}
    if wants_rank or len(rows) > 8:
        return {"type": "bar_horizontal", "x": x, "y": y,
                "reason": "ranked comparison"}
    return {"type": "bar", "x": x, "y": y, "reason": "category comparison"}


def _summarize_rows(columns: list[str], rows: list[dict]) -> str:
    """Deterministic fallback answer from the returned rows (no LLM needed)."""
    if not rows:
        return "No rows matched that question against the connected data."
    if len(columns) == 1:
        return f"The result is {rows[0].get(columns[0])}."
    numeric_cols = [c for c in columns if _numeric(rows[0].get(c))]
    label_cols = [c for c in columns if c not in numeric_cols]
    if label_cols and numeric_cols:
        label, measure = label_cols[0], numeric_cols[-1]
        top = rows[0]
        return (f"{top.get(label)} has the highest {measure} at {top.get(measure)} "
                f"(across {len(rows)} result rows).")
    first = rows[0]
    return f"Returned {len(rows)} rows; first row: {json.dumps(first, default=str)[:300]}."


class CopilotPipeline:
    """One Copilot, interchangeable LLM backends."""

    def __init__(self, llm, schema_mapping: dict, db_uri: str,
                 dialect: str = "postgresql", user_id="anon",
                 embedder=None, provider_name: str | None = None):
        self.llm = llm
        self.dialect = dialect or "postgresql"
        self.db_uri = db_uri
        self.provider_name = provider_name
        self.memory = ConversationMemory(user_id)
        self.index = build_schema_index(schema_mapping or {}, dialect=self.dialect)
        self.retriever = SchemaRetriever(self.index, embedder=embedder)
        self.sql_engine = SqlEngine(db_uri, dialect=self.dialect)
        self.mapping = schema_mapping or {}

    # -- main entry ------------------------------------------------------

    def ask(self, question: str) -> CopilotAnswer:
        if not question or not question.strip():
            return CopilotAnswer(ok=False, answer="Please ask a question.",
                                 provider=self.provider_name)
        if not self.index.tables:
            return CopilotAnswer(
                ok=False,
                answer=("No database schema is available yet. Connect a PostgreSQL "
                        "or MySQL source (or upload a CSV/PDF) and try again."),
                provider=self.provider_name,
            )

        resolved = self.memory.resolve(question)
        followup_ctx = (self.memory.last() or {}).get("context") if resolved != question else None

        ctx = self.retriever.retrieve(resolved, followup_context=followup_ctx)
        if ctx.is_empty():
            return CopilotAnswer(
                ok=False,
                answer=("I couldn't find tables in the connected schema that relate "
                        "to that question. Try naming a subject, measure or time range."),
                provider=self.provider_name,
            )

        result = self.sql_engine.generate_and_run(
            resolved, ctx, self.llm, tables=self.index.tables, model_role="sql",
        )

        if not result.ok:
            answer = self._explain_failure(result)
            return CopilotAnswer(
                ok=False, answer=answer, sql=result.sql, error=result.error,
                tables_used=ctx.tables, retrieved=ctx.to_state(),
                attempts=result.attempts, provider=self.provider_name,
            )

        rows = _sanitize_rows(result.rows)
        narrative = self._narrate(question, result, rows)
        chart = infer_chart(result.columns, rows, question)

        self.memory.append(
            question=question,
            context=ctx.to_state(),
            answer=narrative,
            sql=result.sql,
        )

        return CopilotAnswer(
            ok=True,
            answer=narrative,
            sql=result.sql,
            rows=rows,
            columns=result.columns,
            chart=chart,
            tables_used=ctx.tables,
            retrieved=ctx.to_state(),
            attempts=result.attempts,
            provider=self.provider_name,
        )

    # -- response generation (provider-independent) ----------------------

    def _narrate(self, question: str, result, rows: list[dict]) -> str:
        fallback = _summarize_rows(result.columns, rows)
        if not rows:
            return "The query ran successfully but returned no rows for that question."
        preview = rows[:8]
        try:
            prompt = (
                "You are ARIA Copilot. Answer the user's business question in 2-4 "
                "concise sentences using ONLY the query result below. Start with the "
                "headline number/answer, then one supporting detail. Do not mention "
                "SQL, tables, columns or schemas.\n\n"
                f"QUESTION: {question}\n"
                f"RESULT COLUMNS: {', '.join(result.columns)}\n"
                f"RESULT ROWS ({len(rows)} total, showing {len(preview)}):\n"
                f"{json.dumps(preview, default=str)[:2000]}\n"
            )
            text = self.llm.complete("story", prompt, temperature=0.2,
                                     num_predict=220, timeout=30)
            text = strip_text(text)
            if text and len(text) >= 8:
                return text
        except Exception as exc:
            log.info("Copilot narration LLM failed (%s); using deterministic answer.", exc)
        return fallback

    def _explain_failure(self, result) -> str:
        err = (result.error or "").lower()
        if "rate limit" in err or "429" in err:
            return ("The language model is rate-limited right now. Please retry in a "
                    "moment or switch the LLM provider in Settings.")
        if "connect" in err or "refused" in err or "timeout" in err or "timed out" in err:
            return ("I couldn't reach the language model backend. Check that Ollama is "
                    "running (Local mode) or that the Groq API key is valid (Cloud mode).")
        if "unknown table" in err or "unknown column" in err:
            return ("The generated query referenced tables/columns that don't exist in "
                    "this schema. Try rephrasing with a clearer subject or measure.")
        if "only read-only" in err:
            return "The generated query was rejected because it was not read-only."
        return ("I couldn't answer that question from the connected data. "
                "Try rephrasing or asking about a specific table, measure or period.")


def strip_text(raw: str) -> str:
    """Light cleanup for free-text LLM output (no code fences)."""
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _sanitize_rows(rows: list[dict]) -> list[dict]:
    """Make rows JSON-safe (datetimes/Decimals -> str/float)."""
    out = []
    for r in rows or []:
        clean = {}
        for k, v in r.items():
            if v is None or isinstance(v, (str, int, float, bool)):
                clean[k] = v
            else:
                clean[k] = str(v)
        out.append(clean)
    return out


def create_pipeline(llm, schema_mapping: dict, db_uri: str, dialect: str = "postgresql",
                    user_id="anon", embedder=None, provider_name: str | None = None) -> CopilotPipeline:
    """Factory used by the API route. The LLM is the existing provider object."""
    return CopilotPipeline(
        llm=llm,
        schema_mapping=schema_mapping,
        db_uri=db_uri,
        dialect=dialect,
        user_id=user_id,
        embedder=embedder,
        provider_name=provider_name or getattr(llm, "provider", None),
    )