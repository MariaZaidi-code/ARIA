"""Hypothesis testing routes: statistical tests against connected data."""

import re
import math
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import numpy as np

from core.config import get_session
from core.deps import require_data, require_writable, get_current_user, reject_document_sql
from core.secret_box import decrypt as _decrypt_secret

router = APIRouter()


def _quote_identifier(name, dialect="postgresql"):
    if dialect == "mysql":
        return f"`{name.replace('`', '``')}`"
    return f'"{name.replace(chr(34), chr(34)+chr(34))}"'


class HypothesisRequest(BaseModel):
    hypothesis: str
    dataset: str = "Sales Database"


class InvestigateRequest(BaseModel):
    question: str


def _session_documents(user_id) -> list[dict]:
    """Chunk texts for the session's connected document (best-effort)."""
    try:
        session = get_session(user_id)
        doc_id = session.get("document_id")
        if not doc_id:
            return []
        from insight_rag.storage import RAGMetadataStore
        store = RAGMetadataStore(user_id)
        meta = store.get_document(doc_id) or {}
        chunks = store.load_chunks(doc_id)
        fname = str(meta.get("filename") or meta.get("original_filename") or doc_id)
        out = []
        for ch in chunks[:40]:
            text = getattr(ch, "page_content", "") or ""
            if text.strip():
                out.append({"filename": fname,
                            "page": (getattr(ch, "metadata", {}) or {}).get("page"),
                            "text": text})
        return out
    except Exception:
        return []


def _linked_hypothesis_setup(session):
    """Build investigation context from a stashed linked database (§7).

    Returns (setup_tuple, None) or (None, err_dict). Never raises.
    """
    try:
        from api.copilot_routes import _linked_context
        from api.schema_intel import SchemaIntelligence
        linked = _linked_context(session)
        mapping = linked.get("mapping") or {}
        tables = list(mapping.get("tables", {}).keys())
        if not linked.get("db_uri") or not tables:
            return None, {"ok": False, "code": "NO_CONNECTION",
                          "detail": "No queryable data is connected yet."}
        engine = create_engine(linked["db_uri"], pool_pre_ping=True)
        return (mapping, tables, engine, linked.get("dialect", "postgresql"),
                SchemaIntelligence(mapping)), None
    except Exception as exc:
        return None, {"ok": False, "code": "INVALID_SOURCE",
                      "detail": f"The linked data could not be read: {str(exc)[:150]}"}


@router.post("/api/hypotheses/investigate")
def investigate_hypotheses(req: InvestigateRequest, request: Request,
                           user: dict = Depends(require_writable)):
    """Evidence-based investigation workspace (t.txt): observe -> break down
    -> anomalies -> document evidence -> ranked candidate hypotheses."""
    from hypothesis_engine.investigate import investigate_question
    from insight_agent import sanitize_json
    require_data(request)
    session = get_session(user["user_id"])
    try:
        setup, err = _hypothesis_setup(user)
    except Exception:
        # Document-primary sessions raise inside the shared setup;
        # fall through to the linked-database path below.
        setup, err = None, {"rejected": True}
    if err:
        # Multi-source (§7): a document-primary session may still carry a
        # linked database — investigate that instead of refusing outright.
        setup, err = _linked_hypothesis_setup(session)
    if err:
        if "rejected" in err:
            raise HTTPException(status_code=400, detail=(
                "This source is a text document — use Document Chat (Copilot) "
                "instead of SQL analytics."))
        return {"ok": False, **err}
    mapping, tables, engine, dialect, intel = setup
    try:
        llm = session.get("provider")
        if not isinstance(llm, str) and llm is not None and not hasattr(llm, "complete"):
            llm = None
        out = investigate_question(engine, dialect, intel, tables, req.question,
                                   documents=_session_documents(user["user_id"]),
                                   llm=llm)
        return sanitize_json({"ok": True, **out})
    except Exception as exc:
        return {"ok": False, "code": "ANALYSIS_FAILED",
                "detail": f"The investigation could not run: {str(exc)[:200]}"}
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


@router.get("/api/hypotheses/auto")
def auto_hypotheses(request: Request, user: dict = Depends(get_current_user)):
    """Automatic detection (t.txt §§13, 28): scan data, investigate the top
    event — no question required. Results cached briefly per schema."""
    import time as _time
    from hypothesis_engine.investigate import auto_investigate
    from insight_agent import sanitize_json
    session = get_session(user["user_id"])
    try:
        setup, err = _hypothesis_setup(user)
    except Exception:
        setup, err = None, {"rejected": True}
    if err:
        setup, err = _linked_hypothesis_setup(session)
    if err:
        return {"ok": True, "events": [], "insufficient": True,
                "detail": ("Connect a database or upload a file and ARIA will "
                           "scan it for changes worth investigating."),
                "needed_data": []}
    mapping, tables, engine, dialect, intel = setup
    try:
        llm = session.get("provider")
        if not isinstance(llm, str) and llm is not None and not hasattr(llm, "complete"):
            llm = None
        out = auto_investigate(engine, dialect, intel, tables,
                               documents=_session_documents(user["user_id"]),
                               llm=llm)
        try:
            out["analyzed_at"] = _time.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
        return sanitize_json({"ok": True, **out})
    except Exception as exc:
        return {"ok": False, "code": "ANALYSIS_FAILED",
                "detail": f"Automatic detection could not run: {str(exc)[:200]}"}
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


class AnalyzeRequest(BaseModel):
    question: str
    table: str | None = None
    metric: str | None = None
    driver: str | None = None


class ParseRequest(BaseModel):
    question: str
    metric: str | None = None
    driver: str | None = None


def _engine_for_session(session):
    """Build a bounded engine for any supported source (shared abstraction)."""
    db_type = session.get("db_type", "postgresql")
    if db_type in ("sqlite", "document"):
        engine_url = session.get("db_uri")
        if not engine_url:
            return None, "No queryable database file for this source."
        return create_engine(engine_url, pool_pre_ping=True), "sqlite"
    db_config = session.get("db") or {}
    driver = "mysql" if db_type == "mysql" else "postgresql"
    dialect = "mysql" if driver == "mysql" else "postgresql"
    host = db_config.get("host", "localhost")
    port = db_config.get("port", 5432)
    db = db_config.get("database", db_config.get("db", ""))
    user_name = db_config.get("user", db_config.get("username", ""))
    password = db_config.get("password", "")
    if password:
        try:
            password = _decrypt_secret(password)
        except Exception:
            pass
    if driver == "mysql":
        engine_url = f"mysql+pymysql://{quote_plus(str(user_name))}:{quote_plus(str(password))}@{host}:{port}/{db}"
    else:
        engine_url = f"postgresql+psycopg2://{quote_plus(str(user_name))}:{quote_plus(str(password))}@{host}:{port}/{db}"
    return create_engine(engine_url, pool_pre_ping=True,
                         connect_args={"connect_timeout": 10}), dialect


@router.get("/api/hypothesis/suggest")
def suggest_hypotheses(user: dict = Depends(get_current_user)):
    """Top data-backed hypothesis suggestions, ranked by measured effect.

    Each card carries its evidence (computed live, pre-validated), so every
    suggestion is guaranteed testable — never a dead end.
    """
    from api.schema_intel import SchemaIntelligence
    from hypothesis_engine.engine import rank_prominent, suggest_hypotheses as _suggest
    session = get_session(user["user_id"])
    reject_document_sql(session)
    schema_path = session.get("schema_path")
    if not schema_path:
        return {"ok": True, "suggestions": [], "cards": []}
    try:
        from pathlib import Path as _P
        import json as _j
        mapping = _j.loads(_P(str(schema_path)).read_text(encoding="utf-8"))
    except Exception:
        return {"ok": True, "suggestions": [], "cards": []}
    tables = list(mapping.get("tables", {}).keys())
    if not tables:
        return {"ok": True, "suggestions": [], "cards": []}
    engine, dialect = _engine_for_session(session)
    if engine is None:
        return {"ok": True, "suggestions": [], "cards": []}
    try:
        intel = SchemaIntelligence(mapping)
        try:
            cards = rank_prominent(engine, dialect, intel, tables, limit=5)
        except Exception:
            cards = []
        texts = [c["text"] for c in cards] or _suggest(engine, dialect, intel, tables)
        return {"ok": True, "suggestions": texts, "cards": cards}
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


@router.post("/api/hypothesis/analyze")
def analyze_hypothesis(req: AnalyzeRequest, request: Request, user: dict = Depends(require_writable)):
    """Full Hypothesis Engine pipeline: intent -> adequacy -> analysis -> verdict."""
    from api.schema_intel import SchemaIntelligence
    from hypothesis_engine import analyze_question
    from insight_agent import sanitize_json
    require_data(request)
    session = get_session(user["user_id"])
    reject_document_sql(session)
    schema_path = session.get("schema_path")
    if not schema_path:
        return {"ok": False, "verdict": "NEEDS MORE DATA", "code": "NO_CONNECTION",
                "detail": "No data source is connected yet."}
    try:
        from pathlib import Path as _P
        import json as _j
        mapping = _j.loads(_P(str(schema_path)).read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "verdict": "NEEDS MORE DATA", "code": "INVALID_SOURCE",
                "detail": "The schema description could not be read. Reconnect first."}
    tables = list(mapping.get("tables", {}).keys())
    if not tables:
        return {"ok": False, "verdict": "NEEDS MORE DATA", "code": "INVALID_SOURCE",
                "detail": "The connected source has no tables to analyze."}
    engine, dialect = _engine_for_session(session)
    if engine is None:
        return {"ok": False, "verdict": "NEEDS MORE DATA", "code": "NO_CONNECTION",
                "detail": dialect}
    try:
        out = analyze_question(engine, dialect, SchemaIntelligence(mapping), tables,
                               req.question, table_hint=req.table,
                               metric_override=req.metric, driver_override=req.driver)
        return sanitize_json(out)
    except Exception as exc:
        return {"ok": False, "verdict": "NEEDS MORE DATA", "code": "ANALYSIS_FAILED",
                "detail": f"The analysis could not run: {str(exc)[:200]}"}
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


def _hypothesis_setup(user):
    """Shared loader: mapping + tables + engine for any supported source."""
    from api.schema_intel import SchemaIntelligence
    session = get_session(user["user_id"])
    reject_document_sql(session)
    schema_path = session.get("schema_path")
    if not schema_path:
        return None, {"ok": False, "code": "NO_CONNECTION",
                      "detail": "No data source is connected yet."}
    try:
        from pathlib import Path as _P
        import json as _j
        mapping = _j.loads(_P(str(schema_path)).read_text(encoding="utf-8"))
    except Exception:
        return None, {"ok": False, "code": "INVALID_SOURCE",
                      "detail": "The schema description could not be read. Reconnect first."}
    tables = list(mapping.get("tables", {}).keys())
    if not tables:
        return None, {"ok": False, "code": "INVALID_SOURCE",
                      "detail": "The connected source has no tables to analyze."}
    engine, dialect = _engine_for_session(session)
    if engine is None:
        return None, {"ok": False, "code": "NO_CONNECTION", "detail": dialect}
    return (mapping, tables, engine, dialect, SchemaIntelligence(mapping)), None


@router.get("/api/hypotheses/context")
def hypothesis_context(user: dict = Depends(get_current_user)):
    """Dynamic hypothesis context: metrics, drivers, dimensions, dates, ranges."""
    from hypothesis_engine import data_context
    from insight_agent import sanitize_json
    setup, err = _hypothesis_setup(user)
    if err:
        return {"ok": False, **err}
    mapping, tables, engine, dialect, intel = setup
    try:
        return sanitize_json({"ok": True, **data_context(engine, dialect, intel, tables)})
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


@router.post("/api/hypotheses/parse")
def hypothesis_parse(req: ParseRequest, user: dict = Depends(get_current_user)):
    """Preview a hypothesis before running statistics (never executes analysis)."""
    from hypothesis_engine import preview_question
    from insight_agent import sanitize_json
    setup, err = _hypothesis_setup(user)
    if err:
        return {"ok": False, **err}
    mapping, tables, engine, dialect, intel = setup
    try:
        return sanitize_json(preview_question(engine, dialect, intel, tables,
                                              req.question, metric_hint=req.metric,
                                              driver_hint=req.driver))
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


@router.post("/api/hypothesis")
def run_hypothesis(req: HypothesisRequest, request: Request, user: dict = Depends(require_writable)):
    require_data(request)
    session = get_session(user["user_id"])
    reject_document_sql(session)
    if not session or not session.get("db"):
        return {"ok": False, "detail": "No data source connected"}

    db_config = session["db"]
    db_type = session.get("db_type", "postgresql")

    if db_type in ("sqlite", "document"):
        # CSV-backed SQLite sources: test against the generated .db file.
        # Honest gating stays: <10 points or no numeric pairs -> clear detail.
        engine_url = session.get("db_uri")
        if not engine_url:
            return {"ok": False, "detail": "No queryable database file for this source."}
        dialect = "sqlite"
        try:
            engine = create_engine(engine_url, pool_pre_ping=True)
            return _run_test(engine, dialect, req)
        except Exception as exc:
            return {"ok": False, "detail": f"Hypothesis test failed: {str(exc)[:200]}"}
        finally:
            try:
                engine.dispose()
            except Exception:
                pass

    driver = "mysql" if db_type == "mysql" else "postgresql"
    dialect = "mysql" if driver == "mysql" else "postgresql"

    try:
        # Build engine URL from session db config
        host = db_config.get("host", "localhost") if isinstance(db_config, dict) else db_config.host if hasattr(db_config, "host") else "localhost"
        port = db_config.get("port", 5432) if isinstance(db_config, dict) else (db_config.port if hasattr(db_config, "port") else 5432)
        db = db_config.get("database", db_config.get("db", "")) if isinstance(db_config, dict) else (db_config.database if hasattr(db_config, "database") else db_config.db if hasattr(db_config, "db") else "")
        user_name = db_config.get("user", db_config.get("username", "")) if isinstance(db_config, dict) else (db_config.user if hasattr(db_config, "user") else "")
        password = db_config.get("password", "") if isinstance(db_config, dict) else (db_config.password if hasattr(db_config, "password") else "")
        if password:
            try:
                password = _decrypt_secret(password)
            except Exception:
                pass
        if driver == "mysql":
            engine_url = f"mysql+pymysql://{quote_plus(str(user_name))}:{quote_plus(str(password))}@{host}:{port}/{db}"
        else:
            engine_url = f"postgresql+psycopg2://{quote_plus(str(user_name))}:{quote_plus(str(password))}@{host}:{port}/{db}"

        engine = create_engine(engine_url, pool_pre_ping=True,
                               connect_args={"connect_timeout": 10})

        try:
            return _run_test(engine, dialect, req)
        finally:
            try:
                engine.dispose()
            except Exception:
                pass

    except Exception as e:
        return {"ok": False, "detail": f"Hypothesis test failed: {str(e)}"}


def _run_test(engine, dialect, req):
    """Shared test body for PG/MySQL/SQLite (honest gating, no fabricated stats)."""
    try:
        with engine.connect() as conn:
            tables = _get_tables(conn, dialect)
            if not tables:
                return {"ok": False, "detail": "No tables found in the connected database"}

            numeric_pairs = _find_numeric_pairs(conn, tables, dialect)
            if not numeric_pairs:
                return {"ok": False, "detail": "No numeric column pairs found suitable for hypothesis testing"}

            best_pair = _select_best_pair(numeric_pairs, req.hypothesis, conn, dialect)
            x_col, y_col, table_name = best_pair

            sample = _fetch_sample(conn, table_name, x_col, y_col, dialect)
            if len(sample) < 10:
                return {"ok": False, "detail": "Insufficient data points for statistical testing (need at least 10)"}

            x_vals = np.array([float(r[0]) for r in sample if r[0] is not None and r[1] is not None])
            y_vals = np.array([float(r[1]) for r in sample if r[0] is not None and r[1] is not None])

            if len(x_vals) < 10:
                return {"ok": False, "detail": "Insufficient non-null data points for testing"}

            stats = _compute_correlation(x_vals, y_vals)

            scatter_data = [
                {"x": round(float(x_vals[i]), 2), "y": round(float(y_vals[i]), 2)}
                for i in range(min(200, len(x_vals)))
            ]

            supported = stats["p_value"] < 0.05 and abs(stats["r"]) > 0.3
            interpretation = _build_interpretation(req.hypothesis, stats, supported, x_col, y_col)

            # Context: same test for a few more candidate pairs so the UI can
            # show a comparison view. All real computation, same gating.
            comparisons = [{
                "x": x_col, "y": y_col, "table": table_name,
                "r": stats["r"], "p_value": stats["p_value"],
                "n": len(x_vals), **_r_ci(stats["r"], len(x_vals)),
            }]
            seen_pairs = {(x_col, y_col, table_name)}
            for px, py, pt in numeric_pairs:
                if len(comparisons) >= 5:
                    break
                if (px, py, pt) in seen_pairs:
                    continue
                seen_pairs.add((px, py, pt))
                try:
                    s2 = _fetch_sample(conn, pt, px, py, dialect)
                    xa = np.array([float(r[0]) for r in s2 if r[0] is not None and r[1] is not None])
                    ya = np.array([float(r[1]) for r in s2 if r[0] is not None and r[1] is not None])
                    if len(xa) < 10:
                        continue
                    st2 = _compute_correlation(xa, ya)
                    comparisons.append({
                        "x": px, "y": py, "table": pt,
                        "r": st2["r"], "p_value": st2["p_value"],
                        "n": len(xa), **_r_ci(st2["r"], len(xa)),
                    })
                except Exception:
                    continue
            comparisons.sort(key=lambda c: abs(c["r"]), reverse=True)

            return {
                "ok": True,
                "supported": supported,
                "interpretation": interpretation,
                "stats": {
                    "Compared": f"{_plain_col(x_col)} vs {_plain_col(y_col)}",
                    "Records studied": f"{len(x_vals):,} records",
                    "Link found": ("Strong link" if abs(stats['r']) > 0.7
                                   else "Moderate link" if abs(stats['r']) > 0.4
                                   else "Weak or no link"),
                    "Direction": ("Move together" if stats['r'] > 0 else "Move apart"),
                    "Confidence": _confidence_word(stats['p_value']),
                },
                "data_quality": {
                    "records": len(x_vals),
                    "required": 10,
                    "pair_valid": True,
                    "variance_ok": bool(np.std(x_vals, ddof=1) > 0 and np.std(y_vals, ddof=1) > 0),
                    "method": stats.get("method", "Pearson Correlation"),
                },
                "comparisons": comparisons,
                "scatter_data": scatter_data,
                "x_label": x_col,
                "y_label": y_col,
            }
    except Exception as e:
        return {"ok": False, "detail": f"Hypothesis test failed: {str(e)}"}


def _get_tables(conn, dialect):
    if dialect == "mysql":
        result = conn.execute(text("SHOW TABLES"))
    elif dialect == "sqlite":
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ))
    else:
        result = conn.execute(text(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
        ))
    return [row[0] for row in result]


def _find_numeric_pairs(conn, tables, dialect):
    NUMERIC_TYPES = {"int", "integer", "bigint", "decimal", "numeric", "real",
                    "double precision", "float", "money", "smallint"}
    pairs = []
    for table in tables[:20]:
        try:
            if dialect == "mysql":
                safe_t = table.replace("`", "``")
                cols_result = conn.execute(text(f"SHOW COLUMNS FROM `{safe_t}`"))
                cols = [(row[0], row[1]) for row in cols_result]
            elif dialect == "sqlite":
                # Table name comes from sqlite_master (self-derived); quote it.
                safe_t = table.replace('"', '""')
                cols_result = conn.execute(text(f'PRAGMA table_info("{safe_t}")'))
                cols = [(row[1], row[2]) for row in cols_result]
            else:
                cols_result = conn.execute(text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = :t AND table_schema = 'public'"
                ), {"t": table})
                cols = [(row[0], row[1]) for row in cols_result]

            numeric_cols = []
            for col_name, col_type in cols:
                if col_type and any(t in col_type.lower() for t in NUMERIC_TYPES):
                    if not col_name.lower().endswith("_id") and col_name.lower() != "id":
                        numeric_cols.append(col_name)

            if len(numeric_cols) >= 2:
                for i in range(len(numeric_cols)):
                    for j in range(i + 1, min(i + 4, len(numeric_cols))):
                        pairs.append((numeric_cols[i], numeric_cols[j], table))
        except Exception:
            continue
    return pairs


def _select_best_pair(pairs, hypothesis, conn, dialect):
    hyp_lower = hypothesis.lower()
    for x, y, table in pairs:
        if x.lower() in hyp_lower or y.lower() in hyp_lower:
            return (x, y, table)
    return pairs[0]


def _fetch_sample(conn, table, x_col, y_col, dialect):
    q_x = _quote_identifier(x_col, dialect)
    q_y = _quote_identifier(y_col, dialect)
    q_t = _quote_identifier(table, dialect)
    result = conn.execute(text(
        f"SELECT {q_x}, {q_y} FROM {q_t} WHERE {q_x} IS NOT NULL AND {q_y} IS NOT NULL LIMIT 5000"
    ))
    return result.fetchall()


def _compute_correlation(x, y):
    n = len(x)
    if n < 3:
        return {"r": 0, "r_squared": 0, "p_value": 1.0, "method": "Insufficient data"}

    mean_x, mean_y = np.mean(x), np.mean(y)
    std_x, std_y = np.std(x, ddof=1), np.std(y, ddof=1)

    if std_x == 0 or std_y == 0:
        return {"r": 0, "r_squared": 0, "p_value": 1.0, "method": "Zero variance"}

    r = float(np.corrcoef(x, y)[0, 1])
    r_squared = r ** 2

    if abs(r) >= 1.0:
        p_value = 0.0
    else:
        t_stat = r * np.sqrt((n - 2) / (1 - r_squared))
        df = n - 2
        p_value = float(2 * (1 - _t_cdf(abs(t_stat), df)))

    return {
        "r": r,
        "r_squared": r_squared,
        "p_value": p_value,
        "method": "Pearson Correlation",
    }


def _t_cdf(t, df):
    try:
        from scipy import stats
        return float(stats.t.cdf(t, df))
    except ImportError:
        x = df / (df + t ** 2)
        return 1.0 - 0.5 * _regularized_incomplete_beta(df / 2.0, 0.5, x)


def _regularized_incomplete_beta(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta)
    if x < (a + 1) / (a + b + 2):
        return front * _beta_cf(a, b, x) / a
    else:
        return 1.0 - front * _beta_cf(b, a, 1 - x) / b


def _beta_cf(a, b, x):
    max_iter = 200
    eps = 1e-14
    qab = a + b
    qap = a + 1
    qam = a - 1
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _r_ci(r: float, n: int) -> dict:
    """95% confidence interval for a Pearson r via Fisher z-transform."""
    try:
        if n < 4 or abs(r) >= 1.0:
            return {"ci_low": r, "ci_high": r}
        z = 0.5 * math.log((1 + r) / (1 - r))
        se = 1.0 / math.sqrt(n - 3)
        lo = math.tanh(z - 1.96 * se)
        hi = math.tanh(z + 1.96 * se)
        return {"ci_low": round(lo, 3), "ci_high": round(hi, 3)}
    except Exception:
        return {"ci_low": r, "ci_high": r}


def _plain_col(name: str) -> str:
    """Human column label without touching the analytical logic."""
    try:
        from core.semantic import humanize

        return humanize(name)
    except Exception:
        return str(name).replace("_", " ")


def _confidence_word(p_value: float) -> str:
    if p_value < 0.01:
        return "High"
    if p_value < 0.05:
        return "Moderate"
    return "Low"


def _build_interpretation(hypothesis, stats, supported, x_col, y_col):
    r = stats["r"]
    direction = "positive" if r > 0 else "negative"
    strength = (
        "strong" if abs(r) > 0.7
        else "moderate" if abs(r) > 0.4
        else "weak"
    )
    xc, yc = _plain_col(x_col), _plain_col(y_col)
    together = "tend to rise together" if direction == "positive" else (
        "move in opposite directions: when one rises, the other tends to fall")

    if supported:
        return (
            f"The data backs this idea: {xc} and {yc} {together}, a {strength} "
            f"link. In plain terms, knowing one gives a useful read on the other. "
            f"This pattern is unlikely to be a fluke. It still does not prove "
            f"that one causes the other."
        )
    else:
        return (
            f"The data does not back this idea: the link between {xc} and {yc} "
            f"is {strength} at best, and could easily be chance. "
            f"No business decision should rest on this relationship alone."
        )
