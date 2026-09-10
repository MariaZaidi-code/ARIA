"""Analytical result reasoning: validation, repair and answer synthesis."""

from core.analytical_result import analyze_result


RANKING_IR = {
    "operation": "ranking",
    "intent": "ranking",
    "ranking": {"direction": "desc", "limit": 5},
    "dimensions": [
        {"concept": "customer", "resolved_table": "customer", "resolved_column": "last_name"}
    ],
    "metrics": [
        {"concept": "revenue kpi", "aggregation": "SUM",
         "resolved_column": "total", "resolved_table": "invoice"}
    ],
}


def test_transaction_rows_are_repaired_to_customer_granularity():
    rows = [
        {"customer_id": 6, "first_name": "A", "last_name": "Smith", "total": 10.0},
        {"customer_id": 6, "first_name": "A", "last_name": "Smith", "total": 5.0},
        {"customer_id": 7, "first_name": "B", "last_name": "Jones", "total": 40.0},
        {"customer_id": 8, "first_name": "C", "last_name": "Lee", "total": 2.0},
    ]
    res = analyze_result(
        ir=RANKING_IR, columns=list(rows[0].keys()), rows=rows,
        goal="top customers by invoice value", row_count=412,
    )
    assert res["repaired"] is True
    assert res["columns"] == ["last_name", "total"]
    assert res["data"][0] == {"last_name": "Jones", "total": 40.0}
    assert "Jones" in res["answer"]
    assert "customer_id" not in str(res["data"])
    assert res["chart_spec"]["chart_type"] == "bar_horizontal"
    assert res["chart_spec"]["x"] == "last_name"
    assert res["analysis"]["based_on"] == 412
    assert res["analysis"]["granularity"] == "one row per customer"


def test_preaggregated_ranking_is_not_repaired():
    rows = [
        {"last_name": "Jones", "total": 40.0},
        {"last_name": "Smith", "total": 15.0},
        {"last_name": "Lee", "total": 2.0},
    ]
    res = analyze_result(
        ir=RANKING_IR, columns=list(rows[0].keys()), rows=rows,
        goal="top customers by invoice value", row_count=3,
    )
    assert res["repaired"] is False
    assert res["data"][0]["last_name"] == "Jones"


def test_trend_gets_movement_answer_and_line_chart():
    ir = {
        "operation": "trend", "intent": "trend",
        "dimensions": [{"concept": "month", "resolved_table": "invoice"}],
        "metrics": [{"concept": "revenue kpi", "aggregation": "SUM", "resolved_column": "total"}],
    }
    rows = [
        {"month": "2024-01", "total": 10},
        {"month": "2024-02", "total": 20},
        {"month": "2024-03", "total": 30},
    ]
    res = analyze_result(
        ir=ir, columns=list(rows[0].keys()), rows=rows,
        goal="monthly revenue trend", row_count=3,
    )
    assert res["chart_spec"]["chart_type"] == "line"
    assert res["repaired"] is False
    assert "increased" in res["answer"]


def test_empty_result_is_invalid():
    res = analyze_result(
        ir=RANKING_IR, columns=["last_name", "total"], rows=[],
        goal="top customers by invoice value", row_count=0,
    )
    assert res["valid"] is False
    assert res["chart_spec"]["chart_type"] == "table"