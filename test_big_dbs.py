#!/usr/bin/env python3
"""Run the fine-tuned SQL model through the Goal Agent on the 5 big test DBs."""

import json
import sys
import time
import types

import psycopg2
from goal_agent import GoalAgent
from llm_provider import create_provider

import schema_agent

DB_URI = {
    "market_flow": "postgresql://postgres:12345@localhost:5432/market_flow",
    "telecom_churn": "postgresql://postgres:12345@localhost:5432/telecom_churn",
    "soundstream": "postgresql://postgres:12345@localhost:5432/soundstream",
    "skylines": "postgresql://postgres:12345@localhost:5432/skylines",
    "estate_hub": "postgresql://postgres:12345@localhost:5432/estate_hub",
}

QUESTIONS = {
    "market_flow": [
        "What is the total revenue from delivered purchases?",
        "Which product category has the highest total sales? Show the top 5.",
        "What is the monthly sales trend in 2024?",
        "Who are the top 10 customers by total spending?",
    ],
    "telecom_churn": [
        "How many subscribers churned in each city?",
        "What is the average invoice amount per plan?",
        "What is the total call duration per call type?",
        "Which city has the highest number of subscribers?",
    ],
    "soundstream": [
        "How many plays were recorded in 2024?",
        "What is the total play count per genre?",
        "What are the top 5 most played tracks?",
        "What is the average seconds listened per listener plan?",
    ],
    "skylines": [
        "What is the total booking revenue per seat class?",
        "What is the average booking price per loyalty tier?",
        "How many flights depart from each city?",
        "How many bookings were made in 2024?",
    ],
    "estate_hub": [
        "What is the average sold price per city?",
        "How many listings are currently active?",
        "What is the total sales volume by property type?",
        "Which agent has the most sold listings? Show the top 5.",
    ],
}


def extract_mapping(db, schema_guess="public"):
    cfg = types.SimpleNamespace(
        host="localhost", port=5432, db=db, user="postgres", password="12345",
        db_type="postgresql", db_schema=schema_guess,
    )
    conn = schema_agent.get_connection(cfg)
    try:
        mapping = schema_agent.build_schema_mapping(conn, schema_guess, db_type="postgresql")
        if not mapping.get("tables"):
            fallback = schema_agent.find_schema_with_tables(conn)
            mapping = schema_agent.build_schema_mapping(conn, fallback, db_type="postgresql")
        mapping["database"] = db
    finally:
        conn.close()
    path = f"schema_mapping_{db}_latest.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, indent=2)
    return path


def run_question(agent, goal):
    t0 = time.time()
    out = agent.process_goal(goal, output_path="processed_data_test.json")
    elapsed = time.time() - t0
    with open(out, "r", encoding="utf-8") as fh:
        processed = json.load(fh)
    sql = processed.get("sql_used", "")
    return {
        "goal": goal,
        "seconds": round(elapsed, 1),
        "sql_used": sql,
        "row_count": processed.get("row_count"),
        "message": processed.get("message"),
        "template_fallback": sql.startswith("SELECT * FROM"),
    }


def main():
    report = {}
    for db, questions in QUESTIONS.items():
        print(f"\n=== {db} ===", flush=True)
        schema_path = extract_mapping(db)
        agent = GoalAgent(schema_json_path=schema_path, db_uri=DB_URI[db], provider=create_provider(provider="local"), dialect="postgresql")
        rows = []
        for q in questions:
            try:
                r = run_question(agent, q)
            except Exception as exc:
                r = {"goal": q, "error": str(exc)[:200]}
            rows.append(r)
            ok = "FAIL" if r.get("error") or r.get("template_fallback") else ("OK" if (r.get("row_count") or 0) >= 1 else "EMPTY")
            print(f"  [{ok}] {r['goal'][:60]} | {r.get('seconds', 0)}s | rows={r.get('row_count')}", flush=True)
        report[db] = rows

    with open("test_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print("\nSaved test_report.json", flush=True)


if __name__ == "__main__":
    main()