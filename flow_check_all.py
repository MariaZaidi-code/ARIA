#!/usr/bin/env python3
"""End-to-end flow check: every created DB x provider (local, cloud).

connect -> extract_schema -> ask -> insight, timed per step, logged to a file.
Stuck calls are bounded by explicit HTTP timeouts; each case continues.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PORTS = [8000, 8001, 8002, 8010, 8080]


def resolve_base_url():
    override = os.getenv("ARIA_BASE_URL")
    if override:
        return override.rstrip("/")
    env_port = os.getenv("ARIA_PORT")
    if env_port:
        return f"http://127.0.0.1:{env_port}"
    for port in DEFAULT_PORTS:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/providers", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    return "http://127.0.0.1:8000"


BASE = resolve_base_url()

DBS = [
    ("aria_fttest", "What is the average booking value per guest? Show the top 10."),
    ("market_flow", "What is the total revenue from delivered purchases?"),
    ("telecom_churn", "How many subscribers churned in each city?"),
    ("soundstream", "What is the total play count per genre?"),
    ("skylines", "What is the total booking revenue per seat class?"),
    ("estate_hub", "What is the average sold price per city?"),
]
PROVIDERS = [sys.argv[1]] if len(sys.argv) > 1 else ["local", "cloud"]
TIMEOUTS = {"local": {"ask": 900, "insight": 900}, "cloud": {"ask": 180, "insight": 240}}


def api(path, body=None, token=None, timeout=60, method="POST"):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(r"C:\Users\Go\AppData\Local\Temp\opencode\flow_check_all.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    login = api("/api/auth/login", {"username": "admin", "password": "admin"}, timeout=30)
    token = login["token"]
    report = {}
    for provider in PROVIDERS:
        report[provider] = {}
        for db, question in DBS:
            log(f"=== {provider} | {db} ===")
            case = {}
            steps = [("connect", 60), ("extract", 120), ("ask", TIMEOUTS[provider]["ask"]),
                     ("insight", TIMEOUTS[provider]["insight"])]
            failed = None
            for step, to in steps:
                try:
                    if step == "connect":
                        t0 = time.time()
                        result = api("/api/connect", {"provider": provider, "source_type": "relational",
                                                      "db_type": "postgresql", "host": "localhost",
                                                      "port": 5432, "db": db, "user": "postgres",
                                                      "password": "12345", "db_schema": "public"},
                                     token=token, timeout=to)
                        case["connect_s"] = round(time.time() - t0, 1)
                    elif step == "extract":
                        t0 = time.time()
                        ex = api("/api/extract_schema", None, token=token, timeout=to)
                        case["extract_s"] = round(time.time() - t0, 1)
                        case["tables"] = ex.get("tables") if ex else None
                    elif step == "ask":
                        t0 = time.time()
                        ask = api("/api/ask", {"goal": question}, token=token, timeout=to)
                        case["ask_s"] = round(time.time() - t0, 1)
                        if ask is None:
                            raise RuntimeError("ask returned null")
                        case["sql"] = ask.get("sql_used")
                        case["rows"] = ask.get("row_count")
                        case["msg"] = ask.get("message")
                        case["ask_ok"] = not (ask.get("sql_used", "").startswith("SELECT * FROM"))
                    elif step == "insight":
                        t0 = time.time()
                        ins = api("/api/insight", None, token=token, timeout=to)
                        case["insight_s"] = round(time.time() - t0, 1)
                        if ins is None:
                            raise RuntimeError("insight returned null")
                        i = ins.get("insights", {}) or {}
                        case["kpis"] = len(i.get("kpis", []))
                        case["trends"] = len(i.get("trends", []))
                        case["anomalies"] = len(i.get("anomalies", []))
                        case["hypotheses"] = len(i.get("hypotheses", []))
                        case["dashboard"] = len(i.get("dashboard", []))
                        case["pred_valid"] = bool((i.get("predictions") or {}).get("valid"))
                        case["presc"] = len((i.get("prescriptions") or {}).get("actions", []))
                        case["story_len"] = len(i.get("business_story", ""))
                        case["insight_warning"] = i.get("warning")
                except Exception as exc:
                    failed = f"{step}: {exc}"
                    case["error"] = failed
                    log(f"  ERROR at {step}: {exc}")
                    break
            if not failed:
                log(f"  ask={case.get('ask_s')}s rows={case.get('rows')} ask_ok={case.get('ask_ok')} | "
                    f"ins={case.get('insight_s')}s kpis={case.get('kpis')} trends={case.get('trends')} "
                    f"anom={case.get('anomalies')} pred={case.get('pred_valid')} presc={case.get('presc')} "
                    f"warn={case.get('insight_warning')}")
            report[provider][db] = case

    with open(r"C:\Users\Go\Desktop\ARIA\flow_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    log("DONE")


if __name__ == "__main__":
    main()