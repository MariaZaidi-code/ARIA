"""Regression coverage for exact insights on moderate sized SQL datasets."""

import sqlite3

from api.insights_routes import InsightsEngine, _SQLiteCompatConnection


def test_120k_row_dataset_is_not_reduced_to_a_partial_stride_sample():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, amount REAL)")
    mapping = {
        "tables": {
            "facts": {
                "row_count": 120_000,
                "columns": [
                    {"column": "id", "data_type": "integer"},
                    {"column": "amount", "data_type": "real"},
                ],
            }
        }
    }
    engine = InsightsEngine(_SQLiteCompatConnection(connection), mapping)

    engine._maybe_sample("facts")

    assert engine._sqlt == {}
    assert engine.sample_info == {"sampled": False, "tables": {}}
    engine.conn.close()
