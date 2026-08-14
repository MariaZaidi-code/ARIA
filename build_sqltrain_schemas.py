#!/usr/bin/env python3
"""Create the `aria_sqltrain` Postgres database with synthetic multi-domain
schemas used to build a variety-aware SQL finetuning dataset.

Domains (one Postgres schema each, deliberately different naming styles and
measures): retail, sales, hr, finance, health, logistics, media.

Usage:
    python build_sqltrain_schemas.py
"""

import random
from datetime import date, timedelta

import psycopg2

DB_NAME = "aria_sqltrain"
ADMIN_URI = "host=localhost dbname=postgres user=postgres password=12345"
URI = f"host=localhost dbname={DB_NAME} user=postgres password=12345"

TABLES = {
    "retail": [
        ("customers", "customer_id serial primary key, name text, email text, country text, city text, signup_date date"),
        ("products", "product_id serial primary key, name text, category text, price numeric(10,2), cost numeric(10,2)"),
        ("orders", "order_id serial primary key, customer_id int references retail.customers(customer_id), order_date date, status text, region text"),
        ("order_items", "item_id serial primary key, order_id int references retail.orders(order_id), product_id int references retail.products(product_id), quantity int, unit_price numeric(10,2)"),
    ],
    "sales": [
        ("accounts", "account_id serial primary key, name text, industry text, country text, plan text"),
        ("subscriptions", "subscription_id serial primary key, account_id int references sales.accounts(account_id), plan text, monthly_fee numeric(10,2), started_on date, status text"),
        ("invoices", "invoice_id serial primary key, account_id int references sales.accounts(account_id), issued_on date, amount numeric(12,2), paid boolean"),
        ("payments", "payment_id serial primary key, invoice_id int references sales.invoices(invoice_id), paid_on date, amount numeric(12,2), method text"),
    ],
    "hr": [
        ("departments", "department_id serial primary key, name text, location text"),
        ("employees", "employee_id serial primary key, department_id int references hr.departments(department_id), name text, role text, hire_date date, salary numeric(10,2)"),
        ("projects", "project_id serial primary key, name text, status text, budget numeric(12,2)"),
        ("assignments", "assignment_id serial primary key, employee_id int references hr.employees(employee_id), project_id int references hr.projects(project_id), started_on date, hours int"),
    ],
    "finance": [
        ("branches", "branch_id serial primary key, name text, city text"),
        ("customers", "customer_id serial primary key, name text, segment text"),
        ("accounts", "account_id serial primary key, customer_id int references finance.customers(customer_id), branch_id int references finance.branches(branch_id), type text, opened_on date, balance numeric(14,2)"),
        ("transactions", "txn_id serial primary key, account_id int references finance.accounts(account_id), txn_date date, amount numeric(12,2), kind text"),
    ],
    "health": [
        ("patients", "patient_id serial primary key, name text, gender text, birth_year int"),
        ("providers", "provider_id serial primary key, name text, specialty text"),
        ("visits", "visit_id serial primary key, patient_id int references health.patients(patient_id), provider_id int references health.providers(provider_id), visit_date date, duration_min int, charge numeric(10,2)"),
        ("diagnoses", "diagnosis_id serial primary key, visit_id int references health.visits(visit_id), code text, description text"),
    ],
    "logistics": [
        ("carriers", "carrier_id serial primary key, name text, mode text"),
        ("routes", "route_id serial primary key, origin text, destination text, distance_km numeric(10,2)"),
        ("shipments", "shipment_id serial primary key, carrier_id int references logistics.carriers(carrier_id), route_id int references logistics.routes(route_id), shipped_on date, weight_kg numeric(10,2), status text"),
    ],
    "media": [
        ("subscribers", "subscriber_id serial primary key, name text, country text, joined_on date"),
        ("shows", "show_id serial primary key, title text, genre text, release_year int"),
        ("watch_history", "watch_id serial primary key, subscriber_id int references media.subscribers(subscriber_id), show_id int references media.shows(show_id), watched_on date, duration_min int"),
    ],
}


def ddl_for(domain, name, cols):
    return f"CREATE TABLE {domain}.{name} ({cols});"


def make_rng(seed):
    return random.Random(seed)


def insert_data(cur, domain):
    rng = make_rng(hash(domain) % 10**9)
    start = date(2022, 1, 1)

    def rand_date(days):
        return start + timedelta(days=rng.randint(0, days))

    def pick(items):
        return rng.choice(items)

    countries = ["US", "UK", "DE", "FR", "IN", "BR", "CA", "AU"]

    if domain == "retail":
        cust_ids = []
        for i in range(60):
            cur.execute("INSERT INTO retail.customers(name,email,country,city,signup_date) VALUES(%s,%s,%s,%s,%s) RETURNING customer_id",
                        (f"Customer {i}", f"c{i}@ex.com", pick(countries), f"City {rng.randint(1,30)}", rand_date(1200)))
            cust_ids.append(cur.fetchone()[0])
        prod = []
        for i in range(40):
            cur.execute("INSERT INTO retail.products(name,category,price,cost) VALUES(%s,%s,%s,%s) RETURNING product_id",
                        (f"Product {i}", pick(["Beverages", "Dairy", "Produce", "Meat", "Snacks", "Household"]),
                         round(rng.uniform(2, 80), 2), round(rng.uniform(1, 50), 2)))
            prod.append(cur.fetchone()[0])
        cats = ["Beverages", "Dairy", "Produce", "Meat", "Snacks", "Household"]
        order_ids = []
        for i in range(500):
            cur.execute("INSERT INTO retail.orders(customer_id,order_date,status,region) VALUES(%s,%s,%s,%s) RETURNING order_id",
                        (pick(cust_ids), rand_date(900), pick(["Shipped", "Pending", "Delivered", "Cancelled"]), pick(countries)))
            order_ids.append(cur.fetchone()[0])
        for _ in range(1500):
            oid = pick(order_ids)
            pid = pick(prod)
            cur.execute("INSERT INTO retail.order_items(order_id,product_id,quantity,unit_price) VALUES(%s,%s,%s,%s)",
                        (oid, pid, rng.randint(1, 12), round(rng.uniform(2, 80), 2)))

    elif domain == "sales":
        accts = []
        for i in range(50):
            cur.execute("INSERT INTO sales.accounts(name,industry,country,plan) VALUES(%s,%s,%s,%s) RETURNING account_id",
                        (f"Acme {i}", pick(["Software", "Retail", "Finance", "Health"]), pick(countries), pick(["basic", "pro", "enterprise"])))
            accts.append(cur.fetchone()[0])
        for _ in range(120):
            cur.execute("INSERT INTO sales.subscriptions(account_id,plan,monthly_fee,started_on,status) VALUES(%s,%s,%s,%s,%s)",
                        (pick(accts), pick(["basic", "pro", "enterprise"]), round(rng.uniform(10, 500), 2), rand_date(1400), pick(["active", "churned", "trial"])))
        inv_ids = []
        for _ in range(800):
            cur.execute("INSERT INTO sales.invoices(account_id,issued_on,amount,paid) VALUES(%s,%s,%s,%s) RETURNING invoice_id",
                        (pick(accts), rand_date(1400), round(rng.uniform(50, 3000), 2), rng.random() > 0.25))
            inv_ids.append(cur.fetchone()[0])
        for _ in range(900):
            cur.execute("INSERT INTO sales.payments(invoice_id,paid_on,amount,method) VALUES(%s,%s,%s,%s)",
                        (pick(inv_ids), rand_date(1400), round(rng.uniform(50, 3000), 2), pick(["card", "bank", "paypal"])))

    elif domain == "hr":
        depts = []
        for i in range(12):
            cur.execute("INSERT INTO hr.departments(name,location) VALUES(%s,%s) RETURNING department_id",
                        (pick(["Engineering", "Sales", "Marketing", "Finance", "HR", "Support"]), f"Loc {rng.randint(1,5)}"))
            depts.append(cur.fetchone()[0])
        for i in range(120):
            cur.execute("INSERT INTO hr.employees(department_id,name,role,hire_date,salary) VALUES(%s,%s,%s,%s,%s)",
                        (pick(depts), f"Emp {i}", pick(["Engineer", "Manager", "Analyst", "Rep"]), rand_date(1800), round(rng.uniform(40, 220), 2) * 1000))
        projects = []
        for i in range(30):
            cur.execute("INSERT INTO hr.projects(name,status,budget) VALUES(%s,%s,%s) RETURNING project_id",
                        (f"Project {i}", pick(["active", "done", "planned", "on_hold"]), round(rng.uniform(20, 900), 2) * 1000))
            projects.append(cur.fetchone()[0])
        for _ in range(400):
            cur.execute("INSERT INTO hr.assignments(employee_id,project_id,started_on,hours) VALUES(%s,%s,%s,%s)",
                        (rng.randint(1, 120), pick(projects), rand_date(1400), rng.randint(4, 40)))

    elif domain == "finance":
        branches = []
        for i in range(15):
            cur.execute("INSERT INTO finance.branches(name,city) VALUES(%s,%s) RETURNING branch_id",
                        (f"Branch {i}", f"City {rng.randint(1,20)}"))
            branches.append(cur.fetchone()[0])
        for i in range(80):
            cur.execute("INSERT INTO finance.customers(name,segment) VALUES(%s,%s)",
                        (f"Client {i}", pick(["retail", "corporate", "premium"])))
        for i in range(150):
            cur.execute("INSERT INTO finance.accounts(customer_id,branch_id,type,opened_on,balance) VALUES(%s,%s,%s,%s,%s)",
                        (rng.randint(1, 80), pick(branches), pick(["checking", "savings", "loan"]), rand_date(1600), round(rng.uniform(0, 50000), 2)))
        for _ in range(3000):
            cur.execute("INSERT INTO finance.transactions(account_id,txn_date,amount,kind) VALUES(%s,%s,%s,%s)",
                        (rng.randint(1, 150), rand_date(1200), round(rng.uniform(-2000, 2000), 2), pick(["deposit", "withdrawal", "transfer", "fee"])))

    elif domain == "health":
        for i in range(200):
            cur.execute("INSERT INTO health.patients(name,gender,birth_year) VALUES(%s,%s,%s)",
                        (f"Patient {i}", pick(["M", "F"]), rng.randint(1940, 2015)))
        for i in range(25):
            cur.execute("INSERT INTO health.providers(name,specialty) VALUES(%s,%s)",
                        (f"Dr {i}", pick(["Cardiology", "Ortho", "Family", "Neuro", "Pediatrics"])))
        for _ in range(1200):
            cur.execute("INSERT INTO health.visits(patient_id,provider_id,visit_date,duration_min,charge) VALUES(%s,%s,%s,%s,%s)",
                        (rng.randint(1, 200), rng.randint(1, 25), rand_date(1100), rng.randint(5, 90), round(rng.uniform(50, 800), 2)))
        for _ in range(1500):
            cur.execute("INSERT INTO health.diagnoses(visit_id,code,description) VALUES(%s,%s,%s)",
                        (rng.randint(1, 1200), f"ICD{rng.randint(100,999)}", pick(["Hypertension", "Diabetes", "Flu", "Fracture"])))

    elif domain == "logistics":
        carriers = []
        for i in range(8):
            cur.execute("INSERT INTO logistics.carriers(name,mode) VALUES(%s,%s) RETURNING carrier_id",
                        (f"Carrier {i}", pick(["truck", "rail", "air", "sea"])))
            carriers.append(cur.fetchone()[0])
        routes = []
        for i in range(40):
            cur.execute("INSERT INTO logistics.routes(origin,destination,distance_km) VALUES(%s,%s,%s) RETURNING route_id",
                        (pick(countries), pick(countries), round(rng.uniform(100, 9000), 2)))
            routes.append(cur.fetchone()[0])
        for _ in range(600):
            cur.execute("INSERT INTO logistics.shipments(carrier_id,route_id,shipped_on,weight_kg,status) VALUES(%s,%s,%s,%s,%s)",
                        (pick(carriers), pick(routes), rand_date(1000), round(rng.uniform(1, 400), 2), pick(["in_transit", "delivered", "delayed"])))

    elif domain == "media":
        subs = []
        for i in range(100):
            cur.execute("INSERT INTO media.subscribers(name,country,joined_on) VALUES(%s,%s,%s) RETURNING subscriber_id",
                        (f"Sub {i}", pick(countries), rand_date(1500)))
            subs.append(cur.fetchone()[0])
        shows = []
        for i in range(80):
            cur.execute("INSERT INTO media.shows(title,genre,release_year) VALUES(%s,%s,%s) RETURNING show_id",
                        (f"Show {i}", pick(["Drama", "Comedy", "SciFi", "Reality"]), rng.randint(1990, 2024)))
            shows.append(cur.fetchone()[0])
        for _ in range(2000):
            cur.execute("INSERT INTO media.watch_history(subscriber_id,show_id,watched_on,duration_min) VALUES(%s,%s,%s,%s)",
                        (pick(subs), pick(shows), rand_date(1000), rng.randint(10, 120)))


def main():
    admin = psycopg2.connect(ADMIN_URI)
    admin.set_session(autocommit=True)
    with admin.cursor() as cur:
        cur.execute(f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'")
        if not cur.fetchone():
            cur.execute(f"CREATE DATABASE {DB_NAME}")
    admin.close()

    conn = psycopg2.connect(URI)
    conn.set_session(autocommit=True)
    with conn.cursor() as cur:
        for domain, tables in TABLES.items():
            cur.execute(f"DROP SCHEMA IF EXISTS {domain} CASCADE")
            cur.execute(f"CREATE SCHEMA {domain}")
            for name, cols in tables:
                cur.execute(ddl_for(domain, name, cols))
        for domain in TABLES:
            insert_data(cur, domain)
    conn.close()
    print(f"Created {DB_NAME} with domains: {', '.join(TABLES)}")


if __name__ == "__main__":
    main()