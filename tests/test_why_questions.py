"""Why-question behavior: causal intent, change decomposition, honest story.

Covers the "why did revenue drop last month" path end to end minus HTTP:
classifier priority, period-over-period driver decomposition, hypothesis
wording, and trend-aware story/why prose in ``analyze_result``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from core.analytical_result import analyze_result
from goal_agent.analytics_intent import (
    build_change_hypothesis,
    classify_analytics,
    compute_change_drivers,
)


def test_why_drop_classifies_as_explanation():
    cls = classify_analytics("why did revenue drop last month",
                             schema_terms={"revenue", "orders"})
    assert cls["primary"] == "explanation"
    assert "root_cause" in cls["capabilities"]
    assert cls["confidence"] in ("medium", "high")


def test_why_framing_beats_incidental_filtering_signal():
    # "last month" alone is a filtering signal; "why ... fall" must win.
    plain = classify_analytics("units last month", schema_terms={"units"})
    assert plain["primary"] == "filtering"
    causal = classify_analytics("why did units fall last month",
                                schema_terms={"units"})
    assert causal["primary"] == "explanation"


@pytest.fixture()
def sales_engine():
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE sales (period TEXT, region TEXT, amount REAL)"))
        for period, region, amount in (
            ("2024-01", "North", 100.0),
            ("2024-02", "North", 40.0),
            ("2024-01", "South", 50.0),
            ("2024-02", "South", 50.0),
            ("2024-01", "West", 30.0),
            ("2024-02", "West", 20.0),
        ):
            conn.execute(
                text("INSERT INTO sales (period, region, amount) "
                     "VALUES (:p, :r, :a)"),
                {"p": period, "r": region, "a": amount})
    yield eng
    eng.dispose()


SQL_USED = ('SELECT "period" AS period, SUM("amount") AS value '
            'FROM "sales" GROUP BY period ORDER BY period')


def test_change_drivers_decompose_a_drop(sales_engine):
    series = [("2024-01", 180.0), ("2024-02", 110.0)]
    out = compute_change_drivers(
        sales_engine, "sqlite", SQL_USED, series,
        dims=[("sales", "region")],
        measure_alias="value", time_alias="period",
        question="why did revenue drop last month",
        metric_label="Revenue")
    change = out["change"]
    assert change and change["direction"] == "drop"
    assert change["previous"] == "January 2024"
    assert change["current"] == "February 2024"
    assert change["change_pct"] == -38.9
    drivers = out["drivers"]
    assert drivers, "expected a real segment decomposition"
    top = drivers[0]
    assert top["value"] == "North"
    assert top["delta"] == -60.0
    assert round(top["contribution_pct"]) == 86
    assert top["previous"] == 100.0 and top["total"] == 40.0
    assert drivers[1]["value"] == "West"
    assert all(d["value"] != "South" for d in drivers)


def test_change_drivers_reject_non_period_labels(sales_engine):
    series = [("Chai", 100.0), ("Chang", 40.0)]
    out = compute_change_drivers(
        sales_engine, "sqlite", SQL_USED, series,
        dims=[("sales", "region")], measure_alias="value",
        time_alias="period", question="why did revenue drop",
        metric_label="Revenue")
    assert out["drivers"] == []
    assert out["change"] is None


def test_change_drivers_pick_worst_mom_drop_without_hint(sales_engine):
    series = [("2024-01", 180.0), ("2024-02", 175.0)]
    out = compute_change_drivers(
        sales_engine, "sqlite", SQL_USED, series,
        dims=[("sales", "region")], measure_alias="value",
        time_alias="period", question="why did revenue drop",
        metric_label="Revenue")
    # Only one month-over-month move exists; it must be the target.
    assert out["change"]["current"] == "February 2024"


def test_build_change_hypothesis_wording(sales_engine):
    series = [("2024-01", 180.0), ("2024-02", 110.0)]
    out = compute_change_drivers(
        sales_engine, "sqlite", SQL_USED, series,
        dims=[("sales", "region")], measure_alias="value",
        time_alias="period", question="why did revenue drop",
        metric_label="Revenue")
    hyp = build_change_hypothesis(
        out["change"], out["drivers"], metric_label="Revenue",
        metric_col="amount", observation_count=2, dimensions=["region"])
    assert "fell" in hyp["text"]
    assert "North" in hyp["text"]
    assert "not proof of what caused" in hyp["text"]
    assert hyp["evidence_grade"] in ("strong", "mixed", "weak")
    assert hyp["change"]["direction"] == "drop"
    assert hyp["text"] != ""


def test_trend_story_and_why_are_time_aware():
    ir = {
        "operation": "trend",
        "intent": "trend",
        "dimensions": [{
            "concept": "last name",
            "resolved_table": "employees",
            "resolved_column": "last_name",
        }],
        "metrics": [{
            "concept": "revenue",
            "aggregation": "SUM",
            "resolved_table": "orders",
        }],
    }
    columns = ["period", "value"]
    rows = [
        {"period": "2024-01", "value": 100.0},
        {"period": "2024-02", "value": 50.0},
        {"period": "2024-03", "value": 30.0},
    ]
    res = analyze_result(ir, columns, rows,
                         goal="why did revenue drop last month",
                         sql="SELECT 1", row_count=3)
    story = str(res["story"]).lower()
    assert "last name" not in story
    assert "leads your" not in story
    assert "fell" in story
    why = res["why"]
    what = str(why["what_happened"]).lower()
    assert "last name" not in what
    assert "fell" in what
    tables = [t.lower() for t in why["evidence"]["tables"]]
    assert tables and all("last name" not in t for t in tables)
    assert res["answer"].lower().find("toughest month") >= 0


def test_non_trend_story_keeps_ranking_voice():
    ir = {
        "operation": "ranking",
        "intent": "ranking",
        "dimensions": [{
            "concept": "region",
            "resolved_table": "sales",
            "resolved_column": "region",
        }],
        "metrics": [{
            "concept": "revenue",
            "aggregation": "SUM",
            "resolved_table": "sales",
        }],
        "ranking": {"direction": "desc", "limit": 3},
    }
    columns = ["region", "value"]
    rows = [
        {"region": "North", "value": 100.0},
        {"region": "South", "value": 50.0},
        {"region": "West", "value": 30.0},
    ]
    res = analyze_result(ir, columns, rows, goal="top regions by revenue",
                         sql="SELECT 1", row_count=3)
    assert "North" in res["story"]
    assert "leads" in res["story"].lower() or "standout" in res["story"].lower()
