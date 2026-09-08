"""Dashboard KPI routes — fully dynamic, database-agnostic.

Generates KPIs and charts from ANY connected database using schema metadata.
Zero hardcoded table/column names. Uses SchemaIntelligence for all decisions.
"""

import json
import re
import types
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

from core.config import get_session, SCHEMA_DIR
from core.deps import require_data, get_current_user
from core.secret_box import decrypt as _decrypt_secret
from api.schema_intel import SchemaIntelligence, _safe_name, _run_sql

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_engine(session):
    """Create a SQLAlchemy engine for the session's DB."""
    db_config = dict(session.get("db") or {})
    db_type = session.get("db_type", "postgresql")

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

    if db_config.get("password"):
        try:
            db_config["password"] = _decrypt_secret(db_config["password"])
        except Exception:
            pass

    schema = db_config.get("db_schema", "public")
    if db_type == "mysql":
        uri = (f"mysql+pymysql://{quote_plus(str(db_config['user']))}:{quote_plus(str(db_config['password']))}"
               f"@{db_config['host']}:{db_config.get('port', 3306)}/{db_config['db']}")
    else:
        uri = (f"postgresql://{quote_plus(str(db_config['user']))}:{quote_plus(str(db_config['password']))}"
               f"@{db_config['host']}:{db_config.get('port', 5432)}/{db_config['db']}"
               f"?options=-c%20search_path%3D{schema}")

    return create_engine(uri, pool_pre_ping=True), db_type, db_type


def _fmt(v, is_currency=False):
    if v is None:
        return "N/A"
    if is_currency:
        if abs(v) >= 1_000_000:
            return f"${v/1_000_000:,.1f}M"
        if abs(v) >= 1_000:
            return f"${v/1_000:,.0f}K"
        return f"${v:,.0f}"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:,.1f}M"
    if abs(v) >= 1_000:
        return f"{v/1_000:,.0f}K"
    return f"{v:,.0f}"


def _is_currency_col(col_name: str) -> bool:
    from api.schema_intel import AMOUNT_HINTS
    cl = col_name.lower()
    return any(k in cl for k in AMOUNT_HINTS)


def _safe(val):
    """SQL-escape a string value."""
    if val is None:
        return "NULL"
    return str(val).replace("'", "''")


# ── Chart Selection Intelligence ────────────────────────────────────────
# Section 45 of spec: choose chart based on analytical intent, cardinality,
# measure type, time dimension, etc. Deterministic — no LLM needed.

_CHART_BY_INTENT = {
    "time_series": "line",
    "category_comparison": "bar",
    "distribution": "histogram",
    "correlation": "scatter",
    "composition": "stacked_bar",
    "hierarchy": "treemap",
    "geographic": "map",
    "flow": "sankey",
    "financial": "waterfall",
}


def _recommend_chart(columns: list, data: list, col_types: dict = None) -> dict:
    """Recommend best chart type based on data characteristics.

    Returns {chart_type, reason, compatible_types}.
    Never overrides analytical correctness — only selects presentation.
    """
    if not columns or not data:
        return {"chart_type": "table", "reason": "No data", "compatible_types": ["table"]}

    col_types = col_types or {}
    num_cols = [c for c in columns if col_types.get(c) == "numeric" or
                (data and isinstance(data[0].get(c), (int, float)))]
    cat_cols = [c for c in columns if c not in num_cols and
                data and data[0].get(c) is not None]
    time_cols = [c for c in columns if any(k in c.lower() for k in
                 ("date", "time", "year", "month", "day", "created", "updated"))]

    # Time series detection
    if time_cols and num_cols:
        return {
            "chart_type": "line",
            "reason": f"Time dimension ({time_cols[0]}) with numeric measure",
            "compatible_types": ["line", "area", "bar"],
        }

    # Single category + single numeric → bar
    if len(cat_cols) == 1 and len(num_cols) == 1:
        cardinality = len(set(str(row.get(cat_cols[0])) for row in data[:100]))
        if cardinality <= 20:
            return {
                "chart_type": "bar",
                "reason": f"Categorical comparison ({cardinality} categories)",
                "compatible_types": ["bar", "horizontal_bar", "pie"],
            }
        else:
            return {
                "chart_type": "bar",
                "reason": f"High cardinality category ({cardinality} values)",
                "compatible_types": ["bar", "horizontal_bar"],
            }

    # Two numerics → scatter
    if len(num_cols) >= 2 and len(cat_cols) <= 2:
        return {
            "chart_type": "scatter",
            "reason": "Two numeric measures for correlation",
            "compatible_types": ["scatter", "bubble", "line"],
        }

    # Multiple categories + numeric → stacked or grouped bar
    if len(cat_cols) >= 2 and len(num_cols) >= 1:
        return {
            "chart_type": "stacked_bar",
            "reason": "Multi-dimensional comparison",
            "compatible_types": ["stacked_bar", "grouped_bar", "heatmap"],
        }

    # Single numeric only → histogram/distribution
    if len(num_cols) == 1 and len(cat_cols) == 0:
        return {
            "chart_type": "histogram",
            "reason": "Distribution of single numeric",
            "compatible_types": ["histogram", "box", "density"],
        }

    # Default: table for complex cases
    return {
        "chart_type": "table",
        "reason": "Complex data structure",
        "compatible_types": ["table", "bar"],
    }


# ── Schema loading ───────────────────────────────────────────────────────

def _load_schema(session, user_id=None):
    """Load the schema mapping and build SchemaIntelligence."""
    schema_path = session.get("schema_path")
    # Try user-specific DB schema file first (set by connect_routes)
    if schema_path and Path(str(schema_path)).exists():
        mapping = json.loads(Path(str(schema_path)).read_text(encoding="utf-8"))
        return SchemaIntelligence(mapping)
    # Fall back to the default/latest schema file (global / previous extraction)
    from core.config import SCHEMA_DIR
    default_path = SCHEMA_DIR / "schema_mapping_latest.json"
    if default_path.exists():
        mapping = json.loads(default_path.read_text(encoding="utf-8"))
        return SchemaIntelligence(mapping)
    # Try user-specific file name using DB name (connect_routes naming convention)
    db_name = session.get("db_name", "")
    if db_name:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", db_name)[:64] or "db"
        user_dir = f"user_{user_id}"
        alt_path = SCHEMA_DIR / user_dir / f"schema_mapping_{safe_name}_latest.json"
        if alt_path.exists():
            mapping = json.loads(alt_path.read_text(encoding="utf-8"))
            return SchemaIntelligence(mapping)
        # Also try the user's directory without DB name suffix
        user_default = SCHEMA_DIR / user_dir / "schema_mapping_latest.json"
        if user_default.exists() and user_default != default_path:
            mapping = json.loads(user_default.read_text(encoding="utf-8"))
            return SchemaIntelligence(mapping)
    # Last resort: try to trigger auto-extraction from the session DB info
    if session.get("db") and session.get("db_type") in ("postgresql", "mysql"):
        try:
            import schema_agent
            config = dict(session.get("db", {}))
            if "password" in config and config.get("password"):
                try:
                    config["password"] = _decrypt_secret(config["password"])
                except Exception:
                    pass
            conn = schema_agent.get_connection(types.SimpleNamespace(**config))
            try:
                db_type = session.get("db_type", "postgresql")
                schema_filter = config.get("db_schema", "public") if db_type == "postgresql" else config.get("db", "")
                mapping = schema_agent.build_schema_mapping(conn, schema_filter, db_type=db_type)
                conn.close()
                if mapping.get("tables"):
                    # Save to user-specific path for future requests
                    user_dir_path = SCHEMA_DIR / f"user_{user_id}"
                    user_dir_path.mkdir(parents=True, exist_ok=True)
                    safe_db = re.sub(r"[^a-zA-Z0-9_-]+", "_", db_name)[:64] or "db"
                    user_path = user_dir_path / f"schema_mapping_{safe_db}_latest.json"
                    user_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
                    session["schema_path"] = user_path
                    from core.config import save_session
                    # We can't save here easily without user_id — skip persistence
                    return SchemaIntelligence(mapping)
            except Exception:
                pass
        except Exception:
            pass
    # Final fallback: read schema directly from SQLite DB file (CSV uploads, broken sessions)
    sqlite_path_str = session.get("db_uri") or session.get("csv_db_path")
    if sqlite_path_str and isinstance(sqlite_path_str, (str, Path)):
        sqlite_path_str = str(sqlite_path_str)
        if sqlite_path_str.startswith("sqlite:///"):
            sqlite_file = sqlite_path_str[10:]
        elif sqlite_path_str.startswith("sqlite://"):
            sqlite_file = sqlite_path_str[9:]
        else:
            sqlite_file = sqlite_path_str
        try:
            sqlite_path_obj = Path(sqlite_file)
            if sqlite_path_obj.exists():
                import sqlite3
                conn_sqlite = sqlite3.connect(str(sqlite_path_obj))
                cursor_sqlite = conn_sqlite.cursor()
                cursor_sqlite.execute("SELECT name FROM sqlite_master WHERE type='table';")
                table_rows = cursor_sqlite.fetchall()
                conn_sqlite.close()
                tables_mapping = {}
                for (tname,) in table_rows:
                    # Get column info from PRAGMA
                    try:
                        conn2 = sqlite3.connect(str(sqlite_path_obj))
                        cur2 = conn2.cursor()
                        cur2.execute(f'PRAGMA table_info("{tname}")')
                        col_rows = cur2.fetchall()
                        conn2.close()
                        columns = []
                        inferred_pk = []
                        for row in col_rows:
                            cid, cname, ctype, notnull, dflt, pk = row
                            columns.append({
                                "column": cname,
                                "data_type": ctype or "TEXT",
                                "nullable": not (notnull == 1),
                            })
                            if pk == 1:
                                inferred_pk.append(cname)
                        tables_mapping[tname] = {
                            "columns": columns,
                            "primary_key": inferred_pk,
                            "inferred_primary_key": inferred_pk,
                            "description": tname,
                        }
                    except Exception:
                        pass
                if tables_mapping:
                    mapping = {
                        "database": session.get("db_name") or Path(sqlite_file).stem,
                        "tables": tables_mapping,
                        "declared_relationships": [],
                        "inferred_relationships": [],
                    }
                    return SchemaIntelligence(mapping)
        except Exception:
            pass
    return None


# ── Generic KPI endpoint (works for ANY database) ────────────────────────

@router.get("/api/dashboard/kpis")
def get_dashboard_kpis(request: Request, user: dict = Depends(get_current_user)):
    """Return real KPI metrics from any connected database."""
    session = get_session(user["user_id"])
    intel = _load_schema(session, user["user_id"])
    if not intel or not intel.tables:
        return {"ok": True, "kpis": [], "charts": [], "summary": {}}

    engine, dialect, db_type = _build_engine(session)
    if engine is None:
        return {"ok": True, "kpis": [], "charts": [], "summary": {
            "source_type": session.get("source_type", "file"),
            "message": "KPIs are not available for this source yet",
        }}

    kpis = []
    charts = []

    try:
        with engine.connect() as conn:
            # 1. Total records across all tables
            total = 0
            for tname in list(intel.tables.keys())[:14]:
                try:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {_safe_name(tname, dialect)}"))
                    row = result.fetchone()
                    if row:
                        total += row[0]
                except Exception:
                    continue
            if total > 0:
                kpis.append({
                    "label": "Total Records",
                    "value": _fmt(total),
                    "rawValue": total,
                    "change": None,
                    "prefix": "",
                    "period": "All data",
                })

            # 2. Per-table measures: find the best measure per table
            tables_with_measures = []
            for tname in list(intel.tables.keys())[:10]:
                if intel.tables[tname].get("empty"):
                    continue
                measure = intel.find_best_measure(tname)
                if not measure:
                    continue
                tables_with_measures.append((tname, measure))

            for tname, measure in tables_with_measures[:5]:
                is_curr = _is_currency_col(measure)
                try:
                    result = conn.execute(text(
                        f"SELECT SUM({_safe_name(measure, dialect)}) FROM {_safe_name(tname, dialect)}"
                    ))
                    row = result.fetchone()
                    if row and row[0] is not None:
                        val = float(row[0])
                        tdesc = intel.tables[tname].get("description", tname)
                        kpis.append({
                            "label": f"{measure} ({tdesc[:20]})",
                            "value": _fmt(val, is_curr),
                            "rawValue": val,
                            "change": None,
                            "prefix": "$" if is_curr else "",
                            "period": "Total",
                        })
                except Exception:
                    continue

            # 3. Per-table averages
            for tname, measure in tables_with_measures[:3]:
                is_curr = _is_currency_col(measure)
                try:
                    result = conn.execute(text(
                        f"SELECT AVG({_safe_name(measure, dialect)}) FROM {_safe_name(tname, dialect)}"
                    ))
                    row = result.fetchone()
                    if row and row[0] is not None:
                        val = float(row[0])
                        if len(kpis) < 8:
                            kpis.append({
                                "label": f"Avg {measure}",
                                "value": _fmt(val, is_curr),
                                "rawValue": val,
                                "change": None,
                                "prefix": "$" if is_curr else "",
                                "period": "Average",
                            })
                except Exception:
                    continue

            # 4. Time-series chart: find a table with datetime + measure
            for tname in list(intel.tables.keys())[:14]:
                if intel.tables[tname].get("empty"):
                    continue
                dt_col = intel.find_best_datetime(tname)
                measure = intel.find_best_measure(tname)
                if not dt_col or not measure:
                    continue

                try:
                    if dialect == "sqlite":
                        time_expr = f"strftime('%Y-%m', {_safe_name(dt_col, dialect)})"
                    elif dialect == "mysql":
                        time_expr = f"DATE_FORMAT({_safe_name(dt_col, dialect)}, '%Y-%m')"
                    else:
                        time_expr = f"TO_CHAR({_safe_name(dt_col, dialect)}, 'YYYY-MM')"

                    result = conn.execute(text(
                        f"SELECT {time_expr} AS period, "
                        f"SUM({_safe_name(measure, dialect)}) AS val "
                        f"FROM {_safe_name(tname, dialect)} "
                        f"WHERE {_safe_name(dt_col, dialect)} IS NOT NULL "
                        f"GROUP BY period ORDER BY period LIMIT 30"
                    ))
                    rows = result.fetchall()
                    if rows:
                        chart_data = [{"period": str(r[0]), "value": float(r[1])} for r in rows if r[1] is not None]
                        if chart_data:
                            tdesc = intel.tables[tname].get("description", tname)
                            is_curr = _is_currency_col(measure)
                            charts.append({
                                "title": f"{measure} over time ({tdesc[:15]})",
                                "type": "area",
                                "data": chart_data,
                                "dataKey": "value",
                                "xKey": "period",
                                "format": "currency" if is_curr else "number",
                            })
                            if len(charts) >= 3:
                                break
                except Exception:
                    continue

            # 5. Categorical chart: find a table with a good dimension + measure
            if len(charts) < 3:
                for tname in list(intel.tables.keys())[:14]:
                    if intel.tables[tname].get("empty"):
                        continue
                    dim = intel.find_best_dimension(tname)
                    measure = intel.find_best_measure(tname)
                    if not dim or not measure:
                        continue
                    # Skip if we already have a chart for this table
                    if any(tname in str(c.get("title", "")) for c in charts):
                        continue

                    try:
                        result = conn.execute(text(
                            f"SELECT {_safe_name(dim, dialect)} AS dim_val, "
                            f"SUM({_safe_name(measure, dialect)}) AS val "
                            f"FROM {_safe_name(tname, dialect)} "
                            f"WHERE {_safe_name(dim, dialect)} IS NOT NULL "
                            f"GROUP BY dim_val ORDER BY val DESC LIMIT 8"
                        ))
                        rows = result.fetchall()
                        if rows:
                            chart_data = [{"name": str(r[0]), "value": float(r[1])} for r in rows if r[1] is not None]
                            if chart_data:
                                tdesc = intel.tables[tname].get("description", tname)
                                is_curr = _is_currency_col(measure)
                                charts.append({
                                    "title": f"{measure} by {dim} ({tdesc[:15]})",
                                    "type": "bar",
                                    "data": chart_data,
                                    "dataKey": "value",
                                    "xKey": "name",
                                    "format": "currency" if is_curr else "number",
                                })
                                if len(charts) >= 3:
                                    break
                    except Exception:
                        continue

    except Exception:
        pass

    # Summary
    db_name = session.get("db_name", "")
    summary = {
        "source_type": "relational",
        "database": db_name,
        "tables_used": len(intel.tables),
        "message": None,
    }

    # Generate smart recommendations based on schema
    recommendations = []
    for tname in list(intel.tables.keys())[:5]:
        tdesc = intel.tables[tname].get("description", tname)
        measure = intel.find_best_measure(tname)
        dim = intel.find_best_dimension(tname)
        dt = intel.find_best_datetime(tname)
        if measure and dim:
            recommendations.append({"q": f"What are the top {dim} by {measure}?"})
        if measure and dt:
            recommendations.append({"q": f"How has {measure} changed over time?"})
        if measure and dim and len(recommendations) < 6:
            recommendations.append({"q": f"Show {measure} breakdown by {dim}"})

    return {"ok": True, "kpis": kpis[:8], "charts": charts[:3], "summary": summary, "recommendations": recommendations[:6]}


# ── Real KPI endpoint (same route, enhanced logic) ───────────────────────

@router.get("/api/dashboard/real_kpis")
def get_real_kpis(request: Request, user: dict = Depends(get_current_user)):
    """Alias for /api/dashboard/kpis — uses the same dynamic engine."""
    return get_dashboard_kpis(request, user)


# ── Dashboard summary (wraps KPIs + recommendations) ─────────────────────

@router.get("/api/dashboard/summary")
def get_dashboard_summary(request: Request, user: dict = Depends(get_current_user)):
    """Return KPI summary with smart recommendations."""
    session = get_session(user["user_id"])
    intel = _load_schema(session, user["user_id"])
    if not intel or not intel.tables:
        return {"ok": True, "kpis": [], "charts": [], "recommendations": []}

    kpi_result = get_dashboard_kpis(request, user)
    kpis = kpi_result.get("kpis", [])
    charts = kpi_result.get("charts", [])

    # Generate recommendations based on what tables exist
    recommendations = []
    fact_tables = [t for t in intel.tables if intel.is_fact_table(t)]
    dim_tables = [t for t in intel.tables if intel.is_dimension_table(t)]

    for tname in fact_tables[:3]:
        tdesc = intel.tables[tname].get("description", tname)
        measure = intel.find_best_measure(tname)
        dim = intel.find_best_dimension(tname)
        dt = intel.find_best_datetime(tname)
        if measure and dim:
            recommendations.append(f"What are the top {dim} by {measure} in {tdesc}?")
        if measure and dt:
            recommendations.append(f"How has {measure} changed over time in {tdesc}?")

    for tname in dim_tables[:2]:
        tdesc = intel.tables[tname].get("description", tname)
        recommendations.append(f"Show all records in {tdesc}")

    return {
        "ok": True,
        "kpis": kpis,
        "charts": charts,
        "recommendations": recommendations[:6],
    }


# ── Dashboard section summaries (one per analytical page) ────────────────

@router.get("/api/dashboard/summaries")
def get_dashboard_summaries(request: Request, user: dict = Depends(get_current_user)):
    """Return lightweight summaries for each Dashboard section (AI Analytics,
    Insights, Predictive, Prescription, Hypothesis). Each summary is generated
    from the actual connected data using schema intelligence + quick queries."""
    session = get_session(user["user_id"])
    intel = _load_schema(session, user["user_id"])
    if not intel or not intel.tables:
        return {"ok": True, "sections": []}

    engine, dialect, db_type = _build_engine(session)
    if engine is None:
        return {"ok": True, "sections": []}

    sections = []

    try:
        with engine.connect() as conn:
            # --- AI Analytics summary: top metric + trend ---
            for tname in list(intel.tables.keys()):
                measure = intel.find_best_measure(tname)
                if not measure:
                    continue
                tdesc = intel.tables[tname].get("description", tname)
                is_curr = _is_currency_col(measure)

                # Get total
                try:
                    result = conn.execute(text(
                        f"SELECT SUM({_safe_name(measure, dialect)}) FROM {_safe_name(tname, dialect)}"
                    ))
                    row = result.fetchone()
                    total = float(row[0]) if row and row[0] is not None else None
                except Exception:
                    total = None

                if total is not None:
                    sections.append({
                        "type": "analytics",
                        "title": f"{measure} Overview",
                        "metric": _fmt(total, is_curr),
                        "description": f"Total {measure} across {tdesc}: {_fmt(total, is_curr)}. Use AI Analytics to explore trends, breakdowns, and detailed analysis.",
                        "query": f"What is the total {measure}?",
                    })
                    break

            # --- Insights summary: top anomaly or trend ---
            for tname in list(intel.tables.keys()):
                measure = intel.find_best_measure(tname)
                dt = intel.find_best_datetime(tname)
                if not measure or not dt:
                    continue
                tdesc = intel.tables[tname].get("description", tname)
                try:
                    if dialect == "sqlite":
                        time_expr = f"strftime('%Y-%m', {_safe_name(dt, dialect)})"
                    elif dialect == "mysql":
                        time_expr = f"DATE_FORMAT({_safe_name(dt, dialect)}, '%Y-%m')"
                    else:
                        time_expr = f"TO_CHAR({_safe_name(dt, dialect)}, 'YYYY-MM')"
                    result = conn.execute(text(
                        f"SELECT {time_expr} AS period, SUM({_safe_name(measure, dialect)}) AS val "
                        f"FROM {_safe_name(tname, dialect)} "
                        f"WHERE {_safe_name(dt, dialect)} IS NOT NULL "
                        f"GROUP BY period ORDER BY period DESC LIMIT 6"
                    ))
                    rows = result.fetchall()
                    if len(rows) >= 2:
                        vals = [(str(r[0]), float(r[1])) for r in rows if r[1] is not None]
                        if len(vals) >= 2:
                            curr, prev = vals[0], vals[1]
                            if prev != 0:
                                change = ((curr[1] - prev[1]) / abs(prev[1])) * 100
                                direction = "increased" if change > 0 else "decreased"
                                sections.append({
                                    "type": "insights",
                                    "title": f"{measure} Trend Detected",
                                    "metric": f"{change:+.1f}%",
                                    "description": f"{measure} in {tdesc} {direction} by {abs(change):.1f}% from {prev[0]} to {curr[0]}. Insights page has detailed analysis of all patterns.",
                                    "query": f"What are the trends in {measure}?",
                                })
                                break
                except Exception:
                    continue

            # --- Predictive summary: time-series availability ---
            for tname in list(intel.tables.keys()):
                measure = intel.find_best_measure(tname)
                dt = intel.find_best_datetime(tname)
                if not measure or not dt:
                    continue
                tdesc = intel.tables[tname].get("description", tname)
                try:
                    result = conn.execute(text(
                        f"SELECT COUNT(DISTINCT strftime('%Y-%m', {_safe_name(dt, dialect)})) "
                        f"FROM {_safe_name(tname, dialect)} "
                        f"WHERE {_safe_name(dt, dialect)} IS NOT NULL"
                    ))
                    row = result.fetchone()
                    months = int(row[0]) if row and row[0] else 0
                    if months >= 3:
                        sections.append({
                            "type": "predictive",
                            "title": f"{measure} Forecast Available",
                            "metric": f"{months} months of data",
                            "description": f"Connected data has {months} months of {measure} history in {tdesc}. Predictive Analysis can generate forecasts with confidence intervals.",
                            "query": f"Forecast {measure} over time",
                        })
                        break
                except Exception:
                    continue

            # --- Prescription summary ---
            for tname in list(intel.tables.keys()):
                measure = intel.find_best_measure(tname)
                dim = intel.find_best_dimension(tname)
                if not measure or not dim:
                    continue
                tdesc = intel.tables[tname].get("description", tname)
                try:
                    result = conn.execute(text(
                        f"SELECT {_safe_name(dim, dialect)} AS d, SUM({_safe_name(measure, dialect)}) AS v "
                        f"FROM {_safe_name(tname, dialect)} "
                        f"WHERE {_safe_name(dim, dialect)} IS NOT NULL "
                        f"GROUP BY d ORDER BY v DESC LIMIT 5"
                    ))
                    rows = result.fetchall()
                    if len(rows) >= 2:
                        top = rows[0]
                        sections.append({
                            "type": "prescription",
                            "title": f"Top {dim}: {top[0]}",
                            "metric": _fmt(float(top[1]), _is_currency_col(measure)),
                            "description": f"The leading {dim} in {tdesc} is '{top[0]}'. Prescription page can generate evidence-based recommendations.",
                            "query": f"What actions should I take based on {measure}?",
                        })
                        break
                except Exception:
                    continue

            # --- Hypothesis summary: numeric pairs available ---
            has_numeric_pairs = False
            for tname in list(intel.tables.keys()):
                numerics = intel.get_numeric_cols(tname)
                non_id = [c for c in numerics if not c.lower().endswith("_id") and c.lower() != "id"]
                if len(non_id) >= 2:
                    tdesc = intel.tables[tname].get("description", tname)
                    sections.append({
                        "type": "hypothesis",
                        "title": f"Statistical Testing Available",
                        "metric": f"{len(non_id)} numeric measures",
                        "description": f"{tdesc} has {len(non_id)} numeric measures suitable for correlation and hypothesis testing.",
                        "query": "Is there a correlation between numeric measures?",
                    })
                    has_numeric_pairs = True
                    break

    except Exception:
        pass

    return {"ok": True, "sections": sections[:5]}


# ── Unified dashboard config (backend-driven, frontend renders) ───────────

@router.get("/api/dashboard/config")
def get_dashboard_config(request: Request, user: dict = Depends(get_current_user)):
    """Return a structured dashboard configuration generated from the connected data.

    The frontend renders whatever this endpoint returns — zero business logic
    on the client side. This is the single source of truth for the dashboard.
    """
    session = get_session(user["user_id"])
    intel = _load_schema(session, user["user_id"])
    if not intel or not intel.tables:
        return {
            "ok": True,
            "config": {
                "summary": {"title": "No Data Connected", "description": "Connect a database or upload a file to start analyzing.", "tableCount": 0, "totalRows": 0},
                "metrics": [],
                "visualizations": [],
                "sections": [],
                "quality": {"score": 0, "issues": []},
                "recommendations": [],
            },
        }

    engine, dialect, db_type = _build_engine(session)
    db_name = session.get("db_name", session.get("source_type", "data"))
    tables_list = list(intel.tables.keys())

    metrics = []
    charts = []
    sections = []
    recommendations = []
    total_rows = 0
    quality_issues = []

    if engine is not None:
        try:
            with engine.connect() as conn:
                # ── Total records ──
                for tname in tables_list[:14]:
                    try:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {_safe_name(tname, dialect)}"))
                        row = result.fetchone()
                        if row:
                            total_rows += row[0]
                    except Exception:
                        continue

                if total_rows > 0:
                    metrics.append({
                        "id": "total_records",
                        "label": "Total Records",
                        "value": _fmt(total_rows),
                        "rawValue": total_rows,
                        "format": "number",
                        "period": "All data",
                        "icon": "database",
                        "color": "#4F46E5",
                    })

                # ── Per-table measures ──
                tables_with_measures = []
                for tname in tables_list[:10]:
                    if intel.tables[tname].get("empty"):
                        continue
                    measure = intel.find_best_measure(tname)
                    if not measure:
                        continue
                    tables_with_measures.append((tname, measure))

                for tname, measure in tables_with_measures[:5]:
                    is_curr = _is_currency_col(measure)
                    try:
                        result = conn.execute(text(
                            f"SELECT SUM({_safe_name(measure, dialect)}) FROM {_safe_name(tname, dialect)}"
                        ))
                        row = result.fetchone()
                        if row and row[0] is not None:
                            val = float(row[0])
                            tdesc = intel.tables[tname].get("description", tname)
                            metrics.append({
                                "id": f"{tname}_{measure}",
                                "label": f"{measure} ({tdesc[:20]})",
                                "value": _fmt(val, is_curr),
                                "rawValue": val,
                                "format": "currency" if is_curr else "number",
                                "period": "Total",
                                "icon": "trending-up",
                                "color": "#059669" if is_curr else "#4F46E5",
                            })
                    except Exception:
                        continue

                # ── Per-table averages ──
                for tname, measure in tables_with_measures[:3]:
                    is_curr = _is_currency_col(measure)
                    try:
                        result = conn.execute(text(
                            f"SELECT AVG({_safe_name(measure, dialect)}) FROM {_safe_name(tname, dialect)}"
                        ))
                        row = result.fetchone()
                        if row and row[0] is not None:
                            val = float(row[0])
                            if len(metrics) < 8:
                                metrics.append({
                                    "id": f"avg_{tname}_{measure}",
                                    "label": f"Avg {measure}",
                                    "value": _fmt(val, is_curr),
                                    "rawValue": val,
                                    "format": "currency" if is_curr else "number",
                                    "period": "Average",
                                    "icon": "bar-chart",
                                    "color": "#F59E0B",
                                })
                    except Exception:
                        continue

                # ── Time-series charts ──
                for tname in tables_list[:14]:
                    if intel.tables[tname].get("empty"):
                        continue
                    dt_col = intel.find_best_datetime(tname)
                    measure = intel.find_best_measure(tname)
                    if not dt_col or not measure:
                        continue
                    try:
                        if dialect == "sqlite":
                            time_expr = f"strftime('%Y-%m', {_safe_name(dt_col, dialect)})"
                        elif dialect == "mysql":
                            time_expr = f"DATE_FORMAT({_safe_name(dt_col, dialect)}, '%Y-%m')"
                        else:
                            time_expr = f"TO_CHAR({_safe_name(dt_col, dialect)}, 'YYYY-MM')"
                        result = conn.execute(text(
                            f"SELECT {time_expr} AS period, "
                            f"SUM({_safe_name(measure, dialect)}) AS val "
                            f"FROM {_safe_name(tname, dialect)} "
                            f"WHERE {_safe_name(dt_col, dialect)} IS NOT NULL "
                            f"GROUP BY period ORDER BY period LIMIT 30"
                        ))
                        rows = result.fetchall()
                        if rows:
                            chart_data = [{"period": str(r[0]), "value": float(r[1])} for r in rows if r[1] is not None]
                            if chart_data:
                                tdesc = intel.tables[tname].get("description", tname)
                                is_curr = _is_currency_col(measure)
                                charts.append({
                                    "id": f"ts_{tname}_{measure}",
                                    "title": f"{measure} over time ({tdesc[:15]})",
                                    "type": "area",
                                    "data": chart_data,
                                    "dataKey": "value",
                                    "xKey": "period",
                                    "format": "currency" if is_curr else "number",
                                })
                                if len(charts) >= 3:
                                    break
                    except Exception:
                        continue

                # ── Categorical charts ──
                if len(charts) < 3:
                    for tname in tables_list[:14]:
                        if intel.tables[tname].get("empty"):
                            continue
                        dim = intel.find_best_dimension(tname)
                        measure = intel.find_best_measure(tname)
                        if not dim or not measure:
                            continue
                        if any(tname in str(c.get("title", "")) for c in charts):
                            continue
                        try:
                            result = conn.execute(text(
                                f"SELECT {_safe_name(dim, dialect)} AS dim_val, "
                                f"SUM({_safe_name(measure, dialect)}) AS val "
                                f"FROM {_safe_name(tname, dialect)} "
                                f"WHERE {_safe_name(dim, dialect)} IS NOT NULL "
                                f"GROUP BY dim_val ORDER BY val DESC LIMIT 8"
                            ))
                            rows = result.fetchall()
                            if rows:
                                chart_data = [{"name": str(r[0]), "value": float(r[1])} for r in rows if r[1] is not None]
                                if chart_data:
                                    tdesc = intel.tables[tname].get("description", tname)
                                    is_curr = _is_currency_col(measure)
                                    charts.append({
                                        "id": f"cat_{tname}_{measure}",
                                        "title": f"{measure} by {dim} ({tdesc[:15]})",
                                        "type": "bar",
                                        "data": chart_data,
                                        "dataKey": "value",
                                        "xKey": "name",
                                        "format": "currency" if is_curr else "number",
                                    })
                                    if len(charts) >= 3:
                                        break
                        except Exception:
                            continue

                # ── Section summaries (analytics, insights, predictive, etc.) ──
                # Analytics
                for tname in tables_list:
                    measure = intel.find_best_measure(tname)
                    if not measure:
                        continue
                    tdesc = intel.tables[tname].get("description", tname)
                    is_curr = _is_currency_col(measure)
                    try:
                        result = conn.execute(text(
                            f"SELECT SUM({_safe_name(measure, dialect)}) FROM {_safe_name(tname, dialect)}"
                        ))
                        row = result.fetchone()
                        total = float(row[0]) if row and row[0] is not None else None
                    except Exception:
                        total = None
                    if total is not None:
                        sections.append({
                            "type": "analytics",
                            "title": f"{measure} Overview",
                            "metric": _fmt(total, is_curr),
                            "description": f"Total {measure} across {tdesc}: {_fmt(total, is_curr)}. Use AI Analytics to explore trends, breakdowns, and detailed analysis.",
                            "query": f"What is the total {measure}?",
                        })
                        break

                # Insights
                for tname in tables_list:
                    measure = intel.find_best_measure(tname)
                    dt = intel.find_best_datetime(tname)
                    if not measure or not dt:
                        continue
                    tdesc = intel.tables[tname].get("description", tname)
                    try:
                        if dialect == "sqlite":
                            time_expr = f"strftime('%Y-%m', {_safe_name(dt, dialect)})"
                        elif dialect == "mysql":
                            time_expr = f"DATE_FORMAT({_safe_name(dt, dialect)}, '%Y-%m')"
                        else:
                            time_expr = f"TO_CHAR({_safe_name(dt, dialect)}, 'YYYY-MM')"
                        result = conn.execute(text(
                            f"SELECT {time_expr} AS period, SUM({_safe_name(measure, dialect)}) AS val "
                            f"FROM {_safe_name(tname, dialect)} "
                            f"WHERE {_safe_name(dt, dialect)} IS NOT NULL "
                            f"GROUP BY period ORDER BY period DESC LIMIT 6"
                        ))
                        rows = result.fetchall()
                        if len(rows) >= 2:
                            vals = [(str(r[0]), float(r[1])) for r in rows if r[1] is not None]
                            if len(vals) >= 2:
                                curr, prev = vals[0], vals[1]
                                if prev != 0:
                                    change = ((curr[1] - prev[1]) / abs(prev[1])) * 100
                                    direction = "increased" if change > 0 else "decreased"
                                    sections.append({
                                        "type": "insights",
                                        "title": f"{measure} Trend Detected",
                                        "metric": f"{change:+.1f}%",
                                        "description": f"{measure} in {tdesc} {direction} by {abs(change):.1f}% from {prev[0]} to {curr[0]}. Insights page has detailed analysis of all patterns.",
                                        "query": f"What are the trends in {measure}?",
                                    })
                                    break
                    except Exception:
                        continue

                # Predictive
                for tname in tables_list:
                    measure = intel.find_best_measure(tname)
                    dt = intel.find_best_datetime(tname)
                    if not measure or not dt:
                        continue
                    tdesc = intel.tables[tname].get("description", tname)
                    try:
                        result = conn.execute(text(
                            f"SELECT COUNT(DISTINCT strftime('%Y-%m', {_safe_name(dt, dialect)})) "
                            f"FROM {_safe_name(tname, dialect)} "
                            f"WHERE {_safe_name(dt, dialect)} IS NOT NULL"
                        ))
                        row = result.fetchone()
                        months = int(row[0]) if row and row[0] else 0
                        if months >= 3:
                            sections.append({
                                "type": "predictive",
                                "title": f"{measure} Forecast Available",
                                "metric": f"{months} months of data",
                                "description": f"Connected data has {months} months of {measure} history in {tdesc}. Predictive Analysis can generate forecasts with confidence intervals.",
                                "query": f"Forecast {measure} over time",
                            })
                            break
                    except Exception:
                        continue

                # Prescription
                for tname in tables_list:
                    measure = intel.find_best_measure(tname)
                    dim = intel.find_best_dimension(tname)
                    if not measure or not dim:
                        continue
                    tdesc = intel.tables[tname].get("description", tname)
                    try:
                        result = conn.execute(text(
                            f"SELECT {_safe_name(dim, dialect)} AS d, SUM({_safe_name(measure, dialect)}) AS v "
                            f"FROM {_safe_name(tname, dialect)} "
                            f"WHERE {_safe_name(dim, dialect)} IS NOT NULL "
                            f"GROUP BY d ORDER BY v DESC LIMIT 5"
                        ))
                        rows = result.fetchall()
                        if len(rows) >= 2:
                            top = rows[0]
                            sections.append({
                                "type": "prescription",
                                "title": f"Top {dim}: {top[0]}",
                                "metric": _fmt(float(top[1]), _is_currency_col(measure)),
                                "description": f"The leading {dim} in {tdesc} is '{top[0]}'. Prescription page can generate evidence-based recommendations.",
                                "query": f"What actions should I take based on {measure}?",
                            })
                            break
                    except Exception:
                        continue

                # Hypothesis
                for tname in tables_list:
                    numerics = intel.get_numeric_cols(tname)
                    non_id = [c for c in numerics if not c.lower().endswith("_id") and c.lower() != "id"]
                    if len(non_id) >= 2:
                        tdesc = intel.tables[tname].get("description", tname)
                        sections.append({
                            "type": "hypothesis",
                            "title": "Statistical Testing Available",
                            "metric": f"{len(non_id)} numeric measures",
                            "description": f"{tdesc} has {len(non_id)} numeric measures suitable for correlation and hypothesis testing.",
                            "query": "Is there a correlation between numeric measures?",
                        })
                        break

                # ── Recommendations ──
                for tname in tables_list[:5]:
                    measure = intel.find_best_measure(tname)
                    dim = intel.find_best_dimension(tname)
                    dt = intel.find_best_datetime(tname)
                    if measure and dim:
                        recommendations.append({"id": f"rec_{tname}_dim", "question": f"What are the top {dim} by {measure}?", "type": "dimension"})
                    if measure and dt:
                        recommendations.append({"id": f"rec_{tname}_trend", "question": f"How has {measure} changed over time?", "type": "trend"})
                    if measure and dim and len(recommendations) < 6:
                        recommendations.append({"id": f"rec_{tname}_breakdown", "question": f"Show {measure} breakdown by {dim}", "type": "breakdown"})

                # ── Data quality ──
                quality_score = 100
                for tname in tables_list[:5]:
                    measure = intel.find_best_measure(tname)
                    if not measure:
                        continue
                    try:
                        result = conn.execute(text(
                            f"SELECT COUNT(*) FROM {_safe_name(tname, dialect)} WHERE {_safe_name(measure, dialect)} IS NULL"
                        ))
                        row = result.fetchone()
                        if row and row[0] > 0:
                            total_q = conn.execute(text(f"SELECT COUNT(*) FROM {_safe_name(tname, dialect)}")).fetchone()
                            if total_q and total_q[0] > 0:
                                pct = (row[0] / total_q[0]) * 100
                                if pct > 0:
                                    quality_issues.append({
                                        "field": f"{tname}.{measure}",
                                        "issue": f"{pct:.1f}% null values",
                                        "severity": "warning" if pct < 10 else "critical",
                                        "affectedRecords": row[0],
                                    })
                                    quality_score -= min(10, int(pct))
                    except Exception:
                        continue

        except Exception:
            pass

    config = {
        "summary": {
            "title": f"Data Analysis: {db_name}",
            "description": f"ARIA analyzed {len(tables_list)} tables with {_fmt(total_rows)} total records.",
            "tableCount": len(tables_list),
            "totalRows": total_rows,
            "database": db_name,
        },
        "metrics": metrics[:8],
        "visualizations": charts[:3],
        "sections": sections[:5],
        "quality": {"score": max(0, quality_score), "issues": quality_issues[:10]},
        "recommendations": recommendations[:6],
    }

    return {"ok": True, "config": config}


@router.get("/api/chart/recommend")
def recommend_chart(request: Request, columns: str = "", user: dict = Depends(get_current_user)):
    """Recommend chart type based on column characteristics.

    Query params: columns (comma-separated column names).
    Returns recommended chart type and compatible alternatives.
    """
    session = get_session(user["user_id"])
    cols = [c.strip() for c in columns.split(",") if c.strip()]

    # Get data sample if available
    data_sample = []
    processed_path = session.get("processed_path")
    if processed_path:
        try:
            pp = Path(processed_path)
            if pp.exists():
                pdata = json.loads(pp.read_text(encoding="utf-8"))
                data_sample = (pdata.get("data") or [])[:5]
        except Exception:
            pass

    result = _recommend_chart(cols, data_sample)

    # Apply user preference override if available
    from api.feedback_routes import _load_prefs
    prefs = _load_prefs(user["user_id"])
    chart_history = prefs.get("chart_type_history", {})
    context_key = "_".join(sorted(cols[:3])) if cols else "general"
    if context_key in chart_history:
        counts = chart_history[context_key]
        preferred = max(counts, key=counts.get) if counts else None
        if preferred and preferred in result.get("compatible_types", []):
            result["preferred_type"] = preferred
            result["user_override"] = True

    return {"ok": True, "recommendation": result}
