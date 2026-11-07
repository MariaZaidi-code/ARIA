import json
import sqlite3

from starlette.requests import Request

import api.insights_routes as insights_routes
import api.predictive_routes as predictive_routes


def _request():
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/audit",
        "headers": [],
        "query_string": b"",
    })


def test_forecast_replaces_goal_series_missing_selected_measure(tmp_path, monkeypatch):
    db_path = tmp_path / "forecast.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE orders (order_date DATE NOT NULL, freight REAL NOT NULL)"
    )
    for month in range(1, 19):
        conn.execute(
            "INSERT INTO orders VALUES (?, ?)",
            (f"2023-{month:02d}-01", float(month * 100)),
        )
    conn.commit()
    conn.close()

    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps({
        "tables": {
            "orders": {
                "row_count": 18,
                "columns": [
                    {"column": "order_date", "data_type": "date"},
                    {"column": "freight", "data_type": "real"},
                ],
            },
        },
    }), encoding="utf-8")

    session = {
        "db": {"db": str(db_path)},
        "db_name": "temporary",
        "db_type": "sqlite",
        "db_uri": f"sqlite:///{db_path.as_posix()}",
        "provider": None,
        "source_type": "file",
        "schema_path": schema_path,
    }
    monkeypatch.setattr(predictive_routes, "get_session", lambda _user_id: session)

    class IncorrectGoalAgent:
        def __init__(self, **_kwargs):
            pass

        def process_goal(self, _question, output_path):
            return {
                "data": [
                    {"order_date": "2023-01-01", "value": 1},
                    {"order_date": "2023-02-01", "value": 1},
                ],
                "sql_used": "SELECT order_date, COUNT(*) AS value FROM orders",
            }

    monkeypatch.setattr(
        "goal_agent.agent.GoalAgent", IncorrectGoalAgent
    )

    response = predictive_routes.generate_forecast(
        predictive_routes.ForecastRequest(
            question="Forecast freight by order date",
            column="freight",
            time_dim="order_date",
            horizon=3,
        ),
        _request(),
        {"user_id": 1},
    )

    assert response["ok"] is True
    assert response["selection"]["measure"] == "freight"
    assert response["info"]["fallback_used"] is True
    historical_values = [row["value"] for row in response["historical"]]
    assert len(historical_values) >= 5
    assert set(historical_values).issubset({float(i * 100) for i in range(1, 19)})


def test_insights_evidence_uses_live_table_counts_when_schema_has_none(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "insights.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE observations "
        "(id INTEGER PRIMARY KEY, amount REAL, event_date DATE)"
    )
    conn.executemany(
        "INSERT INTO observations (amount, event_date) VALUES (?, ?)",
        [(float(i), f"2024-01-{(i % 28) + 1:02d}") for i in range(12)],
    )
    conn.commit()
    conn.close()

    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps({
        "tables": {
            "observations": {
                "columns": [
                    {"column": "id", "data_type": "integer"},
                    {"column": "amount", "data_type": "real"},
                    {"column": "event_date", "data_type": "date"},
                ],
            },
        },
    }), encoding="utf-8")

    session = {
        "db": {"db": str(db_path)},
        "db_name": "temporary",
        "db_type": "sqlite",
        "db_uri": f"sqlite:///{db_path.as_posix()}",
        "source_type": "file",
        "schema_path": schema_path,
    }
    monkeypatch.setattr(insights_routes, "get_session", lambda _user_id: session)

    response = insights_routes.get_insights(_request(), {"user_id": 1})

    assert response["ok"] is True
    assert response["evidence_state"]["row_count"] == 12
    assert response["evidence_state"]["status"] == "supported"
