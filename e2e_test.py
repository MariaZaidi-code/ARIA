"""End-to-end test: 1-table CSV treated as DB, full Decision Center flow."""
import sys, os, json, tempfile, traceback, time
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from fastapi.testclient import TestClient

client = TestClient(app)
PASS = 0
FAIL = 0
RESULTS = []

def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        RESULTS.append(f"  PASS  {name}")
    except Exception as e:
        FAIL += 1
        RESULTS.append(f"  FAIL  {name}: {e}")
        traceback.print_exc()

# SETUP
print("=" * 60)
print("ARIA E2E TEST - 1-table CSV as database")
print("=" * 60)

UNAME = f"e2e_run_{int(time.time())}"
r = client.post("/api/auth/register", json={"username": UNAME, "password": "Test1234!"})
assert r.status_code == 200, f"Auth failed: {r.status_code} {r.text[:200]}"
TOKEN = client.cookies.get("aria_token") or client.cookies.get("__Host-aria_token") or ""
assert TOKEN, f"Auth cookie missing after register: {r.json()} cookies={dict(client.cookies)}"
H = {"Authorization": f"Bearer {TOKEN}"}

# 24-month sales CSV: trends, seasonality, category/region breakdowns
import random
random.seed(42)
rows = ["month,revenue,orders,customers,avg_order_value,returns,category,region"]
for m in range(1, 25):
    month = f"2025-{m:02d}-01"
    base = 50000 + (m * 800) - (3000 if m > 12 else 0)
    rev = max(5000, int(base + random.gauss(0, 3000)))
    orders = max(10, int(rev / 80 + random.gauss(0, 10)))
    customers = max(5, int(orders * 0.6 + random.gauss(0, 5)))
    aov = round(rev / max(orders, 1), 2)
    rets = max(0, int(orders * 0.08 + random.gauss(0, 2)))
    cat = "Electronics" if m % 3 == 0 else ("Clothing" if m % 3 == 1 else "Food")
    reg = "North" if m % 4 in (0, 1) else ("South" if m % 4 == 2 else "East")
    rows.append(f"{month},{rev},{orders},{customers},{aov},{rets},{cat},{reg}")

csv_content = "\n".join(rows)
f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
f.write(csv_content)
f.close()
with open(f.name, "rb") as fp:
    r = client.post("/api/connect_file", files={"file": ("sales.csv", fp, "text/csv")}, headers=H)
    conn = r.json()
assert conn.get("ok"), f"Connect failed: {conn}"
TABLE = conn.get("table", "sales")
print(f"\nConnected CSV as table: {TABLE} ({conn.get('rows', '?')} rows, {len(conn.get('columns', []))} columns)")
os.unlink(f.name)

# ==========================================================
# 1. DASHBOARD
# ==========================================================
print("\n--- 1. DASHBOARD ---")

def test_preview():
    r = client.post("/api/data/preview", json={"table": TABLE, "limit": 5}, headers=H)
    d = r.json()
    rows_data = d.get("rows") or d.get("data") or []
    assert len(rows_data) > 0, f"No data from preview: {list(d.keys())}"

def test_dashboard_kpis():
    r = client.get("/api/dashboard/config", headers=H)
    d = r.json()
    assert d.get("ok"), f"Dashboard config failed: {str(d)[:200]}"
    cfg = d.get("config", d)
    metrics = cfg.get("metrics", cfg.get("kpis", []))
    assert len(metrics) >= 1, f"Expected >=1 KPI, got {len(metrics)} (config keys: {list(cfg.keys())})"
    for m in metrics[:3]:
        val = m.get("value") or m.get("rawValue") or m.get("current")
        assert val is not None, f"KPI has no value: {m.get('label', m.get('id', '?'))}"

def test_dashboard_charts():
    r = client.get("/api/dashboard/config", headers=H)
    d = r.json()
    cfg = d.get("config", d)
    charts = cfg.get("visualizations", cfg.get("charts", []))
    assert len(charts) >= 2, f"Expected >=2 charts, got {len(charts)}"

test("Preview returns rows", test_preview)
test("Dashboard KPIs real", test_dashboard_kpis)
test("Dashboard >=2 charts", test_dashboard_charts)

# ==========================================================
# 2. DECISION CENTER - OVERVIEW
# ==========================================================
print("\n--- 2. DECISION CENTER OVERVIEW ---")

def test_overview_ok():
    r = client.get("/api/decision-center/overview", headers=H)
    d = r.json()
    assert d.get("ok"), f"Overview failed: {d}"
    assert d.get("aria_view"), "No aria_view"

def test_overview_has_levers():
    r = client.get("/api/decision-center/overview", headers=H)
    d = r.json()
    prios = d.get("priorities", [])
    opps = d.get("opportunities", [])
    total = len(prios) + len(opps)
    assert total > 0, "No priorities or opportunities found"
    print(f"    Found {len(prios)} priorities + {len(opps)} opportunities")

test("Overview ok", test_overview_ok)
test("Overview has levers", test_overview_has_levers)

# ==========================================================
# 3. RECOMMENDATIONS
# ==========================================================
print("\n--- 3. RECOMMENDATIONS ---")

def test_recommendations():
    r = client.get("/api/decision-center/recommendations?top_n=5", headers=H)
    d = r.json()
    assert d.get("ok"), f"Recommendations failed: {d}"
    recs = d.get("prescriptions", [])
    status = d.get("status", "")
    if status == "no_recommendation":
        assert d.get("reason"), "no_recommendation without reason"
        print(f"    Honest no_recommendation: {d.get('reason', '')[:80]}")
    else:
        assert len(recs) > 0, f"Expected prescriptions but got none"
        print(f"    Found {len(recs)} prescriptions")

test("Recommendations honest", test_recommendations)

# ==========================================================
# 4. DECISION CREATE + PERSISTENCE
# ==========================================================
print("\n--- 4. DECISION CREATE + PERSIST ---")

DECISION_ID = None

def test_create_from_analytics():
    global DECISION_ID
    r = client.post("/api/decision-center/decisions/from-context", json={
        "origin": "analytics",
        "question": "Why did revenue decline?",
        "metric": "revenue",
        "title": "Investigate revenue decline in Electronics",
        "decision": {
            "metric": "revenue",
            "driver": "orders",
            "table": TABLE,
            "time_period": "2025-Q4",
            "evidence": [
                {"metric": "revenue", "current": 42000, "previous": 58000, "change": -27.6, "n": 24},
                {"metric": "orders", "current": 380, "previous": 520, "change": -26.9}
            ],
            "possible_drivers": [
                {"driver": "Electronics category decline", "confidence": "high", "contribution_pct": 62},
                {"driver": "Seasonal demand drop", "confidence": "moderate", "contribution_pct": 25}
            ],
            "recommendation": "Focus on Electronics category recovery.",
            "forecast": {"direction": "declining", "reliability": "moderate", "horizon": "3 months"},
            "impact": {"baseline": 58000, "delta": -16000, "scenario": 42000, "rel_pct": -27.6},
            "confidence": "high"
        }
    }, headers=H)
    d = r.json()
    assert d.get("ok"), f"Create failed: {d}"
    DECISION_ID = d.get("decision", {}).get("id")
    assert DECISION_ID, "No decision ID"
    assert DECISION_ID.startswith("dc_"), f"ID should start with dc_: {DECISION_ID}"

def test_evidence_persisted():
    r = client.get(f"/api/decision-center/decisions/{DECISION_ID}", headers=H)
    d = r.json()
    assert d.get("ok"), f"Detail failed: {d}"
    dec = d.get("decision", {})
    assert dec.get("evidence"), "Evidence not persisted"
    assert len(dec["evidence"]) >= 2, f"Expected >=2 evidence, got {len(dec['evidence'])}"
    assert dec.get("possible_drivers"), "Drivers not persisted"
    assert dec.get("recommendation"), "Recommendation not persisted"
    assert d.get("evidence_gap") is None, f"Unexpected gap: {d.get('evidence_gap')}"

def test_persists_across_reload():
    r = client.get(f"/api/decision-center/decisions/{DECISION_ID}", headers=H)
    dec = r.json().get("decision", {})
    assert dec.get("id") == DECISION_ID, "ID mismatch on reload"
    assert dec.get("status") == "Saved", f"Status not persisted: {dec.get('status')}"
    assert len(dec.get("evidence", [])) >= 2, "Evidence lost on reload"

test("Create from analytics", test_create_from_analytics)
test("Evidence persisted", test_evidence_persisted)
test("Persists across reload", test_persists_across_reload)

# ==========================================================
# 5. DASHBOARD -> DC SAME ID
# ==========================================================
print("\n--- 5. DASHBOARD -> DC SAME ID ---")

def test_dashboard_shares_decisions():
    r = client.get("/api/decision-center/decisions", headers=H)
    saved = r.json().get("saved", [])
    ids = [s["id"] for s in saved]
    assert DECISION_ID in ids, f"Dashboard doesn't see {DECISION_ID}: {ids}"

def test_click_opens_same_evidence():
    r = client.get(f"/api/decision-center/decisions/{DECISION_ID}", headers=H)
    dec = r.json().get("decision", {})
    assert dec.get("evidence"), "Evidence missing on click"
    assert dec.get("recommendation"), "Recommendation missing on click"

test("Dashboard shares decisions", test_dashboard_shares_decisions)
test("Click opens same evidence", test_click_opens_same_evidence)

# ==========================================================
# 6. STATUS LIFECYCLE
# ==========================================================
print("\n--- 6. STATUS LIFECYCLE ---")

def test_status_exploring():
    r = client.patch(f"/api/decision-center/decisions/{DECISION_ID}",
                     json={"status": "Exploring", "reason": "Starting investigation"}, headers=H)
    d = r.json()
    assert d.get("ok"), f"Status change failed: {d}"
    assert d.get("decision", {}).get("status") == "Exploring"

def test_status_saved():
    r = client.patch(f"/api/decision-center/decisions/{DECISION_ID}",
                     json={"status": "Saved"}, headers=H)
    assert r.json().get("ok") and r.json()["decision"]["status"] == "Saved"

def test_status_monitoring():
    r = client.patch(f"/api/decision-center/decisions/{DECISION_ID}",
                     json={"status": "Monitoring"}, headers=H)
    assert r.json().get("ok") and r.json()["decision"]["status"] == "Monitoring"

def test_status_persists():
    r = client.get(f"/api/decision-center/decisions/{DECISION_ID}", headers=H)
    assert r.json()["decision"]["status"] == "Monitoring"

def test_status_completed():
    r = client.patch(f"/api/decision-center/decisions/{DECISION_ID}",
                     json={"status": "Completed"}, headers=H)
    assert r.json().get("ok") and r.json()["decision"]["status"] == "Completed"

def test_dismiss_always_allowed():
    r = client.patch(f"/api/decision-center/decisions/{DECISION_ID}",
                     json={"status": "Dismissed"}, headers=H)
    assert r.json().get("ok") and r.json()["decision"]["status"] == "Dismissed"

test("Status -> Exploring", test_status_exploring)
test("Status -> Saved", test_status_saved)
test("Status -> Monitoring", test_status_monitoring)
test("Status persists across read", test_status_persists)
test("Status -> Completed", test_status_completed)
test("Status -> Dismissed always works", test_dismiss_always_allowed)

# ==========================================================
# 7. ACTIVITY TIMELINE
# ==========================================================
print("\n--- 7. ACTIVITY TIMELINE ---")

def test_activity_recorded():
    r = client.get(f"/api/decision-center/decisions/{DECISION_ID}", headers=H)
    dec = r.json().get("decision", {})
    activity = dec.get("activity", [])
    assert len(activity) >= 4, f"Expected >=4 events (created + 4 status changes), got {len(activity)}"
    events = [a.get("event", "") for a in activity]
    assert any("created" in e for e in events), "No 'created' event"
    assert any("Exploring" in e for e in events), "No Exploring event"

test("Activity timeline recorded", test_activity_recorded)

# ==========================================================
# 8. MONITORING
# ==========================================================
print("\n--- 8. MONITORING ---")

# Reopen for monitoring test
client.patch(f"/api/decision-center/decisions/{DECISION_ID}",
             json={"status": "Saved"}, headers=H)
client.patch(f"/api/decision-center/decisions/{DECISION_ID}",
             json={"status": "Monitoring"}, headers=H)

def test_outcome():
    r = client.get(f"/api/decision-center/decisions/{DECISION_ID}/outcome", headers=H)
    d = r.json()
    assert d.get("ok"), f"Outcome failed: {d}"

test("Monitoring outcome endpoint", test_outcome)

# ==========================================================
# 9. FROM-CONTEXT HANDOFFS (Insights, Forecast)
# ==========================================================
print("\n--- 9. FROM-CONTEXT HANDOFFS ---")

def test_insight_to_dc():
    r = client.post("/api/decision-center/decisions/from-context", json={
        "origin": "insights",
        "question": "Unusual spike in returns detected",
        "metric": "returns",
        "title": "Investigate returns spike in Food category",
        "decision": {
            "metric": "returns",
            "driver": "category",
            "table": TABLE,
            "evidence": [{"metric": "returns", "change": 45, "n": 24}],
            "possible_drivers": [{"driver": "Food category quality issue", "confidence": "moderate"}],
            "recommendation": "Review Food category supplier quality."
        }
    }, headers=H)
    d = r.json()
    assert d.get("ok"), f"Insight->DC failed: {d}"
    assert d["decision"]["id"] != DECISION_ID, "Should be a different decision"

def test_forecast_to_dc():
    r = client.post("/api/decision-center/decisions/from-context", json={
        "origin": "forecast",
        "question": "Forecast shows revenue risk in Q1",
        "metric": "revenue",
        "title": "Prepare for forecasted revenue decline",
        "decision": {
            "metric": "revenue",
            "driver": "seasonal",
            "table": TABLE,
            "forecast": {"direction": "declining", "reliability": "high", "horizon": "3 months"},
            "evidence": [{"metric": "revenue", "forecast_change": -15}],
            "recommendation": "Build inventory buffer for anticipated demand drop."
        }
    }, headers=H)
    assert r.json().get("ok"), f"Forecast->DC failed: {r.json()}"

def test_dc_list_has_all():
    r = client.get("/api/decision-center/decisions", headers=H)
    saved = r.json().get("saved", [])
    assert len(saved) >= 3, f"Expected >=3 decisions, got {len(saved)}"

test("Insights -> DC", test_insight_to_dc)
test("Forecast -> DC", test_forecast_to_dc)
test("DC list has all decisions", test_dc_list_has_all)

# ==========================================================
# 10. EMPTY / EDGE STATES
# ==========================================================
print("\n--- 10. EMPTY / EDGE STATES ---")

def test_prio_detail_explains():
    r = client.get("/api/decision-center/decisions/prio_0", headers=H)
    d = r.json()
    assert not d.get("ok"), "prio_0 should not resolve as a decision"
    assert d.get("code") == "NOT_A_DECISION", f"Expected NOT_A_DECISION, got {d.get('code')}"
    detail = d.get("detail", "").lower()
    assert "candidate" in detail or "lever" in detail, f"Detail should explain: {d.get('detail','')[:80]}"

def test_nonexistent_detail():
    r = client.get("/api/decision-center/decisions/dc_nonexistent", headers=H)
    d = r.json()
    assert not d.get("ok") and d.get("code") == "NOT_FOUND"

def test_delete_decision():
    r = client.post("/api/decision-center/decisions/from-context", json={
        "origin": "test", "title": "Temporary", "decision": {"metric": "test", "evidence": [{"n": 1}]}
    }, headers=H)
    did = r.json()["decision"]["id"]
    r = client.delete(f"/api/decision-center/decisions/{did}", headers=H)
    assert r.json().get("ok")
    r = client.get("/api/decision-center/decisions", headers=H)
    ids = [s["id"] for s in r.json().get("saved", [])]
    assert did not in ids, "Deleted decision still in list"

test("prio_* explains not a decision", test_prio_detail_explains)
test("Nonexistent id returns NOT_FOUND", test_nonexistent_detail)
test("Delete removes decision", test_delete_decision)

# ==========================================================
# 11. AI ANALYTICS INTEGRATION
# ==========================================================
print("\n--- 11. AI ANALYTICS INTEGRATION ---")

def test_ask_endpoint():
    r = client.post("/api/ask", json={"goal": "What is the average revenue?", "table": TABLE}, headers=H)
    d = r.json()
    ok = d.get("ok")
    has_answer = d.get("answer") or d.get("sql") or d.get("result")
    assert ok or has_answer, f"Ask failed: {str(d)[:200]}"

test("AI Analytics /api/ask", test_ask_endpoint)

# ==========================================================
# 12. SCENARIO
# ==========================================================
print("\n--- 12. SCENARIO ---")

def test_scenario():
    r = client.post("/api/decision-center/scenario", json={
        "table": TABLE, "metric": "revenue", "driver": "orders", "change_pct": 10
    }, headers=H)
    d = r.json()
    if d.get("ok"):
        assert d.get("baseline") is not None or d.get("scenarios") is not None
    else:
        assert d.get("code") in ("SCENARIO_UNSUPPORTED", "ANALYSIS_FAILED", "INVALID_METRIC", "LEVER_NOT_FOUND")

test("Scenario honest response", test_scenario)

# ==========================================================
# 13. LEVERS
# ==========================================================
print("\n--- 13. LEVERS ---")

def test_levers():
    r = client.get("/api/decision-center/levers", headers=H)
    d = r.json()
    assert d.get("ok"), f"Levers failed: {d}"
    levers = d.get("levers", [])
    assert isinstance(levers, list)
    print(f"    Found {len(levers)} levers")

test("Levers endpoint works", test_levers)

# ==========================================================
# 14. REGRESSION - Other pages
# ==========================================================
print("\n--- 14. REGRESSION ---")

def test_schema():
    r = client.get("/api/schema", headers=H)
    assert r.status_code == 200

def test_preview_reg():
    r = client.post("/api/data/preview", json={"table": TABLE, "limit": 3}, headers=H)
    assert (r.json().get("rows") or r.json().get("data"))

def test_predictive_eligibility():
    r = client.get("/api/predictive/eligibility", headers=H)
    d = r.json()
    assert d.get("ok"), f"Predictive eligibility broken: {str(d)[:200]}"

def test_hypothesis():
    r = client.get("/api/hypothesis/suggest", headers=H)
    d = r.json()
    assert d.get("ok"), f"Hypothesis suggest broken: {str(d)[:200]}"

def test_auth_me():
    r = client.get("/api/auth/me", headers=H)
    assert r.status_code == 200

def test_providers():
    r = client.get("/api/providers")
    assert r.status_code == 200

def test_history():
    r = client.get("/api/history", headers=H)
    assert r.status_code == 200

test("Schema intact", test_schema)
test("Preview intact", test_preview_reg)
test("Predictive eligibility intact", test_predictive_eligibility)
test("Hypothesis intact", test_hypothesis)
test("Auth intact", test_auth_me)
test("Providers intact", test_providers)
test("History intact", test_history)

# ==========================================================
# RESULTS
# ==========================================================
print("\n" + "=" * 60)
print(f"RESULTS: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
print("=" * 60)
for r in RESULTS:
    print(r)
print("=" * 60)
if FAIL > 0:
    print(f"\n{FAIL} TESTS FAILED")
    sys.exit(1)
else:
    print(f"\nALL {PASS} TESTS PASSED")
