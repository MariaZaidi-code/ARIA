"""Hypothesis testing routes: statistical tests against connected data."""

import re
import math
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import numpy as np

from core.config import get_session
from core.deps import require_data, require_writable, get_current_user
from core.secret_box import decrypt as _decrypt_secret

router = APIRouter()


def _quote_identifier(name, dialect="postgresql"):
    if dialect == "mysql":
        return f"`{name.replace('`', '``')}`"
    return f'"{name.replace(chr(34), chr(34)+chr(34))}"'


class HypothesisRequest(BaseModel):
    hypothesis: str
    dataset: str = "Sales Database"
    period: str = "Last 12 months"


@router.post("/api/hypothesis")
async def run_hypothesis(req: HypothesisRequest, request: Request, user: dict = Depends(require_writable)):
    require_data(request)
    session = get_session(user["user_id"])
    if not session or not session.get("db"):
        return {"ok": False, "detail": "No data source connected"}

    db_config = session["db"]
    db_type = session.get("db_type", "postgresql")

    if db_type in ("sqlite", "document"):
        return {"ok": False, "detail": "Hypothesis testing requires a relational database connection."}

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

        engine = create_engine(engine_url, pool_pre_ping=True)

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

            return {
                "ok": True,
                "supported": supported,
                "interpretation": interpretation,
                "stats": {
                    "Method": stats["method"],
                    "Sample Size": f"{len(x_vals):,} observations",
                    "Correlation (r)": f"{stats['r']:.3f}",
                    "R² (variance explained)": f"{stats['r_squared']:.1%}",
                    "p-value": f"{stats['p_value']:.4f}" if stats['p_value'] >= 0.0001 else "< 0.0001",
                    "Confidence": f"{(1 - stats['p_value']) * 100:.1f}%",
                },
                "scatter_data": scatter_data,
                "x_label": x_col,
                "y_label": y_col,
            }

    except Exception as e:
        return {"ok": False, "detail": f"Hypothesis test failed: {str(e)}"}


def _get_tables(conn, dialect):
    if dialect == "mysql":
        result = conn.execute(text("SHOW TABLES"))
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
                cols_result = conn.execute(text(f"SHOW COLUMNS FROM `{table}`"))
                cols = [(row[0], row[1]) for row in cols_result]
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


def _build_interpretation(hypothesis, stats, supported, x_col, y_col):
    r = stats["r"]
    direction = "positive" if r > 0 else "negative"
    strength = (
        "strong" if abs(r) > 0.7
        else "moderate" if abs(r) > 0.4
        else "weak"
    )

    if supported:
        return (
            f"A {strength} {direction} correlation (r={r:.3f}) was found between {x_col} and {y_col}. "
            f"The data supports the hypothesis with {stats['method']} (p={stats['p_value']:.4f}). "
            f"{abs(r)**2:.1%} of the variance in {y_col} is explained by {x_col}."
        )
    else:
        return (
            f"The analysis found a {strength} {direction} correlation (r={r:.3f}) between {x_col} and {y_col}, "
            f"but this was not statistically significant (p={stats['p_value']:.4f}). "
            f"The data does not support the hypothesis at the 95% confidence level."
        )
