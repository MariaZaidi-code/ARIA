"""Data-aware autocomplete routes (pro.docx sections 55-58, 60).

Returns suggestions generated from the actual connected database —
not hardcoded static lists.  Builds a lightweight in-memory ``data_index``
of: table names, metric column names, date column names, categorical
column names, and the most common distinct values for each categorical
column.  Suggestions are then derived by matching the user's partial
input against this index with typo tolerance (difflib SequenceMatcher
ratio), so the user can type ``ali`` and ARIA suggests ``Ali Traders``
if that value is actually present in the data.
"""

import difflib
import json
import re
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from core.config import get_session, save_session
from core.data_intelligence import (
    hint_hit as _hint_hit,
    is_id_like_name as _is_id_like_name,
    name_tokens as _name_tokens,
)
from core.deps import get_current_user, require_writable

router = APIRouter()


class AutocompleteRequest(BaseModel):
    partial: str = ""
    limit: int = 8

# In-memory data_index cache: keyed by absolute schema_path, with file
# mtime as a freshness check.  The index is small (distinct values per
# categorical column, capped), so per-user memory pressure is minimal.
_INDEX_CACHE: dict[str, tuple[float, dict]] = {}
_INDEX_LOCK = threading.RLock()

# Cap how many distinct values we index per column — keeps the index
# bounded for wide cardinalities.  Top-N by frequency is what we store.
_MAX_DISTINCT_PER_COLUMN = 25
# Hard cap on the total cached entries.
_MAX_INDEX_ENTRIES = 100

# Words that signal an analytical intent — used to build template-style
# completions ("Top {cat} by {metric}", etc.) when the user types
# an incomplete phrase like "top" or "top p".  All derived from the
# actual data model — never hardcoded business content.
_INTENT_WORDS = {
    "top": "top",
    "best": "top",
    "highest": "top",
    "worst": "bottom",
    "lowest": "bottom",
    "bottom": "bottom",
    "sum": "sum",
    "total": "total",
    "average": "average",
    "avg": "average",
    "mean": "average",
    "count": "count",
    "how": "count",
    "many": "count",
    "revenue": "revenue",
    "sales": "revenue",
    "income": "revenue",
    "turnover": "revenue",
    "quantity": "quantity",
    "qty": "quantity",
    "units": "quantity",
    "trend": "trend",
    "over": "trend",
    "compare": "compare",
    "vs": "compare",
    "versus": "compare",
    "against": "compare",
    "difference": "compare",
    "by": "group_by",
    "per": "group_by",
}

_NUMERIC_HINT = {"amount", "price", "cost", "revenue", "sales", "total", "sum",
                 "count", "quantity", "qty", "value", "profit", "income",
                 "balance", "pay", "discount", "tax", "fee", "rate",
                 "percent", "number", "num", "stock", "weight", "score"}


# ---------------------------------------------------------------------------
# DB engine construction (mirrors api/kpi_routes._build_engine so the
# autocomplete endpoint handles both relational + SQLite/CSV sources
# consistently).  Duplicated rather than imported to avoid coupling
# unrelated route modules.
# ---------------------------------------------------------------------------
def _build_engine(session):
    db_config = dict(session.get("db") or {})
    if not db_config or session.get("source_type") != "relational":
        sqlite_path = session.get("db_uri") or session.get("csv_db_path")
        if sqlite_path:
            if sqlite_path.startswith("sqlite:///"):
                uri = sqlite_path
            elif sqlite_path.startswith("sqlite://"):
                uri = sqlite_path
            else:
                uri = f"sqlite:///{sqlite_path}"
            return create_engine(uri), "sqlite", "sqlite"
        return None, "unknown", "unknown"
    try:
        from core.secret_box import decrypt as _decrypt_secret
    except Exception:
        _decrypt_secret = None
    if db_config.get("password") and _decrypt_secret:
        try:
            db_config["password"] = _decrypt_secret(db_config["password"])
        except Exception:
            pass
    db_type = session.get("db_type", "postgresql")
    user = quote_plus(str(db_config.get("user", "")))
    password = quote_plus(str(db_config.get("password", "")))
    host = db_config.get("host", "localhost")
    port = db_config.get("port", 5432)
    db = db_config.get("db", "")
    if not db:
        raise HTTPException(status_code=400, detail="No database configured.")
    _cargs: dict = {}
    try:
        from core.db import search_path_connect_args as _spa_a
        _sch_a = [str(s).strip() for s in (session.get("schemas") or [])
                  if str(s or "").strip()]
        _db_schema = db_config.get("db_schema", "")
        if _db_schema:
            for _s in _db_schema.split(","):
                _s = _s.strip()
                if _s and _s not in _sch_a:
                    _sch_a.append(_s)
        _cargs = _spa_a(db_type, _sch_a)
    except Exception:
        _cargs = {}
    if db_type == "mysql":
        from core.db import format_db_host
        uri = (f"mysql+pymysql://{user}:{password}"
               f"@{format_db_host(host)}:{port}/{db}")
    else:
        from core.db import format_db_host
        uri = (f"postgresql://{user}:{password}"
               f"@{format_db_host(host)}:{port}/{db}")
    return create_engine(uri, pool_pre_ping=True,
                         **({"connect_args": _cargs} if _cargs else {})), session.get("dialect", "postgresql"), db_type


def _quote(name, dialect):
    # Dotted keys (sales.employee) quote per segment, never as one name.
    try:
        segs = [s for s in str(name or "").split(".") if s]
        if len(segs) > 1:
            if dialect == "mysql":
                return ".".join(f"`{s.replace('`', '``')}`" for s in segs)
            return ".".join(
                f'"{s.replace(chr(34), chr(34) + chr(34))}"' for s in segs)
    except Exception:
        pass
    if dialect == "mysql":
        return f"`{name.replace('`', '``')}`"
    return f'"{name.replace(chr(34), chr(34)+chr(34))}"'


def _column_iter(table_info):
    raw = table_info.get("columns") or {}
    if isinstance(raw, dict):
        yield from raw.items()
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item.get("column", ""), item
            else:
                yield str(item), {}


def _dtype(col_info) -> str:
    return str(col_info.get("dtype", col_info.get("data_type", "")) or "").lower()


def _words(col_name) -> set:
    """Plain words of a column name, shorthand expanded ('txn_dt' ->
    {'transaction', 'date'}); generic naming conventions only."""
    from schema_engine.lexical import identifier_words
    return set(identifier_words(col_name))


# Calendar parts ('yr', 'month', 'quarter') are time groupings, never
# measures: summing a year column is meaningless.
_PERIOD_WORDS = {"year", "years", "month", "quarter", "week", "weekday",
                 "day", "hour", "period"}
_DATE_WORDS = {"date", "time", "timestamp", "datetime", "created", "updated"}
# Measures whose total is meaningless: ratios, rates and unit prices are
# averaged instead ("average discount percent", never "total discount").
_AVERAGE_WORDS = {"percent", "percentage", "rate", "ratio", "price", "score",
                  "rating", "age", "margin", "avg", "average", "mean"}
_MONEY_WORDS = {"amount", "total", "revenue", "sales", "sale", "price",
                "cost", "value", "profit", "income", "balance", "due",
                "spend", "payment", "fee", "tax", "freight"}
_QUANTITY_WORDS = {"quantity", "units", "unit", "count", "number", "volume"}
_NUMERIC_TYPES = ("int", "float", "decimal", "numeric", "double", "real", "number")
_TEXT_TYPES = ("char", "text", "string", "varchar", "clob")


def _column_role(col_name, col_info, column_class=None):
    """'date' | 'period' | 'metric' | 'category' | None for one column.

    The profiled class / declared type is the truth; name words are only
    used when neither is known. So a TEXT column named 'pay_mthd' is never
    a measure and an INTEGER 'yr' is a period, never a measure.
    """
    if _is_id_like(col_name):
        return None
    words = _words(col_name)
    dt = _dtype(col_info)
    cls = str(column_class or "").lower()
    if cls == "date" or any(t in dt for t in ("date", "time"))             or (words & _DATE_WORDS and not any(t in dt for t in _NUMERIC_TYPES)):
        return "date"
    if words & _PERIOD_WORDS:
        return "period"
    if cls == "numeric" or any(t in dt for t in _NUMERIC_TYPES):
        return "metric"
    if cls in ("categorical", "text") or any(t in dt for t in _TEXT_TYPES):
        return "category"
    if not dt and not cls:
        if _hint_hit(col_name, _NUMERIC_HINT):
            return "metric"
        return "category"
    return None


_HEADLINE_WORDS = {"total", "due", "revenue", "sales", "sale", "turnover"}
_COMPONENT_WORDS = {"sub", "tax", "freight", "shipping", "fee", "cost",
                    "discount", "price", "unit", "line"}


def _metric_rank(words) -> int:
    """Headline money totals first ('total due', 'revenue'), then other
    money amounts, then components (sub total, tax, freight), then
    quantities; averaged measures (rates, prices) last."""
    if words & _AVERAGE_WORDS:
        return 4
    if words & _COMPONENT_WORDS:
        return 2
    if words & _HEADLINE_WORDS:
        return 0
    if words & _MONEY_WORDS:
        return 1
    return 3


def _measure_phrase(m) -> str:
    """'total amount', 'average discount percent', 'total due', 'sub total':
    the aggregate word is added only when the label does not carry it."""
    lab = m["label"]
    word = "average" if m.get("agg") == "average" else "total"
    return lab if word in lab.split() else f"{word} {lab}"


# ---------------------------------------------------------------------------
# Data index construction
# ---------------------------------------------------------------------------
def _index_from_mapping(tables: dict) -> dict:
    """Classify every column of a schema mapping into measures, groupings,
    dates and calendar periods, with plain-English labels. Pure (no DB):
    value sampling is layered on top by _build_data_index."""
    from schema_engine.lexical import humanize_identifier
    metrics: list[dict] = []
    categories: list[dict] = []
    dates: list[dict] = []
    periods: list[dict] = []
    table_names: list[str] = []

    for tname, tinfo in tables.items():
        table_names.append(tname)
        classes = tinfo.get("column_classes") or {}
        stats = tinfo.get("null_stats") or {}
        rows_total = int(tinfo.get("row_count") or 0)
        for col_name, col_info in _column_iter(tinfo):
            if not col_name:
                continue
            role = _column_role(col_name, col_info or {}, classes.get(col_name))
            if role is None:
                continue
            words = _words(col_name)
            entry = {"table": tname, "column": col_name, "name": col_name,
                     "label": humanize_identifier(col_name)}
            if role == "date":
                dates.append(entry)
            elif role == "period":
                periods.append(entry)
            elif role == "metric":
                entry["agg"] = "average" if words & _AVERAGE_WORDS else "total"
                entry["rank"] = _metric_rank(words)
                metrics.append(entry)
            else:
                distinct = int((stats.get(col_name) or {}).get("distinct_count") or 0)
                entry["distinct"] = distinct
                # Near-unique text (names, free text, row keys) is searchable
                # by value but is never a useful breakdown.
                entry["groupable"] = not distinct or (
                    distinct <= 50 and (not rows_total or distinct < rows_total))
                categories.append(entry)
    metrics.sort(key=lambda m: m["rank"])
    categories.sort(key=lambda c: (not c["groupable"], c.get("distinct") or 999))
    return {"tables": table_names, "metrics": metrics, "categories": categories,
            "dates": dates, "periods": periods}


def _build_data_index(session, schema_path: Path):
    """Read schema mapping + sample distinct values to build a small
    in-memory index describing the actual database.  Cached per
    schema_path + mtime to avoid re-querying the database on every
    keystroke.  Returns a dict suitable for matching against partial
    user input."""
    if not schema_path.exists():
        return {"tables": [], "metrics": [], "categories": [],
                "dates": [], "values": [], "ready": False}

    try:
        mapping = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:
        return {"tables": [], "metrics": [], "categories": [],
                "dates": [], "values": [], "ready": False}

    tables = mapping.get("tables", {})
    if not tables:
        return {"tables": [], "metrics": [], "categories": [],
                "dates": [], "values": [], "ready": False}

    engine, dialect, _ = _build_engine(session)
    if engine is None:
        return {"tables": [], "metrics": [], "categories": [],
                "dates": [], "values": [], "ready": False}

    structure = _index_from_mapping(tables)
    metrics, categories = structure["metrics"], structure["categories"]
    dates, periods, table_names = structure["dates"], structure["periods"], structure["tables"]
    cat_cols = [(c["table"], c["column"]) for c in categories]

    # Sample distinct values from categorical columns — this is the
    # "actual data" feed that makes autocomplete data-aware (section 56).
    distinct_values: list[dict] = []
    if not cat_cols:
        engine.dispose()
    else:
        try:
            with engine.connect() as conn:
                # Cap total samples to keep the index small.
                for tname, col_name in cat_cols[:20]:
                    q = (f"SELECT {_quote(col_name, dialect)} AS v, "
                         f"COUNT(*) AS c FROM {_quote(tname, dialect)} "
                         f"WHERE {_quote(col_name, dialect)} IS NOT NULL "
                         f"GROUP BY {_quote(col_name, dialect)} "
                         f"ORDER BY c DESC LIMIT {_MAX_DISTINCT_PER_COLUMN}")
                    try:
                        rows = conn.execute(text(q)).fetchall()
                    except Exception:
                        continue
                    for r in rows:
                        v = r[0]
                        if v is None:
                            continue
                        s = str(v).strip()
                        if not s:
                            continue
                        distinct_values.append({
                            "value": s,
                            "table": tname,
                            "column": col_name,
                            "count": int(r[1] or 0),
                        })
        except Exception:
            pass
        finally:
            try:
                engine.dispose()
            except Exception:
                pass

    return {
        "tables": table_names,
        "metrics": metrics,
        "categories": categories,
        "dates": dates,
        "periods": periods,
        "values": distinct_values,
        "ready": True,
    }


def _get_data_index(session, user_id=None):
    """Return cached data_index for the session's schema, rebuilding if
    the schema file mtime changed."""
    schema_path: Path = session.get("schema_path")
    if not schema_path or not isinstance(schema_path, Path):
        try:
            schema_path = Path(str(schema_path)) if schema_path else None
        except Exception:
            schema_path = None
    if not schema_path:        return {"tables": [], "metrics": [], "categories": [],
                "dates": [], "values": [], "ready": False}

    try:
        mtime = schema_path.stat().st_mtime if schema_path.exists() else 0.0
    except Exception:
        mtime = 0.0
    # Key includes the user: two users must never share an index even if
    # paths ever collide (linked/shared DBs, tmp paths in tests).
    try:
        _uid = int(str(user_id)) if user_id is not None else 0
    except (TypeError, ValueError):
        _uid = 0
    key = (_uid, str(schema_path))
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached and cached[0] == mtime:
            # LRU touch: reinsert so eviction drops least-recently-used.
            _INDEX_CACHE.pop(key, None)
            _INDEX_CACHE[key] = cached
            return cached[1]
        # Evict least-recently-used if at capacity
        if len(_INDEX_CACHE) >= _MAX_INDEX_ENTRIES and key not in _INDEX_CACHE:
            _INDEX_CACHE.pop(next(iter(_INDEX_CACHE)))
        idx = _build_data_index(session, schema_path)
        _INDEX_CACHE[key] = (mtime, idx)
        return idx


# ---------------------------------------------------------------------------
# Suggestion ranking
# ---------------------------------------------------------------------------
def _normalize(text):
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fuzzy_ratio(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def _match_quality(query, candidate):
    """Match quality tier: 3 = prefix, 2 = substring, 1 = fuzzy, 0 = none.

    Prefix matches carry the strongest signal (typing "sal" almost surely
    means the Sales column, not a fuzzy value hit), so ranking scores
    follow the tier instead of rating every hit equally.
    """
    if not query:
        return 0
    q = query.lower()
    c = candidate.lower()
    if c.startswith(q) or any(w.startswith(q) for w in c.split()):
        return 3
    if q in c:
        return 2
    # Fuzzy: allow genuine typos (section 59).  The bar sits well above
    # coincidental 3-letter overlaps ("what" must not match "Art") while
    # real typos ("salse" -> "sales") still clear it.  Comparison is
    # two-sided so it stays fair regardless of string length.
    if len(q) >= 3:
        # Cap the comparison window to the longer of |query| and |candidate|
        window = c[:max(len(q), len(c))]
        if _fuzzy_ratio(q, window) >= 0.65:
            return 1
    return 0


def _partial_match(query, candidate):
    """True if ``query`` is a prefix or fuzzy substring of ``candidate``."""
    if not query:
        return True
    return _match_quality(query, candidate) > 0


def _is_id_like(name: str) -> bool:
    # Separator-agnostic (shared helper): "order_id", "Order ID" and
    # "postal_code" are identifiers; "country" is not.
    return bool(_is_id_like_name(name))


# Words that carry no meaning on their own when matching typed text.
_FILLER = {"the", "a", "an", "is", "are", "of", "in", "on", "for", "to",
           "what", "which", "show", "me", "how", "has", "have", "my",
           "our", "was", "were", "do", "does", "give", "tell", "list", "and"}


def _question_pool(index):
    """Full plain-English questions this schema can actually answer.

    Built only from the connected data's own measures, groupings and dates
    (labels humanized: 'txn_dt' -> 'transaction date'). Ordered so the
    first items cover the most important measure, then the next, so the
    list stays varied. Every entry: (text, kind, metric_label or None).
    """
    from schema_engine.lexical import pluralize
    mets = index.get("metrics", [])[:4]
    cats = [c for c in index.get("categories", []) if c.get("groupable", True)][:6]
    dates = index.get("dates", [])[:1]
    periods = index.get("periods", [])[:2]

    measure = _measure_phrase

    def plural_phrase(label):
        head, _sep, last = label.rpartition(" ")
        return f"{head} {pluralize(last)}" if head else pluralize(last)

    tiers: list[list[tuple[str, str, str | None]]] = []
    for m in mets:
        mm = measure(m)
        t = [(f"What is the {mm}?", "template", m["label"])]
        for c in cats:
            t.append((f"What is the {mm} by {c['label']}?", "template", m["label"]))
            t.append((f"Which {c['label']} has the highest {mm}?", "template", m["label"]))
        if dates:
            t.append((f"How has {mm} changed over time?", "template", m["label"]))
        for pd in periods:
            t.append((f"What is the {mm} by {pd['label']}?", "template", m["label"]))
        for c in cats:
            t.append((f"Top 10 {plural_phrase(c['label'])} by {mm}", "template", m["label"]))
        if m.get("agg") != "average":
            t.append((f"What is the average {m['label']}?", "template", m["label"]))
        tiers.append(t)
    general = [("How many records are there?", "template", None)]
    for c in cats:
        general.append((f"Which {c['label']} has the most records?", "template", None))
        general.append((f"How many records are there per {c['label']}?", "template", None))
    tiers.append(general)
    # Round-robin across measures so one measure never fills the list.
    pool, i = [], 0
    while any(i < len(t) for t in tiers):
        for t in tiers:
            if i < len(t):
                pool.append(t[i])
        i += 1
    return pool


def answerable_questions(session, user_id=None, focus=None) -> list[str]:
    """Plain-English questions the connected data can answer, best first.

    Shared by every suggestion surface (starter chips, follow-ups, the
    assistant) so they all speak the same humanized, dimension-aware
    language. `focus` (a measure label such as 'amount') moves questions
    about that measure to the front. Never raises: returns [] when the
    index is unavailable.
    """
    try:
        index = _get_data_index(session, user_id)
        if not index.get("ready"):
            return []
        pool = [t for t, _k, _m in _question_pool(index)]
    except Exception:
        return []
    if focus:
        f = str(focus).lower()
        pool = [q for q in pool if f in q.lower()] + [q for q in pool if f not in q.lower()]
    return [q[:1].upper() + q[1:] for q in pool]


def _expand_tokens(tokens):
    from schema_engine.lexical import expand_abbreviation
    out = []
    for t in tokens:
        out.extend(expand_abbreviation(t).split())
    return out


def _continuation_score(partial_n, cand):
    """How well `cand` continues what the user typed (0 = not at all).

    1.0  the question starts with the typed text ('what is' ->
         'What is the total amount?'), shorthand expanded ('total amt').
    0.85 every typed word appears in the question, the last one possibly
         half-typed ('amount sto' -> '... by store code').
    0.6  the same, allowing small typos ('amout').
    """
    cand_n = _normalize(cand)
    p_tokens = partial_n.split()
    if not p_tokens:
        return 0.0
    expanded = " ".join(_expand_tokens(p_tokens))
    if cand_n.startswith(partial_n) or cand_n.startswith(expanded):
        return 1.0
    c_tokens = cand_n.split()
    content = [t for t in _expand_tokens(p_tokens) if t not in _FILLER] or _expand_tokens(p_tokens)
    head, last = content[:-1], content[-1]
    if all(t in c_tokens for t in head) and any(c.startswith(last) for c in c_tokens):
        return 0.85
    def near(t):
        return any(c.startswith(t) or (len(t) >= 4 and _fuzzy_ratio(t, c) >= 0.8)
                   for c in c_tokens)
    if all(near(t) for t in content):
        return 0.6
    return 0.0


def _rank_suggestions(index, partial, limit):
    """Ranked suggestion dicts for the typed text.

    Each suggestion: {"text": "<full question>", "kind": "template"|"value",
    "score": float in [0, 1]}. Suggestions continue what the user typed and
    are built only from the connected data (its measures, groupings and
    real values) - never static strings, never raw column names, never a
    total of a year, a text column or a percentage.
    """
    partial_n = _normalize(partial)
    if len(partial_n) < 1:
        return []

    scored: list[tuple[float, int, dict]] = []
    seen: set[str] = set()

    def _add(text, kind, score):
        key = text.lower().strip()
        if not key or key in seen or score <= 0:
            return
        seen.add(key)
        scored.append((score, len(scored), {"text": text, "kind": kind,
                                            "score": round(score, 3)}))

    # 1) Whole questions that continue the typed text.
    for text_, kind, _m in _question_pool(index):
        _add(text_, kind, _continuation_score(partial_n, text_))

    # 2) Real values from the data: typing 'card' offers 'Card' answers.
    #    Only the last typed word is matched, so a value never hijacks a
    #    question the user is clearly writing.
    last = partial_n.split()[-1]
    if len(last) >= 2 and last not in _FILLER:
        mets = index.get("metrics", [])
        lead = _measure_phrase(mets[0]) if mets else None
        labels = {(c["table"], c["column"]): c.get("label", "")
                  for c in index.get("categories", [])}
        hits = 0
        for v in index.get("values", []):
            if hits >= 3:
                break
            q = _match_quality(last, v["value"])
            if q < 2:
                continue
            hits += 1
            # Below whole-question continuations (0.85+): a value only leads
            # when nothing in the schema continues the typed words.
            score = 0.8 if q >= 3 else 0.62
            col_label = labels.get((v.get("table"), v.get("column")), "")
            subject = f"{col_label} {v['value']}".strip()
            if lead:
                _add(f"What is the {lead} for {subject}?", "value", score)
            _add(f"How many records have {subject}?", "value", score - 0.05)

    scored.sort(key=lambda t: (-t[0], t[1]))
    out = [d for _s, _i, d in scored[:limit]]
    for d in out:
        d["text"] = d["text"][:1].upper() + d["text"][1:]
    return out


# ---------------------------------------------------------------------------
# Follow-up context (section 61)
# ---------------------------------------------------------------------------
def _store_conversation(user_id, session, question, answer_summary):
    """Persist the last Q/A pair on the session so follow-ups can resolve
    context.  Uses save_session to flush to disk for cross-process
    consistency."""
    conv = session.get("conversation") or []
    conv.append({
        "question": question,
        "summary": answer_summary,
        "ts": time.time(),
    })
    # Keep only the last 5 turns to bound the payload.
    session["conversation"] = conv[-5:]
    save_session(user_id, session)


def _build_followup_goal(session, raw_question):
    """If ``raw_question`` looks like a follow-up (no clear entity),
    prepend the previous question's context so the goal agent has
    something to anchor to.  This implements section 61."""
    conv = session.get("conversation") or []
    if not conv:
        return raw_question
    last = conv[-1]
    prev_q = (last.get("question") or "").strip()
    if not prev_q:
        return raw_question
    # Heuristic: very short questions, or questions that start with
    # follow-up words, get the previous question prepended.
    followup_signals = (
        "how much", "what about", "only for", "in 20", "compare with",
        "compare to", "vs ", "and ", "also", "now", "then", "next",
        "why", "show me", "give me", "more", "less", "filter",
    )
    q_lower = raw_question.lower().strip()
    if len(q_lower.split()) <= 6 or any(q_lower.startswith(s) for s in followup_signals):
        return f"Previous question: {prev_q}\nFollow-up: {raw_question}"
    return raw_question


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/api/autocomplete")
def autocomplete_get(
    partial: str = "",
    limit: int = 8,
    user: dict = Depends(get_current_user),
):
    """GET autocomplete — for simple browser fetch with query params."""
    return _autocomplete(partial, limit, user)


@router.post("/api/autocomplete")
def autocomplete_post(
    body: AutocompleteRequest,
    user: dict = Depends(get_current_user),
):
    """POST autocomplete — accepts JSON body."""
    return _autocomplete(body.partial, body.limit, user)


def _autocomplete(partial: str, limit: int, user: dict):
    partial = (partial or "").strip()
    limit = max(1, min(int(limit or 8), 20))

    session = get_session(user["user_id"])

    # Even when not connected, the call should not 500 — return an
    # empty list so the frontend can keep working.
    if not session.get("db") and session.get("source_type") != "semi-structured":
        return {"ok": True, "suggestions": [], "ready": False,
                "index_summary": {"tables": 0, "values": 0}}

    if not session.get("schema_path") or not Path(str(session["schema_path"])).exists():
        return {"ok": True, "suggestions": [], "ready": False,
                "index_summary": {"tables": 0, "values": 0}}

    index = _get_data_index(session, user["user_id"])
    suggestions = _rank_suggestions(index, partial, limit)

    return {
        "ok": True,
        "ready": bool(index.get("ready")),
        "suggestions": suggestions,
        "index_summary": {
            "tables": len(index.get("tables", [])),
            "metrics": len(index.get("metrics", [])),
            "categories": len(index.get("categories", [])),
            "dates": len(index.get("dates", [])),
            "values": len(index.get("values", [])),
        },
    }


@router.post("/api/conversation/store")
def store_conversation(request: Request, payload: dict,
                       user: dict = Depends(require_writable)):
    """Persist a Q/A pair as the most recent conversation turn.

    Intended for API clients after rendering an answer so follow-ups can
    resolve against this context (section 61). Note: the web UI does not
    call this - /api/ask keeps its own conversation_history instead.  The endpoint is intentionally lightweight — it only
    stores what the UI tells it, and the goal agent re-derives the
    answer from the database when the follow-up is asked.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body required")
    question = (payload.get("question") or "").strip()
    summary = (payload.get("summary") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    session = get_session(user["user_id"])
    _store_conversation(user["user_id"], session, question, summary)
    return {"ok": True, "turns": len(session.get("conversation") or [])}


@router.post("/api/conversation/resolve_followup")
def resolve_followup(request: Request, payload: dict,
                     user: dict = Depends(get_current_user)):
    """Given a possibly-incomplete follow-up, return the resolved goal
    text.  Returns the original question unchanged if there is no
    prior conversation, or prepends ``Previous question:`` so the goal
    agent can see the context."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body required")
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    session = get_session(user["user_id"])
    resolved = _build_followup_goal(session, question)
    return {
        "ok": True,
        "original": question,
        "resolved": resolved,
        "has_context": resolved != question,
    }
