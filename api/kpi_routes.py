"""Dashboard KPI routes: quick summary metrics from the connected data."""

import json
import re
from fastapi import APIRouter, Depends, Request
from sqlalchemy import create_engine, text

from core.config import get_session
from core.deps import require_data
from core.secret_box import decrypt as _decrypt_secret

router = APIRouter()


def _quote_identifier(name, dialect="postgresql"):
    """Quote a SQL identifier to prevent injection."""
    if dialect == "mysql":
        return f"`{name.replace('`', '``')}`"
    return f'"{name.replace(chr(34), chr(34)+chr(34))}"'


def _numeric_columns(table_info):
    """Find columns that look numeric (money, count, quantity, etc.)."""
    keywords = [
        "amount", "price", "cost", "revenue", "sales", "total", "sum",
        "count", "quantity", "qty", "value", "profit", "income", "balance",
        "order", "pay", "discount", "tax", "fee", "rate", "percent",
        "number", "num", "id", "stock", "weight", "score",
    ]
    cols = []
    for col_name, col_info in (table_info.get("columns") or {}).items():
        low = col_name.lower()
        # Check column name matches business metric keywords
        if any(kw in low for kw in keywords):
            cols.append(col_name)
        # Check if the column type looks numeric
        dtype = str(col_info.get("dtype", "")).lower()
        if any(t in dtype for t in ("int", "float", "decimal", "numeric", "bigint", "double")):
            if col_name not in cols:
                cols.append(col_name)
    return cols


def _date_columns(table_info):
    """Find columns that look like dates."""
    cols = []
    for col_name, col_info in (table_info.get("columns") or {}).items():
        low = col_name.lower()
        if any(kw in low for kw in ("date", "time", "created", "updated", "day", "month", "year", "period")):
            cols.append(col_name)
    return cols


@router.get("/api/dashboard/kpis")
def get_dashboard_kpis(request: Request, user: dict = Depends(require_data)):
    """Return real KPI metrics from the connected database."""
    session = get_session(user["user_id"])
    schema_path = session["schema_path"]

    if not schema_path.exists():
        return {"ok": True, "kpis": [], "charts": [], "summary": {}}

    mapping = json.loads(schema_path.read_text(encoding="utf-8"))
    tables = mapping.get("tables", {})

    if not tables:
        return {"ok": True, "kpis": [], "charts": [], "summary": {}}

    # Check if this is a CSV/PDF source (no database connection)
    if not session.get("db"):
        return {
            "ok": True,
            "kpis": [],
            "charts": [],
            "summary": {
                "source_type": session.get("source_type", "file"),
                "message": "KPIs are not available for CSV/PDF sources yet"
            }
        }

    # Build connection
    db_config = dict(session["db"])
    if "password" in db_config and db_config["password"]:
        db_config["password"] = _decrypt_secret(db_config["password"])

    db_type = session.get("db_type", "postgresql")
    db_name = session.get("db_name", "")
    dialect = session.get("dialect", db_type)

    if db_type == "mysql":
        uri = f"mysql+pymysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['db']}"
    else:
        schema = db_config.get("db_schema", "public")
        uri = f"postgresql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['db']}"

    engine = create_engine(uri, pool_pre_ping=True)
    kpis = []
    charts = []

    try:
        with engine.connect() as conn:
            # 1. Total records across all tables
            total_rows = 0
            for table_name in tables:
                try:
                    q = f"SELECT COUNT(*) FROM {_quote_identifier(table_name, dialect)}"
                    result = conn.execute(text(q))
                    count = result.scalar() or 0
                    total_rows += count
                except Exception:
                    pass

            kpis.append({
                "label": "Total Records",
                "value": total_rows,
                "format": "number",
                "color": "#4f6cf7",
            })

            # 2. For each table with numeric columns, get key aggregates
            for table_name, table_info in list(tables.items())[:5]:
                num_cols = _numeric_columns(table_info)
                date_cols = _date_columns(table_info)

                for col in num_cols[:2]:  # Max 2 metrics per table
                    try:
                        # SUM of numeric column
                        q = f"SELECT SUM({_quote_identifier(col, dialect)}) FROM {_quote_identifier(table_name, dialect)} WHERE {_quote_identifier(col, dialect)} IS NOT NULL"
                        result = conn.execute(text(q))
                        total = result.scalar()
                        if total is not None:
                            # Build a human-readable label
                            label = f"{col.replace('_', ' ').title()}"
                            kpis.append({
                                "label": label,
                                "value": round(float(total), 2),
                                "table": table_name,
                                "format": "currency" if any(w in col.lower() for w in ("amount", "price", "revenue", "sales", "cost", "profit", "income")) else "number",
                                "color": "#22c55e" if len(kpis) % 3 == 0 else "#f59e0b" if len(kpis) % 3 == 1 else "#8b5cf6",
                            })
                    except Exception:
                        pass

                    # Try AVG too
                    try:
                        q = f"SELECT AVG({_quote_identifier(col, dialect)}) FROM {_quote_identifier(table_name, dialect)} WHERE {_quote_identifier(col, dialect)} IS NOT NULL"
                        result = conn.execute(text(q))
                        avg_val = result.scalar()
                        if avg_val is not None and len(kpis) < 8:
                            kpis.append({
                                "label": f"Avg {col.replace('_', ' ').title()}",
                                "value": round(float(avg_val), 2),
                                "table": table_name,
                                "format": "currency" if any(w in col.lower() for w in ("amount", "price", "revenue", "sales", "cost", "profit")) else "number",
                                "color": "#06b6d4",
                            })
                    except Exception:
                        pass

                # 3. If there's a date column, build a time-series chart
                if date_cols and num_cols:
                    try:
                        date_col = date_cols[0]
                        val_col = num_cols[0]
                        q = (
                            f"SELECT {_quote_identifier(date_col, dialect)}, "
                            f"SUM({_quote_identifier(val_col, dialect)}) as total "
                            f"FROM {_quote_identifier(table_name, dialect)} "
                            f"WHERE {_quote_identifier(val_col, dialect)} IS NOT NULL "
                            f"GROUP BY {_quote_identifier(date_col, dialect)} "
                            f"ORDER BY {_quote_identifier(date_col, dialect)} LIMIT 20"
                        )
                        result = conn.execute(text(q))
                        rows = result.fetchall()
                        if rows:
                            chart_data = [
                                {"name": str(r[0])[:10], "value": round(float(r[1] or 0), 2)}
                                for r in rows
                            ]
                            charts.append({
                                "title": f"{val_col.replace('_', ' ').title()} by {date_col.replace('_', ' ').title()}",
                                "data": chart_data,
                                "table": table_name,
                            })
                    except Exception:
                        pass

            # 4. Table summary
            summary = {
                "db_name": db_name,
                "table_count": len(tables),
                "total_rows": total_rows,
                "tables": [
                    {"name": t, "columns": len(info.get("columns", {}))}
                    for t, info in list(tables.items())[:10]
                ],
            }

    except Exception as exc:
        return {"ok": False, "error": str(exc), "kpis": [], "charts": [], "summary": {}}
    finally:
        try:
            engine.dispose()
        except Exception:
            pass

    return {
        "ok": True,
        "kpis": kpis[:8],
        "charts": charts[:3],
        "summary": summary,
    }
