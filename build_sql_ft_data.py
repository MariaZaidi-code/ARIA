#!/usr/bin/env python3
"""Generate a variety-aware SQL finetuning dataset (verified against the DB).

Covers northwind (real), the aria_test library (real) and the 7 synthetic
sqltrain domains. Every (question -> SQL) pair is executed against the live
database and kept ONLY if it returns rows, so the model never learns a broken
query. The instruction mirrors the Goal Agent's exact SQL prompt (Task /
User goal / KPIs / Dimensions / Schema DDL / join path / SQL) so training and
inference line up.

Usage:
    python build_sql_ft_data.py --out sql_training_data.jsonl
"""

import argparse
import json
import logging
from pathlib import Path

from sqlalchemy import text

from core.config import BASE_DIR
import schema_agent
import psycopg2
from goal_agent import GoalAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sqltrain")

SQLTRAIN_URI = "postgresql://postgres:12345@localhost:5432/aria_sqltrain"
LIBRARY_URI = "postgresql://postgres:12345@localhost:5432/aria_test"

CONFIGS = {
    "northwind": {
        "uri": "postgresql://postgres:12345@localhost:5432/northwind",
        "schema_file": "schema_mapping_northwind_latest.json",
        "schema_name": "public",
        "join_path": ["orders", "order_details", "customers", "products", "categories"],
        "amount": ("SUM(order_details.unit_price * order_details.quantity)", "revenue"),
        "amount_name": "revenue",
        "orders_count": ("COUNT(DISTINCT orders.order_id)", "order_count"),
        "aov": ("SUM(order_details.unit_price * order_details.quantity) / NULLIF(COUNT(DISTINCT orders.order_id), 0)", "average_order_value"),
        "qty": ("SUM(order_details.quantity)", "units_sold"),
        "date_col": "orders.order_date",
        "dim2": "categories.category_name",
        "dim2_label": "category",
        "entity": ("customers.company_name", "customer"),
        "entity2": ("products.product_name", "product"),
        "country": "customers.country",
        "status": "orders.status",
        "from_full": (
            "FROM order_details JOIN orders ON orders.order_id = order_details.order_id "
            "JOIN customers ON customers.customer_id = orders.customer_id "
            "JOIN products ON products.product_id = order_details.product_id "
            "JOIN categories ON categories.category_id = products.category_id"
        ),
    },
    "library": {
        "uri": LIBRARY_URI,
        "schema_file": "schema_mapping_sqltrain_library.json",
        "schema_name": "public",
        "join_path": ["loans", "books", "authors"],
        "amount": ("SUM(books.price)", "loan_value"),
        "amount_name": "loan value",
        "orders_count": ("COUNT(DISTINCT loans.loan_id)", "loan_count"),
        "qty": ("COUNT(loans.loan_id)", "loans_made"),
        "date_col": "loans.loan_date",
        "dim2": "books.title",
        "dim2_label": "book",
        "entity": ("books.title", "book"),
        "entity2": ("authors.author_name", "author"),
        "country": "authors.nationality",
        "status": "books.title",
        "from_full": (
            "FROM loans JOIN books ON books.book_id = loans.book_id "
            "JOIN authors ON authors.author_id = books.author_id"
        ),
    },
}

_DOMAIN_CONFIGS = {
    "retail": {
        "schema_file": "schema_mapping_sqltrain_retail.json",
        "join_path": ["orders", "order_items", "customers", "products"],
        "amount": ("SUM(order_items.unit_price * order_items.quantity)", "revenue"),
        "amount_name": "revenue",
        "orders_count": ("COUNT(DISTINCT orders.order_id)", "order_count"),
        "qty": ("SUM(order_items.quantity)", "units_sold"),
        "date_col": "orders.order_date",
        "dim2": "products.category",
        "dim2_label": "category",
        "entity": ("customers.name", "customer"),
        "entity2": ("products.name", "product"),
        "country": "customers.country",
        "status": "orders.status",
        "from_full": (
            "FROM order_items JOIN orders ON orders.order_id = order_items.order_id "
            "JOIN customers ON customers.customer_id = orders.customer_id "
            "JOIN products ON products.product_id = order_items.product_id"
        ),
    },
    "sales": {
        "schema_file": "schema_mapping_sqltrain_sales.json",
        "join_path": ["invoices", "accounts", "subscriptions"],
        "amount": ("SUM(invoices.amount)", "billing"),
        "amount_name": "billing",
        "orders_count": ("COUNT(DISTINCT invoices.invoice_id)", "invoice_count"),
        "date_col": "invoices.issued_on",
        "dim2": "accounts.plan",
        "dim2_label": "plan",
        "entity": ("accounts.name", "account"),
        "entity2": ("accounts.industry", "industry"),
        "country": "accounts.country",
        "status": "invoices.paid",
        "from_full": (
            "FROM invoices JOIN accounts ON accounts.account_id = invoices.account_id"
        ),
    },
    "hr": {
        "schema_file": "schema_mapping_sqltrain_hr.json",
        "join_path": ["employees", "departments", "assignments", "projects"],
        "amount": ("SUM(employees.salary)", "payroll"),
        "amount_name": "payroll",
        "orders_count": ("COUNT(DISTINCT employees.employee_id)", "employee_count"),
        "qty": ("SUM(assignments.hours)", "hours_worked"),
        "date_col": "employees.hire_date",
        "dim2": "departments.name",
        "dim2_label": "department",
        "entity": ("departments.name", "department"),
        "entity2": ("projects.name", "project"),
        "country": "departments.location",
        "status": "projects.status",
        "from_full": (
            "FROM employees JOIN departments ON departments.department_id = employees.department_id "
            "JOIN assignments ON assignments.employee_id = employees.employee_id "
            "JOIN projects ON projects.project_id = assignments.project_id"
        ),
    },
    "finance": {
        "schema_file": "schema_mapping_sqltrain_finance.json",
        "join_path": ["transactions", "accounts", "customers", "branches"],
        "amount": ("SUM(transactions.amount)", "total_flow"),
        "amount_name": "total transaction flow",
        "orders_count": ("COUNT(DISTINCT transactions.txn_id)", "transaction_count"),
        "date_col": "transactions.txn_date",
        "dim2": "transactions.kind",
        "dim2_label": "transaction type",
        "entity": ("customers.name", "customer"),
        "entity2": ("accounts.type", "account type"),
        "country": "branches.city",
        "status": "accounts.type",
        "from_full": (
            "FROM transactions JOIN accounts ON accounts.account_id = transactions.account_id "
            "JOIN customers ON customers.customer_id = accounts.customer_id "
            "JOIN branches ON branches.branch_id = accounts.branch_id"
        ),
    },
    "health": {
        "schema_file": "schema_mapping_sqltrain_health.json",
        "join_path": ["visits", "patients", "providers"],
        "amount": ("SUM(visits.charge)", "charges"),
        "amount_name": "patient charges",
        "orders_count": ("COUNT(DISTINCT visits.visit_id)", "visit_count"),
        "qty": ("SUM(visits.duration_min)", "minutes"),
        "date_col": "visits.visit_date",
        "dim2": "providers.specialty",
        "dim2_label": "specialty",
        "entity": ("patients.name", "patient"),
        "entity2": ("providers.name", "provider"),
        "country": "patients.birth_year",
        "status": "providers.specialty",
        "from_full": (
            "FROM visits JOIN patients ON patients.patient_id = visits.patient_id "
            "JOIN providers ON providers.provider_id = visits.provider_id"
        ),
    },
    "logistics": {
        "schema_file": "schema_mapping_sqltrain_logistics.json",
        "join_path": ["shipments", "carriers", "routes"],
        "amount": ("SUM(shipments.weight_kg)", "tonnage"),
        "amount_name": "tonnage",
        "orders_count": ("COUNT(DISTINCT shipments.shipment_id)", "shipment_count"),
        "date_col": "shipments.shipped_on",
        "dim2": "carriers.mode",
        "dim2_label": "carrier mode",
        "entity": ("carriers.name", "carrier"),
        "entity2": ("routes.origin", "origin"),
        "country": "routes.destination",
        "status": "shipments.status",
        "from_full": (
            "FROM shipments JOIN carriers ON carriers.carrier_id = shipments.carrier_id "
            "JOIN routes ON routes.route_id = shipments.route_id"
        ),
    },
    "media": {
        "schema_file": "schema_mapping_sqltrain_media.json",
        "join_path": ["watch_history", "subscribers", "shows"],
        "amount": ("SUM(watch_history.duration_min)", "watch_minutes"),
        "amount_name": "watch time",
        "orders_count": ("COUNT(DISTINCT watch_history.watch_id)", "watch_count"),
        "date_col": "watch_history.watched_on",
        "dim2": "shows.genre",
        "dim2_label": "genre",
        "entity": ("subscribers.name", "subscriber"),
        "entity2": ("shows.title", "show"),
        "country": "subscribers.country",
        "status": "shows.genre",
        "from_full": (
            "FROM watch_history JOIN subscribers ON subscribers.subscriber_id = watch_history.subscriber_id "
            "JOIN shows ON shows.show_id = watch_history.show_id"
        ),
    },
}

for name, cfg in _DOMAIN_CONFIGS.items():
    cfg["uri"] = SQLTRAIN_URI
    cfg["schema_name"] = name
    CONFIGS[name] = cfg


def build_prompt(question, ddl, join_path, kpi_desc, dims):
    return f"""### Task
Generate a single postgresql query that answers the user's business goal.
User goal: {question}
Aligned KPIs: {kpi_desc}
Dimensions: {dims}

### Database Schema
The query will run on a database with the following schema:
{ddl}
Preferred starting tables (inspect these first, but you may use any table
needed to answer the goal, joining via the FOREIGN KEY relationships above):
{join_path}
### SQL
Output only the final SQL statement. No explanations, no markdown, nothing after it.
"""


def _m(cfg, key, default=None):
    return cfg.get(key, default)


def templates(cfg):
    """Yield (question, sql, kpi_desc, dims) pairs for a domain config."""
    measure, m_alias = cfg["amount"]
    amount_name = cfg["amount_name"]
    date_col = cfg["date_col"]
    ff = cfg["from_full"]
    dim2 = cfg["dim2"]
    dim2_label = cfg["dim2_label"]
    entity_label, entity_name = cfg["entity"]
    orders_count, oc_alias = cfg["orders_count"]

    out = []

    def add(q, sql, kpi, dims):
        out.append((q, sql, kpi, dims))

    add(f"What is the total {amount_name}?",
        f"SELECT {measure} AS {m_alias} {ff};",
        f"sum({amount_name})", "none")

    add(f"Show me the total {amount_name}.",
        f"SELECT {measure} AS {m_alias} {ff};",
        f"sum({amount_name})", "none")

    add(f"How many orders have been placed in total?",
        f"SELECT {orders_count} AS {oc_alias} {ff};",
        "count(orders)", "none")

    add(f"Which {dim2_label} drives the most {amount_name}? Show the top 5.",
        f"SELECT {dim2}, {measure} AS {m_alias} {ff} GROUP BY {dim2} ORDER BY {m_alias} DESC NULLS LAST LIMIT 5;",
        f"sum({amount_name})", dim2_label)

    add(f"Show {amount_name} by {dim2_label}.",
        f"SELECT {dim2}, {measure} AS {m_alias} {ff} GROUP BY {dim2} ORDER BY {m_alias} DESC NULLS LAST;",
        f"sum({amount_name})", dim2_label)

    add(f"What is the monthly {amount_name} trend?",
        f"SELECT date_trunc('month', {date_col})::date AS month, {measure} AS {m_alias} {ff} GROUP BY 1 ORDER BY 1;",
        f"sum({amount_name})", "month")

    add(f"Show {amount_name} by year.",
        f"SELECT EXTRACT(YEAR FROM {date_col})::int AS year, {measure} AS {m_alias} {ff} GROUP BY 1 ORDER BY 1;",
        f"sum({amount_name})", "year")

    add(f"Who are the top {entity_name}s by {amount_name}? Show the top 10.",
        f"SELECT {entity_label}, {measure} AS {m_alias} {ff} GROUP BY {entity_label} ORDER BY {m_alias} DESC NULLS LAST LIMIT 10;",
        f"sum({amount_name})", entity_name)

    add(f"Show {amount_name} per {entity_name}.",
        f"SELECT {entity_label}, {measure} AS {m_alias} {ff} GROUP BY {entity_label} ORDER BY {m_alias} DESC NULLS LAST;",
        f"sum({amount_name})", entity_name)

    add(f"Which {entity_name} has the most orders? Show the top 10.",
        f"SELECT {entity_label}, {orders_count} AS {oc_alias} {ff} GROUP BY {entity_label} ORDER BY {oc_alias} DESC NULLS LAST LIMIT 10;",
        "count(orders)", entity_name)

    add(f"Show the number of orders per {entity_name}.",
        f"SELECT {entity_label}, {orders_count} AS {oc_alias} {ff} GROUP BY {entity_label} ORDER BY {oc_alias} DESC NULLS LAST;",
        "count(orders)", entity_name)

    add(f"What is the {amount_name} share by {dim2_label}?",
        f"SELECT {dim2}, {measure} AS {m_alias}, ROUND((100.0 * {measure} / NULLIF(SUM({measure}) OVER (), 0))::numeric, 2) AS share_pct {ff} GROUP BY {dim2} ORDER BY {m_alias} DESC NULLS LAST;",
        f"sum({amount_name})", f"{dim2_label}, share")

    add(f"How many distinct {entity_name}s have ordered?",
        f"SELECT COUNT(DISTINCT {entity_label}) AS {entity_name}_count {ff};",
        f"count(distinct {entity_name})", "none")

    add(f"Show {amount_name} by {dim2_label} and month.",
        f"SELECT {dim2}, date_trunc('month', {date_col})::date AS month, {measure} AS {m_alias} {ff} GROUP BY 1, 2 ORDER BY 2, {m_alias} DESC NULLS LAST;",
        f"sum({amount_name})", f"{dim2_label}, month")

    if "aov" in cfg:
        aov, aov_alias = cfg["aov"]
        add(f"What is the average order value per {entity_name}? Show the top 10.",
            f"SELECT {entity_label}, {aov} AS {aov_alias} {ff} GROUP BY {entity_label} ORDER BY {aov_alias} DESC NULLS LAST LIMIT 10;",
            "average order value", entity_name)

    if "qty" in cfg:
        qty, qty_alias = cfg["qty"]
        add(f"Show total {amount_name} by {dim2_label} for the largest category.",
            f"SELECT {dim2}, {measure} AS {m_alias} {ff} GROUP BY {dim2} ORDER BY {m_alias} DESC NULLS LAST LIMIT 1;",
            f"sum({amount_name})", dim2_label)
        add(f"What is the {qty_alias.replace('_', ' ')}?",
            f"SELECT {qty} AS {qty_alias} {ff};",
            f"sum({qty_alias.replace('_', ' ')})", "none")

    if "entity2" in cfg:
        e2_label, e2_name = cfg["entity2"]
        add(f"Which {e2_name} brings in the most {amount_name}? Show the top 5.",
            f"SELECT {e2_label}, {measure} AS {m_alias} {ff} GROUP BY {e2_label} ORDER BY {m_alias} DESC NULLS LAST LIMIT 5;",
            f"sum({amount_name})", e2_name)
        add(f"Show {amount_name} per {e2_name}.",
            f"SELECT {e2_label}, {measure} AS {m_alias} {ff} GROUP BY {e2_label} ORDER BY {m_alias} DESC NULLS LAST;",
            f"sum({amount_name})", e2_name)

    if "country" in cfg:
        country = cfg["country"]
        add(f"How many {entity_name}s are there per {country.split('.')[-1]}?",
            f"SELECT {country}, COUNT(DISTINCT {entity_label}) AS {entity_name}_count {ff} GROUP BY {country} ORDER BY {entity_name}_count DESC NULLS LAST;",
            f"count(distinct {entity_name})", country.split(".")[-1])

    if "status" in cfg:
        status = cfg["status"]
        st_label = status.split(".")[-1]
        add(f"Show the count by {st_label}.",
            f"SELECT {status}, {orders_count} AS {oc_alias} {ff} GROUP BY {status} ORDER BY {oc_alias} DESC NULLS LAST;",
            "count(orders)", st_label)
        add(f"Show {amount_name} by {st_label}.",
            f"SELECT {status}, {measure} AS {m_alias} {ff} GROUP BY {status} ORDER BY {m_alias} DESC NULLS LAST;",
            f"sum({amount_name})", st_label)

    add(f"Which {dim2_label} has the most orders? Show the top 5.",
        f"SELECT {dim2}, {orders_count} AS {oc_alias} {ff} GROUP BY {dim2} ORDER BY {oc_alias} DESC NULLS LAST LIMIT 5;",
        "count(orders)", dim2_label)

    add(f"Show the top 3 {dim2_label}s by {amount_name}.",
        f"SELECT {dim2}, {measure} AS {m_alias} {ff} GROUP BY {dim2} ORDER BY {m_alias} DESC NULLS LAST LIMIT 3;",
        f"sum({amount_name})", dim2_label)

    return out


def load_or_build_schema(domain, cfg):
    schema_file = Path(cfg["schema_file"])
    if not schema_file.exists():
        logger.info("Building schema mapping for %s ...", domain)
        db = cfg["uri"].split("/")[-1]
        db_type = "postgresql"
        with psycopg2.connect(
            host="localhost", dbname=db, user="postgres", password="12345"
        ) as conn:
            schema_name = "public" if domain in ("northwind", "library") else domain
            mapping = schema_agent.build_schema_mapping(conn, schema_name, db_type=db_type)
        with open(schema_file, "w", encoding="utf-8") as fh:
            json.dump(mapping, fh, indent=2)
        logger.info("Wrote %s", schema_file)
    return str(schema_file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="sql_training_data.jsonl")
    args = parser.parse_args()

    rows = []
    stats = {}
    for domain, cfg in CONFIGS.items():
        schema_path = load_or_build_schema(domain, cfg)
        agent = GoalAgent(schema_json_path=schema_path, db_uri=cfg["uri"])
        ddl = agent._build_schema_ddl(cfg["join_path"], full=False)
        pairs = templates(cfg)
        kept = 0
        for q, sql, kpi, dims in pairs:
            prompt = build_prompt(q, ddl, ", ".join(cfg["join_path"]), kpi, dims)
            try:
                with agent.engine.connect() as conn:
                    conn.execute(text(f"SET search_path TO {cfg.get('schema_name', 'public')}, public"))
                    res = conn.execute(text(sql.replace('"', "")))
            except Exception as exc:
                logger.warning("SKIP %s/%s: %s", domain, q[:40], exc)
                continue
            if not res.returns_rows or res.first() is None:
                logger.warning("SKIP %s/%s: no rows returned", domain, q[:40])
                continue
            rows.append({"instruction": prompt, "output": sql.strip()})
            kept += 1
        stats[domain] = kept
        logger.info("%s: kept %d/%d", domain, kept, len(pairs))

    with open(args.out, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    logger.info("Wrote %d verified pairs to %s", len(rows), args.out)
    for d, c in stats.items():
        print(f"  {d}: {c}")


if __name__ == "__main__":
    main()