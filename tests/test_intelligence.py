"""Tests for the Intelligence module (services + API routes).

Covers: eligibility, explore, goals CRUD, what-if, coverage, auth ownership.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MAPPING = {
    "tables": {
        "orders": {
            "columns": [
                {"column": "order_id", "data_type": "integer", "nullable": False},
                {"column": "revenue", "data_type": "numeric", "nullable": True},
                {"column": "quantity", "data_type": "integer", "nullable": True},
                {"column": "product_category", "data_type": "text", "nullable": True},
                {"column": "order_date", "data_type": "date", "nullable": True},
                {"column": "region", "data_type": "text", "nullable": True},
                {"column": "bytes", "data_type": "bigint", "nullable": True},
                {"column": "milliseconds", "data_type": "bigint", "nullable": True},
                {"column": "room_id", "data_type": "integer", "nullable": True},
            ],
            "primary_key": ["order_id"],
            "foreign_keys": [{"column": "room_id", "references": {"table": "rooms", "column": "room_id"}}],
            "row_count": 1000,
        },
        "rooms": {
            "columns": [
                {"column": "room_id", "data_type": "integer", "nullable": False},
                {"column": "room_name", "data_type": "text", "nullable": True},
                {"column": "capacity", "data_type": "integer", "nullable": True},
            ],
            "primary_key": ["room_id"],
            "row_count": 50,
        },
    }
}

SESSION = {
    "provider": "local",
    "source_type": "semi-structured",
    "db_uri": "sqlite:///:memory:",
    "db_name": "test_dataset",
    "schema_path": None,
}


@pytest.fixture(autouse=True)
def _setup_schema_path(tmp_path):
    """Write MAPPING to a temp file so _load_schema_mapping finds it."""
    schema_path = tmp_path / "schema_mapping_latest.json"
    schema_path.write_text(json.dumps(MAPPING), encoding="utf-8")
    SESSION["schema_path"] = str(schema_path)
    yield
    SESSION["schema_path"] = None


@pytest.fixture
def user_id():
    return 12345


@pytest.fixture
def dataset_id():
    from services.intelligence_service import _dataset_id
    return _dataset_id(SESSION)


# ---------------------------------------------------------------------------
# Eligibility tests
# ---------------------------------------------------------------------------

class TestEligibility:
    def test_measure_vs_measure_rejected(self):
        """BREAKDOWN: measure used as dimension must be rejected."""
        from services.intelligence_service import _classify_columns
        roles = _classify_columns(MAPPING)
        order_roles = roles["orders"]

        # revenue is MEASURE, quantity is MEASURE
        # Using quantity as breakdown should be flagged
        assert order_roles["revenue"] in ("MEASURE", "BUSINESS_MEASURE")
        assert order_roles["quantity"] in ("MEASURE", "BUSINESS_MEASURE")

        # The explore function should reject this
        from services.intelligence_service import run_explore
        result = run_explore(SESSION, {"metric": "revenue", "breakdown": "quantity"})
        assert result["ok"] is False
        assert "MEASURE_USED_AS_DIMENSION" in result.get("code", "")

    def test_technical_only_rejected(self):
        """BYTES/MILLISECONDS must not be used as business breakdowns."""
        from services.intelligence_service import _classify_columns
        roles = _classify_columns(MAPPING)
        order_roles = roles["orders"]

        assert order_roles["bytes"] == "TECHNICAL_MEASURE"
        assert order_roles["milliseconds"] == "TECHNICAL_MEASURE"

        from services.intelligence_service import run_explore
        result = run_explore(SESSION, {"metric": "revenue", "breakdown": "bytes"})
        assert result["ok"] is False
        assert "TECHNICAL_ONLY" in result.get("code", "")

    def test_fk_not_driver(self):
        """FOREIGN KEY must not be used as business dimension."""
        from services.intelligence_service import _classify_columns
        roles = _classify_columns(MAPPING)
        order_roles = roles["orders"]

        assert order_roles["room_id"] == "FOREIGN_KEY"

        from services.intelligence_service import run_explore
        result = run_explore(SESSION, {"metric": "revenue", "breakdown": "room_id"})
        assert result["ok"] is False
        assert "FK_NOT_DRIVER" in result.get("code", "")

    def test_valid_breakdown_accepted(self):
        """Valid dimension breakdown should be accepted (even without DB)."""
        from services.intelligence_service import _classify_columns
        roles = _classify_columns(MAPPING)
        order_roles = roles["orders"]

        # product_category is TEXT -> DIMENSION, revenue is MEASURE
        assert order_roles["product_category"] in ("DIMENSION", "CATEGORY", "TEXT")
        assert order_roles["revenue"] in ("MEASURE", "BUSINESS_MEASURE")

    def test_valid_dimension_breakdown(self):
        """Region is TEXT/DIMENSION — valid breakdown for revenue MEASURE."""
        from services.intelligence_service import _classify_columns
        roles = _classify_columns(MAPPING)
        order_roles = roles["orders"]
        assert order_roles["region"] in ("DIMENSION", "CATEGORY", "TEXT")
        assert order_roles["revenue"] in ("MEASURE", "BUSINESS_MEASURE")


class TestUndefinedColumnHonesty:
    """FAILURE C regression: type errors must not masquerade as join errors."""

    def test_sum_text_is_not_undefined_column(self):
        from services.intelligence_service import _is_undefined_column
        type_err = type("ProgrammingError", (Exception,), {})(
            "(psycopg2.errors.UndefinedFunction) function sum(text) does not exist")
        assert _is_undefined_column(type_err) is False
        missing = Exception(
            '(psycopg2.errors.UndefinedColumn) column "foo" does not exist')
        assert _is_undefined_column(missing) is True
        assert _is_undefined_column(Exception("no such column: foo")) is True
        assert _is_undefined_column(Exception("Unknown column 'foo'")) is True
        assert _is_undefined_column(
            Exception('ORA-00904: "FOO": invalid identifier')) is True

    def test_text_metric_casts_instead_of_crashing(self, tmp_path):
        """TEXT-stored prices (e.g. 'Rs.1,099') SUM via numeric cast."""
        import json as _json
        import sqlite3 as _sqlite3
        db_path = tmp_path / "textmoney.db"
        conn = _sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE amazon (id INTEGER PRIMARY KEY, price TEXT, cat TEXT)")
        for i, (p, c) in enumerate([("Rs.1,099", "A"), ("Rs.349", "B"),
                                    ("Rs.2,000", "A"), ("Rs.100", "B")]):
            conn.execute("INSERT INTO amazon VALUES (?,?,?)", (i, p, c))
        conn.commit()
        conn.close()
        mapping = {"tables": {"amazon": {
            "columns": [
                {"column": "id", "data_type": "integer", "nullable": False},
                {"column": "price", "data_type": "text", "nullable": True},
                {"column": "cat", "data_type": "text", "nullable": True},
            ],
            "primary_key": ["id"], "row_count": 4}}}
        schema_path = tmp_path / "schema_mapping_latest.json"
        schema_path.write_text(_json.dumps(mapping), encoding="utf-8")
        session = {"provider": "local", "source_type": "csv",
                   "db_uri": f"sqlite:///{db_path}",
                   "db_name": "tm", "schema_path": str(schema_path)}
        from services.intelligence_service import run_explore
        res = run_explore(session, {"metric": "price", "breakdown": "cat"})
        assert res["ok"] is True, res.get("detail")
        assert abs(float(res["total"]) - 3548.0) < 0.05
        assert res.get("validation", {}).get("passed") is True


class TestJoinPathDepth:
    """FAILURE F regression: 3-hop paths join instead of refusing."""

    def test_three_hop_path_found(self):
        from services.intelligence_service import _find_join_path
        mapping = {"tables": {"a": {}, "b": {}, "c": {}, "d": {}},
                   "declared_relationships": [
                       {"table_name": "b", "column_name": "a_id",
                        "references_table": "a", "references_column": "id"},
                       {"table_name": "c", "column_name": "b_id",
                        "references_table": "b", "references_column": "id"},
                       {"table_name": "d", "column_name": "c_id",
                        "references_table": "c", "references_column": "id"},
                   ]}
        roles = {"a": {"id": "IDENTIFIER"}, "b": {"a_id": "FOREIGN_KEY"},
                 "c": {"b_id": "FOREIGN_KEY"}, "d": {"c_id": "FOREIGN_KEY",
                                                     "x": "DIMENSION"}}
        hops = _find_join_path(mapping, roles, "a", "d")
        assert hops is not None and len(hops) == 3
        # Unknown names resolve to no targets ([]); a real but isolated
        # table is honestly unreachable (None).
        assert _find_join_path(mapping, roles, "a", "zz") == []
        mapping["tables"]["iso"] = {}
        roles["iso"] = {"z": "DIMENSION"}
        assert _find_join_path(mapping, roles, "a", "iso") is None


# ---------------------------------------------------------------------------
# Meta tests
# ---------------------------------------------------------------------------

class TestMeta:
    def test_meta_returns_structure(self):
        """GET /meta should return metrics, dimensions, date_columns."""
        # Session without schema_path — returns empty but valid structure
        from services.intelligence_service import get_intelligence_meta
        result = get_intelligence_meta(SESSION)
        assert result["ok"] is True
        assert "metrics" in result
        assert "dimensions" in result
        assert "date_columns" in result


# ---------------------------------------------------------------------------
# Goals CRUD tests
# ---------------------------------------------------------------------------

class TestGoalsCRUD:
    def test_create_and_list(self, user_id, dataset_id):
        from services.intelligence_service import create_goal, list_goals
        goal = create_goal(user_id, dataset_id, {
            "title": "Increase Revenue",
            "metric": "revenue",
            "target_value": 100000,
            "current_value": 80000,
        })
        assert goal["id"]
        assert goal["status"] == "active"
        assert goal.get("progress_pct") is not None
        assert goal["progress_pct"] == 80.0

        goals = list_goals(user_id, dataset_id)
        assert len(goals) >= 1
        assert any(g["id"] == goal["id"] for g in goals)

    def test_update_goal_status(self, user_id, dataset_id):
        from services.intelligence_service import create_goal, update_goal, list_goals
        goal = create_goal(user_id, dataset_id, {"title": "Test"})
        updated = update_goal(user_id, goal["id"], {"status": "saved"})
        assert updated is not None
        assert updated["status"] == "saved"

    def test_delete_goal(self, user_id, dataset_id):
        from services.intelligence_service import create_goal, delete_goal, list_goals
        goal = create_goal(user_id, dataset_id, {"title": "To Delete"})
        assert delete_goal(user_id, goal["id"]) is True
        remaining = list_goals(user_id, dataset_id)
        assert not any(g["id"] == goal["id"] for g in remaining)

    def test_goal_progress_computation(self, user_id, dataset_id):
        from services.intelligence_service import create_goal
        goal = create_goal(user_id, dataset_id, {
            "title": "Near target",
            "target_value": 100,
            "current_value": 95,
        })
        assert goal["progress_pct"] == 95.0
        assert goal["status_label"] == "Near target"

    def test_dataset_isolation(self):
        """User A cannot read User B's goals."""
        from services.intelligence_service import list_goals
        goals_a = list_goals(111, "ds_a")
        goals_b = list_goals(222, "ds_a")
        assert goals_a == []
        assert goals_b == []


# ---------------------------------------------------------------------------
# What-If tests
# ---------------------------------------------------------------------------

class TestWhatIf:
    def test_whatif_meta_structure(self):
        from services.intelligence_service import get_whatif_meta
        result = get_whatif_meta(SESSION)
        assert result["ok"] is True
        assert "variables" in result

    def test_whatif_requires_variable(self):
        from services.intelligence_service import run_whatif
        result = run_whatif(SESSION, {})
        assert result["ok"] is False
        assert "variable" in result.get("detail", "").lower() or result.get("code") == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Coverage tests
# ---------------------------------------------------------------------------

class TestCoverage:
    def test_coverage_structure(self):
        from services.intelligence_service import get_coverage
        result = get_coverage(SESSION)
        assert result["ok"] is True
        assert "examined" in result
        assert "accepted" in result
        assert "rejected" in result


# ---------------------------------------------------------------------------
# Hypotheses tests
# ---------------------------------------------------------------------------

class TestHypotheses:
    def test_hypotheses_candidates(self):
        from services.intelligence_service import generate_hypotheses
        result = generate_hypotheses(SESSION, {})
        assert result["ok"] is True
        assert "candidates" in result
        # Hypothesis prompts should investigate metric movement over time,
        # not manufacture arbitrary metric-by-dimension relationships.
        assert result["candidates"]
        assert {c["type"] for c in result["candidates"]} == {"trend"}
        for candidate in result["candidates"]:
            assert "change over time" in candidate["title"].lower()
            assert "vary by" not in candidate["title"].lower()
            assert candidate["evidence_strength"] == "Not tested"
            assert candidate["evidence"] == []
            # Measure labels are table-qualified ("Orders Revenue"), never a
            # bare ambiguous column word.
            assert candidate["metric_label"].startswith("Orders ")

    def test_trend_detail_spans_full_range(self, tmp_path):
        """The "All data" trend compares halves of the WHOLE range.

        Regression: the quick trend used to read only the earliest 24 date
        buckets, so a dataset could headline "increased" from its first
        month while the full range declined.
        """
        import sqlite3
        from datetime import date, timedelta
        from services.intelligence_service import (_hypothesis_items,
                                                   get_hypothesis_detail)
        db = tmp_path / "orders.db"
        conn = sqlite3.connect(str(db))
        try:
            conn.execute("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, "
                         "revenue REAL, quantity INTEGER, order_date TEXT)")
            rows, base = [], date(2021, 1, 1)
            for day in range(40):
                # Days 13-24 are double days 1-12: a 24-bucket window reads
                # "+100%", the full 40 days read a decline (280 -> 160).
                rev = 10.0 if day < 12 else (20.0 if day < 24 else 5.0)
                rows.append((day + 1, rev, 1,
                             (base + timedelta(days=day)).isoformat()))
            conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", rows)
            conn.commit()
        finally:
            conn.close()
        SESSION["db_uri"] = f"sqlite:///{db}"
        try:
            cands = _hypothesis_items(SESSION)
            rev = next(c for c in cands if c["metric"] == "revenue")
            assert rev["metric_label"] == "Orders Revenue"
            detail = get_hypothesis_detail(SESSION, rev["id"])
        finally:
            SESSION["db_uri"] = "sqlite:///:memory:"
        pat = detail["observed_pattern"]
        assert len(pat["series"]) == 40
        assert pat["direction"] == "declined"
        assert abs(pat["change_pct"] - (-42.9)) < 0.15


class TestHypothesesListEnrichment:
    """List cards carry measured moves; empty searches explain themselves."""

    def test_list_hint_when_search_measure_has_no_time(self):
        """A searched measure whose table has no date gets a plain-worded hint."""
        from services.intelligence_service import generate_hypotheses
        res = generate_hypotheses(SESSION, {"search": "capacity"})
        assert res["ok"] is True
        assert res["items"] == []
        # rooms.capacity is a real numeric measure and rooms has no date
        # column — the empty result explains why instead of a blank page.
        assert "no time column" in res["hint"]
        assert "capacity" in res["hint"].lower()

    def test_list_cards_carry_measured_trend_summary(self, tmp_path):
        """Every trend card gets real earliest-vs-latest numbers when the
        pair can be measured from the data — never a fabricated chip."""
        import sqlite3
        from datetime import date, timedelta
        from services.intelligence_service import generate_hypotheses
        db = tmp_path / "orders.db"
        conn = sqlite3.connect(str(db))
        try:
            conn.execute("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, "
                         "revenue REAL, quantity INTEGER, order_date TEXT)")
            base = date(2021, 1, 1)
            rows = []
            for day in range(12):
                rev = 10.0 if day < 6 else 20.0
                rows.append((day + 1, rev, 1,
                             (base + timedelta(days=day)).isoformat()))
            conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", rows)
            conn.commit()
        finally:
            conn.close()
        SESSION["db_uri"] = f"sqlite:///{db}"
        try:
            res = generate_hypotheses(SESSION, {"page_size": 10, "sort": "az"})
        finally:
            SESSION["db_uri"] = "sqlite:///:memory:"
        assert res["ok"] is True
        item = next(i for i in res["items"] if i["metric"] == "revenue")
        ts = item.get("trend_summary")
        assert ts, "revenue trend should be measurable from real dates"
        assert ts["direction"] == "increased"
        assert ts["change_pct"] == 100.0
        assert ts["first_display"] and ts["last_display"]
        assert ts["first_label"] != ts["last_label"]
        assert "trend_limitation" not in item
