import sqlite3

from sqlalchemy import create_engine

from api.hypothesis_routes import HypothesisRequest, _run_test
from core.schema_intel import SchemaIntelligence
from hypothesis_engine.engine import analyze_question


def _correlation_engine(tmp_path):
    path = tmp_path / "correlation.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sales (quantity INTEGER, unit_price REAL);
        CREATE TABLE products (unit_price REAL, units_in_stock REAL);
    """)
    conn.executemany(
        "INSERT INTO sales VALUES (?, ?)",
        [(i, 20.0 + (i % 2) * 0.1) for i in range(1, 41)],
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?)",
        [(float(i), float(i * 10)) for i in range(1, 21)],
    )
    conn.commit()
    conn.close()
    return create_engine(f"sqlite:///{path}")


def test_legacy_comparisons_keep_the_tested_pair_first(tmp_path):
    engine = _correlation_engine(tmp_path)
    try:
        response = _run_test(
            engine,
            "sqlite",
            HypothesisRequest(hypothesis="relationship between quantity and unit price"),
        )
    finally:
        engine.dispose()

    assert response["ok"] is True
    assert response["x_label"] == "quantity"
    assert response["y_label"] == "unit_price"
    assert response["comparisons"][0]["table"] == "sales"
    assert response["comparisons"][0]["x"] == response["x_label"]
    assert response["comparisons"][0]["y"] == response["y_label"]
    assert response["stats"]["Direction"] == "No clear direction"


def test_unsignificant_correlation_explanation_does_not_imply_a_direction(
    tmp_path,
):
    engine = _correlation_engine(tmp_path)
    mapping = {
        "tables": {
            "sales": {
                "columns": [
                    {"column": "quantity", "data_type": "integer"},
                    {"column": "unit_price", "data_type": "real"},
                ],
                "primary_key": [],
                "foreign_keys": [],
            },
        },
    }
    try:
        response = analyze_question(
            engine,
            "sqlite",
            SchemaIntelligence(mapping),
            ["sales"],
            "Does quantity relate to unit price?",
            metric_override="unit_price",
            driver_override="quantity",
        )
    finally:
        engine.dispose()

    assert response["ok"] is True
    assert response["verdict"] == "NOT SUPPORTED"
    assert "no clear relationship" in response["explanation"]
    assert "rise together" not in response["explanation"]


def test_invalid_selected_driver_is_not_replaced_by_an_unrelated_dimension(
    tmp_path,
):
    path = tmp_path / "rooms.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE rooms (
            room_id INTEGER PRIMARY KEY,
            room_type TEXT,
            price_per_night REAL
        );
        INSERT INTO rooms VALUES
            (1, 'standard', 100.0),
            (2, 'suite', 200.0);
    """)
    conn.commit()
    conn.close()

    mapping = {
        "tables": {
            "rooms": {
                "columns": [
                    {"column": "room_id", "data_type": "integer"},
                    {"column": "room_type", "data_type": "text"},
                    {"column": "price_per_night", "data_type": "real"},
                ],
                "primary_key": ["room_id"],
                "foreign_keys": [],
            },
        },
    }
    engine = create_engine(f"sqlite:///{path}")
    try:
        response = analyze_question(
            engine,
            "sqlite",
            SchemaIntelligence(mapping),
            ["rooms"],
            "Does room capacity relate to nightly price?",
            metric_override="price_per_night",
            driver_override="max_people",
        )
    finally:
        engine.dispose()

    assert response["ok"] is False
    assert response["code"] == "COLUMN_NOT_FOUND"
    assert "max_people" in response["detail"]
