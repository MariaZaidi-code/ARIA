#!/usr/bin/env python3
"""ARIA Agent Validation Harness.

Validates each agent INDEPENDENTLY, `--iterations` times (default 4), across
every test database, so a regression in any single agent is caught immediately.

Agents under test (each exercised in isolation with a fresh instance):
  1. GoalAgent       - schema load, KPI alignment, join-path resolution,
                       SQL generation + validation, execution, preprocessing.
                       Provider-agnostic guards (bare SELECT *, PK/FK joins,
                       nested aggregates, unknown tables/columns) are exercised
                       implicitly by running real goals against the DB.
  2. InsightAgent    - column classification, KPIs, data-intelligent charts,
                       hypotheses (natural English ONLY), business story.
  3. PredictionAgent - forecast with the validity gate and a clean
                       "not_applicable" outcome for questions with no time axis.

Checks that must always hold (regression guardrails):
  * GoalAgent never raises, writes JSON-safe processed data, reports a
    preprocessing report, and never returns a bare `SELECT *` for an
    aggregating goal.
  * InsightAgent never raises and hypotheses/story contain no technical
    jargon tokens (std dev, z-score, grouped sum, etc.).
  * PredictionAgent never raises and returns either a forecast or a reason.

Usage:
  python validate_agents.py [--provider cloud|local] [--iterations 4]
                            [--db db1 db2 ...] [--quick]

Exits non-zero if any check fails on any iteration.
"""

import argparse
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from goal_agent import GoalAgent
from insight_agent import InsightAgent
from llm_provider import create_provider
from prediction.agent import PredictionAgent
import schema_agent

DB_URI = {
    "aria_fttest": "postgresql://postgres:12345@localhost:5432/aria_fttest",
    "market_flow": "postgresql://postgres:12345@localhost:5432/market_flow",
    "telecom_churn": "postgresql://postgres:12345@localhost:5432/telecom_churn",
    "soundstream": "postgresql://postgres:12345@localhost:5432/soundstream",
    "skylines": "postgresql://postgres:12345@localhost:5432/skylines",
    "estate_hub": "postgresql://postgres:12345@localhost:5432/estate_hub",
}

QUESTIONS = {
    "aria_fttest": "What is the average booking value per guest?",
    "market_flow": "What is the total revenue of delivered orders?",
    "telecom_churn": "How many subscribers churned in each city?",
    "soundstream": "What is the total play count per genre?",
    "skylines": "What is the average flight price by destination city?",
    "estate_hub": "What is the average sold price per city?",
}

# Technical jargon that must NEVER appear in natural-English hypotheses/stories.
FORBIDDEN_TOKENS = (
    "std dev", "z-score", "z score", "stddev", "2 std", "grouped sum",
    "beyond 2 standard", "descriptive kpi", "1.5", "walk-forward",
    "coefficient of variation", "standard deviation", "median", "dispersion",
)


def extract_mapping(db):
    """Extract (or reuse) the schema mapping file for a database."""
    path = BASE_DIR / f"schema_mapping_{db}_latest.json"
    if path.exists():
        return str(path)
    import types
    cfg = types.SimpleNamespace(
        host="localhost", port=5432, db=db, user="postgres", password="12345",
        db_type="postgresql", db_schema="public",
    )
    conn = schema_agent.get_connection(cfg)
    try:
        mapping = schema_agent.build_schema_mapping(conn, "public", db_type="postgresql")
        if not mapping.get("tables"):
            fallback = schema_agent.find_schema_with_tables(conn)
            mapping = schema_agent.build_schema_mapping(conn, fallback, db_type="postgresql")
        mapping["database"] = db
    finally:
        conn.close()
    path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    return str(path)


def _json_safe(obj):
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def _is_provider_outage(message):
    """A graceful empty result caused by the LLM provider being down or
    rate-limited is an infrastructure condition, not a system regression."""
    if not message:
        return False
    m = str(message).lower()
    return "rate-limited" in m or "unavailable" in m or "rate limit" in m


def check_goal(db, provider, report):
    """Exercise the GoalAgent independently; returns (ok, detail)."""
    t0 = time.time()
    schema_path = extract_mapping(db)
    agent = GoalAgent(
        schema_json_path=schema_path, db_uri=DB_URI[db],
        provider=create_provider(provider=provider), dialect="postgresql",
    )
    out = agent.process_goal(QUESTIONS[db], output_path=str(BASE_DIR / "tmp_va_goal.json"))
    processed = json.loads(Path(out).read_text(encoding="utf-8"))
    elapsed = time.time() - t0

    msg = processed.get("message")
    if _is_provider_outage(msg):
        report["goal"] = {"seconds": round(elapsed, 1), "outage": True,
                          "message": msg}
        return None, "PROVIDER OUTAGE (not a system failure)"

    fails = []
    sql = processed.get("sql_used") or ""
    if not sql:
        fails.append("sql_used is empty")
    if agent._goal_asks_for_aggregation(QUESTIONS[db]) and agent._find_bare_select_star(sql):
        fails.append(f"bare SELECT * returned for aggregating goal: {sql[:60]}")
    if processed.get("row_count") is None:
        fails.append("row_count missing")
    if not isinstance(processed.get("preprocessing"), dict):
        fails.append("preprocessing report missing")
    if not _json_safe(processed.get("data")):
        fails.append("data is not JSON-safe (Decimal/datetime leaked)")
    if not isinstance(processed.get("data"), list):
        fails.append("data is not a list")
    report["goal"] = {
        "seconds": round(elapsed, 1),
        "rows": processed.get("row_count"),
        "sql": sql[:70],
        "preprocessing_notes": len(processed.get("preprocessing", {}).get("notes", [])),
    }
    return (not fails), "; ".join(fails)


class _NoLLM:
    """Stub provider that always fails: forces every agent onto its
    deterministic path, which is the cloud/local parity guarantee and the
    fast, reproducible engine under test here. The real LLM polish path is
    exercised separately by the GoalAgent checks (which use the live
    provider) and by the running server."""

    def chat(self, *a, **k):
        raise RuntimeError("no-llm harness stub")

    def complete(self, *a, **k):
        raise RuntimeError("no-llm harness stub")


def check_insight(db, report):
    """Exercise the InsightAgent independently (deterministic engine)."""
    t0 = time.time()
    src = BASE_DIR / "tmp_va_goal.json"
    if not src.exists():
        return False, "no goal output to analyse"
    out = BASE_DIR / "tmp_va_ins.json"
    agent = InsightAgent(provider=create_provider(provider="local"))
    agent.llm = _NoLLM()
    agent.prescription.llm = _NoLLM()
    agent.analyze(str(src), str(out))
    ins = json.loads(out.read_text(encoding="utf-8"))
    elapsed = time.time() - t0

    fails = []
    if not isinstance(ins.get("dashboard"), list):
        fails.append("dashboard missing")
    if not isinstance(ins.get("kpis"), list):
        fails.append("kpis missing")
    hyps = ins.get("hypotheses") or []
    if not isinstance(hyps, list) or not hyps:
        fails.append("no hypotheses produced")
    for h in hyps:
        text = (h.get("hypothesis") or "").lower()
        for tok in FORBIDDEN_TOKENS:
            if tok in text:
                fails.append(f"technical jargon in hypothesis: '{tok}'")
    story = ins.get("business_story") or ""
    if not isinstance(story, str) or len(story) < 20:
        fails.append("business story missing/too short")
    else:
        low = story.lower()
        for tok in FORBIDDEN_TOKENS:
            if tok in low:
                fails.append(f"technical jargon in story: '{tok}'")
    report["insight"] = {
        "seconds": round(elapsed, 1),
        "charts": [c.get("chart_type") for c in ins.get("dashboard", [])
                   if c.get("chart_type") not in ("", "kpi_card")],
        "hypotheses": len(hyps),
        "story_len": len(story),
    }
    return (not fails), "; ".join(fails)


def check_prediction(db, report):
    """Exercise the PredictionAgent independently on the goal output."""
    t0 = time.time()
    src = BASE_DIR / "tmp_va_goal.json"
    if not src.exists():
        return False, "no goal output to forecast"
    processed = json.loads(src.read_text(encoding="utf-8"))
    pa = PredictionAgent()
    res = pa.forecast(processed)
    elapsed = time.time() - t0

    fails = []
    if not isinstance(res, dict):
        fails.append("forecast did not return a dict")
    elif "valid" not in res:
        fails.append("forecast missing 'valid' gate")
    elif res.get("valid") and not res.get("points"):
        fails.append("valid forecast has no points")
    elif not res.get("valid") and not res.get("reason"):
        fails.append("invalid forecast has no reason")
    report["prediction"] = {
        "seconds": round(elapsed, 1),
        "reliability": res.get("reliability"),
        "valid": res.get("valid"),
        "method": res.get("method"),
        "reason": (res.get("reason") or "")[:50],
    }
    return (not fails), "; ".join(fails)


def run_iteration(db, provider, iteration, quiet):
    reports = {}
    ok_goal, f_goal = check_goal(db, provider, reports)
    if ok_goal is None:
        # Provider outage: nothing meaningful to analyse/forecast on empty data.
        return {
            "goal": (None, f_goal),
            "insight": (None, "skipped (no data from provider outage)"),
            "prediction": (None, "skipped (no data from provider outage)"),
        }
    ok_ins, f_ins = check_insight(db, reports)
    ok_pred, f_pred = check_prediction(db, reports)
    results = {
        "goal": (ok_goal, f_goal),
        "insight": (ok_ins, f_ins),
        "prediction": (ok_pred, f_pred),
    }
    if not quiet:
        g = reports.get("goal", {})
        i = reports.get("insight", {})
        p = reports.get("prediction", {})
        if g.get("outage"):
            gmark = "SKIP"
        elif ok_goal:
            gmark = "PASS"
        else:
            gmark = "FAIL"
        print(
            f"  iter {iteration} | {db:13s} | "
            f"goal {gmark} "
            f"({g.get('rows')} rows, {g.get('seconds')}s) | "
            f"insight {'PASS' if ok_ins else 'FAIL'} "
            f"(charts={i.get('charts')}, hyps={i.get('hypotheses')}, {i.get('seconds')}s) | "
            f"prediction {'PASS' if ok_pred else 'FAIL'} "
            f"({p.get('reliability')}/{p.get('valid')})",
            flush=True,
        )
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="cloud", choices=["cloud", "local"])
    ap.add_argument("--iterations", type=int, default=4)
    ap.add_argument("--db", nargs="*", default=list(DB_URI))
    ap.add_argument("--quick", action="store_true", help="one DB, one iteration")
    args = ap.parse_args()

    dbs = args.db
    iters = 1 if args.quick else args.iterations
    if args.quick:
        dbs = dbs[:1]

    total_fail = 0
    total_skip = 0
    print(f"Provider: {args.provider} | DBs: {dbs} | iterations: {iters}\n", flush=True)
    for iteration in range(1, iters + 1):
        print(f"=== Iteration {iteration}/{iters} ===", flush=True)
        for db in dbs:
            try:
                results = run_iteration(db, args.provider, iteration, args.quick)
                for agent, (ok, fail) in results.items():
                    if ok is None:
                        # provider outage -> skip; not a system regression
                        total_skip += 1
                        print(f"    -- {db} {agent}: {fail}", flush=True)
                    elif not ok:
                        total_fail += 1
                        print(f"    !! {db} {agent}: {fail}", flush=True)
            except Exception as exc:
                total_fail += 1
                print(f"    !! {db} CRASHED: {type(exc).__name__}: {exc}", flush=True)
        print("", flush=True)

    print(
        f"RESULT: {total_fail} FAILURE(S), {total_skip} SKIP(S)"
        f"{' — ALL PASS' if total_fail == 0 else ''}",
        flush=True,
    )
    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    main()