"""Regression tests for the /api/predictive/forecast route.

Hermetic: a temp SQLite file + schema mapping, and a monkeypatched
``get_session``. No network, no LLM (provider=None forces the deterministic
fallback inside the route, which is the production fallback path).
"""
from __future__ import annotations

import datetime
import json
import sqlite3

import pytest

from api import predictive_routes as pr
from api.predictive_routes import ForecastRequest


def _make_source(tmp_path):
    db = tmp_path / "sales.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sales (sale_date TEXT, amount REAL, region TEXT)")
    rows = []
    for i in range(30):
        d = (datetime.date(2023, 1, 1) + datetime.timedelta(days=30 * i)).isoformat()
        rows.append((d, 100.0 + i * 7.5, "north" if i % 2 else "south"))
    con.executemany("INSERT INTO sales VALUES (?,?,?)", rows)
    con.commit()
    con.close()

    mapping = {
        "tables": {
            "sales": {
                "columns": [
                    {"column": "sale_date", "data_type": "text"},
                    {"column": "amount", "data_type": "real"},
                    {"column": "region", "data_type": "text"},
                ],
                "primary_key": [],
            }
        }
    }
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(mapping), encoding="utf-8")
    return db, schema


def _session(db, schema, *, with_db_dict=True):
    return {
        "schema_path": str(schema),
        "db": {".csv": str(db)} if with_db_dict else {},
        "db_uri": f"sqlite:///{db}",
        "db_type": "sqlite",
        "db_name": "sales",
        "source_type": "semi-structured",
        "provider": None,
    }


@pytest.fixture()
def patched_session(monkeypatch):
    def _apply(session):
        monkeypatch.setattr(pr, "get_session", lambda uid: dict(session))
    return _apply


def test_forecast_works_with_csv_db_dict(tmp_path, patched_session):
    db, schema = _make_source(tmp_path)
    patched_session(_session(db, schema, with_db_dict=True))
    res = pr.generate_forecast(
        ForecastRequest(column="amount", time_dim="sale_date", horizon=6),
        None, {"user_id": 1},
    )
    assert res["ok"] is True
    forecast = res["forecast"]
    assert forecast["valid"] is True
    assert len(forecast["historical"]) > 0
    assert len(forecast["forecast"]) == 6


def test_forecast_accepts_db_uri_only_session(tmp_path, patched_session):
    """Legacy/CSV sessions with an empty db dict but a db_uri must forecast."""
    db, schema = _make_source(tmp_path)
    patched_session(_session(db, schema, with_db_dict=False))
    res = pr.generate_forecast(
        ForecastRequest(column="amount", time_dim="sale_date", horizon=4),
        None, {"user_id": 1},
    )
    assert res["ok"] is True
    assert res["forecast"]["valid"] is True


def test_forecast_refuses_document_session(tmp_path, patched_session):
    db, schema = _make_source(tmp_path)
    session = _session(db, schema)
    session["source_type"] = "document"
    session["db_type"] = "document"
    session["db_uri"] = "document://doc-1"
    patched_session(session)
    with pytest.raises(Exception):
        pr.generate_forecast(
            ForecastRequest(column="amount", time_dim="sale_date", horizon=6),
            None, {"user_id": 1},
        )
