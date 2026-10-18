import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

import api.data_routes as data_routes


def _schema_file(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps({
        "tables": {
            "orders": {
                "columns": [
                    {"column": "order_id", "type": "INTEGER"},
                    {"column": "amount", "type": "REAL"},
                ],
                "null_stats": {},
            },
        },
        "declared_relationships": [],
    }), encoding="utf-8")
    return path


def _quality_for_source(monkeypatch, tmp_path, session):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE orders (order_id INTEGER, amount REAL)"
        ))
        conn.execute(text(
            "INSERT INTO orders (order_id, amount) VALUES (1, 10.0), (2, 20.0)"
        ))

    session["schema_path"] = str(_schema_file(tmp_path))
    monkeypatch.setattr(data_routes, "get_session", lambda _user_id: session)
    monkeypatch.setattr(
        "api.kpi_routes._build_engine",
        lambda _session: (engine, "sqlite", "sqlite"),
    )
    result = data_routes.get_data_quality(None, {"user_id": "test"})["quality"]
    engine.dispose()
    return result


def test_csv_quality_does_not_report_or_score_primary_key(monkeypatch, tmp_path):
    quality = _quality_for_source(
        monkeypatch,
        tmp_path,
        {"file_type": "csv", "db_type": "sqlite", "dialect": "sqlite"},
    )

    assert quality["metrics"]["primary_key_applicable"] is False
    assert "pk_coverage" not in quality["metrics"]
    assert not any(issue["check"] == "missing_pk" for issue in quality["issues"])
    assert quality["overall"] == 100


def test_relational_quality_keeps_primary_key_checks(monkeypatch, tmp_path):
    quality = _quality_for_source(
        monkeypatch,
        tmp_path,
        {"source_type": "relational", "db_type": "postgresql", "dialect": "postgresql"},
    )

    assert quality["metrics"]["primary_key_applicable"] is True
    assert quality["metrics"]["pk_coverage"] == 0
    assert any(issue["check"] == "missing_pk" for issue in quality["issues"])


def test_pdf_document_quality_remains_blocked_from_sql_scans(monkeypatch):
    monkeypatch.setattr(
        data_routes,
        "get_session",
        lambda _user_id: {"source_type": "document", "db_uri": "document://pdf-1"},
    )

    with pytest.raises(HTTPException) as exc:
        data_routes.get_data_quality(None, {"user_id": "test"})

    assert exc.value.status_code == 400
    assert "Document Chat" in exc.value.detail
