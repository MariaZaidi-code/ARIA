"""Suggestions, labels and autocomplete across database shapes (audit 4.1).

Three schema shapes, no live database:
  snake  - snake_case CSV (order_id, unit_price, total_amount ...)
  camel  - CamelCase, multi-schema (sales.SalesOrderHeader, TotalDue ...)
  messy  - data shorthand (amt, qty, txn_dt, pay_mthd, yr, mth)

Every shape must yield plain-English questions: no raw identifiers, full
lists, no totals of years/months/text/percentages, and typed text continued.
"""

import re
import unittest

from fastapi import HTTPException

from api.autocomplete_routes import _index_from_mapping, _question_pool, _rank_suggestions
from core.analytical_result import natural_label, synthesize_answer
from core.semantic import humanize
from core.validation import validate_goal_text
from goal_agent import GoalAgent
from goal_agent.suggestions import SuggestionsMixin
from schema_engine.lexical import humanize_identifier, pluralize, singularize


def _table(cols, stats=None, rows=1000):
    return {
        "columns": {c: {"data_type": t} for c, t in cols.items()},
        "null_stats": {c: {"distinct_count": n} for c, n in (stats or {}).items()},
        "row_count": rows,
        "primary_key": [],
        "foreign_keys": [],
    }


SHAPES = {
    "snake": {
        "sales_orders": _table(
            {"order_id": "INTEGER", "order_date": "TEXT", "region": "TEXT",
             "customer_segment": "TEXT", "product_category": "TEXT",
             "unit_price": "REAL", "quantity": "INTEGER",
             "discount_pct": "INTEGER", "total_amount": "REAL"},
            {"region": 5, "customer_segment": 3, "product_category": 4}),
    },
    "camel": {
        "sales.SalesOrderHeader": _table(
            {"SalesOrderID": "INTEGER", "CustomerID": "INTEGER", "OrderDate": "DATE",
             "OrderStatus": "TEXT", "SubTotal": "NUMERIC", "TaxAmt": "NUMERIC",
             "TotalDue": "NUMERIC"},
            {"OrderStatus": 3}),
        "sales.Customer": _table(
            {"CustomerID": "INTEGER", "CompanyName": "TEXT", "Region": "TEXT",
             "Segment": "TEXT"},
            {"CompanyName": 150, "Region": 5, "Segment": 3}, rows=150),
    },
    "messy": {
        "messy_txns": _table(
            {"txn_id": "TEXT", "txn_dt": "TEXT", "cust_nm": "TEXT", "store_cd": "TEXT",
             "prod_cat": "TEXT", "qty": "INTEGER", "amt": "REAL", "disc_pct": "INTEGER",
             "pay_mthd": "TEXT", "yr": "INTEGER", "mth": "INTEGER"},
            {"txn_id": 1500, "cust_nm": 390, "store_cd": 8, "prod_cat": 4,
             "pay_mthd": 4}, rows=1500),
    },
}
# txn_dt is profiled as a date even though it is stored as TEXT.
SHAPES["messy"]["messy_txns"]["column_classes"] = {"txn_dt": "date"}


def _raw_identifiers(shape):
    out = set()
    for t, info in SHAPES[shape].items():
        out.add(t.split(".")[-1])
        out.update(info["columns"])
    return {n for n in out if "_" in n or re.search(r"[a-z][A-Z]", n)}


class TestLabels(unittest.TestCase):
    def test_camelcase_and_shorthand_are_plain_words(self):
        cases = {
            "TotalDue": "total due", "SalesOrderHeader": "sales order header",
            "txn_dt": "transaction date", "cust_nm": "customer name",
            "pay_mthd": "pay method", "disc_pct": "discount percent",
            "amt": "amount", "sales.SalesPerson": "sales person",
        }
        for raw, want in cases.items():
            self.assertEqual(humanize_identifier(raw), want, raw)

    def test_natural_label_singularizes_only_the_head_noun(self):
        self.assertEqual(natural_label("order_details"), "order detail")
        self.assertEqual(natural_label("sales.SalesPerson"), "sales person")
        self.assertEqual(natural_label("amt"), "amount")
        self.assertEqual(natural_label("status"), "status")

    def test_display_labels_are_title_case_and_drop_key_suffixes(self):
        self.assertEqual(humanize("TotalDue"), "Total Due")
        self.assertEqual(humanize("pay_mthd"), "Pay Method")
        self.assertEqual(humanize("store_cd"), "Store")
        self.assertEqual(humanize("HTTPStatus"), "HTTP Status")

    def test_singular_and_plural_forms(self):
        singles = {"categories": "category", "addresses": "address", "boxes": "box",
                   "statuses": "status", "analyses": "analysis", "status": "status",
                   "analysis": "analysis", "series": "series", "news": "news",
                   "houses": "house", "orders": "order", "people": "person"}
        for word, want in singles.items():
            self.assertEqual(singularize(word), want, word)
        plurals = {"category": "categories", "status": "statuses",
                   "analysis": "analyses", "box": "boxes", "person": "people"}
        for word, want in plurals.items():
            self.assertEqual(pluralize(word), want, word)

    def test_semantic_mixin_labels_match_shared_helper(self):
        agent = GoalAgent.__new__(GoalAgent)
        self.assertEqual(agent._natural_label("TotalDue"), "total due")
        self.assertEqual(agent._plural_label("prod_cat"), "product categories")
        self.assertEqual(agent._pluralize_word("analysis"), "analyses")


class TestShorthandGrounding(unittest.TestCase):
    def _agent(self, shape):
        agent = GoalAgent.__new__(GoalAgent)
        agent.tables = SHAPES[shape]
        return agent

    def test_amount_shorthand_matches_amount_column(self):
        agent = self._agent("messy")
        self.assertTrue(agent._schema_token_matches_goal("amt", "amount"))
        self.assertTrue(agent._schema_token_matches_goal("qty", "quantity"))
        # 'amount' is money, not a count of units.
        self.assertFalse(agent._schema_token_matches_goal("qty", "amount"))

    def test_best_guess_measure_is_money_not_first_numeric(self):
        self.assertEqual(self._agent("messy")._pick_measure_column("messy_txns"), "amt")
        self.assertEqual(self._agent("snake")._pick_measure_column("sales_orders"),
                         "total_amount")


class TestAnswerWording(unittest.TestCase):
    def test_single_value_names_the_measure_exactly(self):
        text = synthesize_answer([{"total": 1071222.0}], "amount", "group", "SUM")
        self.assertEqual(text, "Total amount is 1,071,222 (about 1.1M).")
        text = synthesize_answer([{"average": 758.664}], "amount", "group", "AVG")
        self.assertEqual(text, "Average amount is 758.66.")
        self.assertEqual(synthesize_answer([{"count": 1500}], "record count", "group"),
                         "There are 1,500 records.")


class TestValidation(unittest.TestCase):
    def test_shorthand_questions_are_real_questions(self):
        for q in ("What is the total amt?", "total txns by pay mthd",
                  "Total pay mthd by txn dt"):
            self.assertEqual(validate_goal_text(q), q)

    def test_keyboard_noise_is_still_rejected(self):
        for q in ("sdfg hjkl", "wrtp xzcv", "asdf qwerty"):
            with self.assertRaises(HTTPException):
                validate_goal_text(q)


class TestAutocompleteShapes(unittest.TestCase):
    def _index(self, shape):
        idx = _index_from_mapping(SHAPES[shape])
        idx["values"] = []
        idx["ready"] = True
        return idx

    def test_pool_has_no_raw_identifiers(self):
        for shape in SHAPES:
            raws = _raw_identifiers(shape)
            for text, _kind, _m in _question_pool(self._index(shape)):
                for raw in raws:
                    self.assertNotIn(raw.lower(), text.lower(), (shape, text))
                self.assertNotRegex(text, r"[_()`\"]", (shape, text))

    def test_never_totals_periods_text_or_percentages(self):
        bad = re.compile(r"\b(total|average) (year|month|pay method|store code|"
                         r"product category|region|segment)\b|\btotal discount\b",
                         re.IGNORECASE)
        for shape in SHAPES:
            for text, _kind, _m in _question_pool(self._index(shape)):
                self.assertNotRegex(text, bad, (shape, text))

    def test_full_lists_for_every_shape(self):
        for shape in SHAPES:
            got = _rank_suggestions(self._index(shape), "what is", 8)
            self.assertEqual(len(got), 8, shape)

    def test_typed_text_is_continued(self):
        idx = self._index("messy")
        got = [s["text"] for s in _rank_suggestions(idx, "what is", 6)]
        self.assertEqual(got[0], "What is the total amount?")
        self.assertTrue(all(t.lower().startswith("what is") for t in got), got)
        got = [s["text"] for s in _rank_suggestions(idx, "total amt", 6)]
        self.assertTrue(all("amount" in t.lower() for t in got), got)
        got = [s["text"] for s in _rank_suggestions(self._index("snake"), "which reg", 6)]
        self.assertTrue(got and all("region" in t.lower() for t in got), got)
        self.assertTrue(all(t.startswith("Which region") for t in got[:5]), got)
        got = [s["text"] for s in _rank_suggestions(self._index("camel"), "what is", 3)]
        self.assertEqual(got[0], "What is the total due?")

    def test_dates_and_near_unique_text_are_not_groupings(self):
        idx = self._index("messy")
        groupable = {c["label"] for c in idx["categories"] if c["groupable"]}
        self.assertNotIn("customer name", groupable)
        self.assertNotIn("transaction", groupable)
        self.assertEqual([d["label"] for d in idx["dates"]], ["transaction date"])
        self.assertEqual({p["label"] for p in idx["periods"]}, {"year", "month"})


class TestSuggestionCleanup(unittest.TestCase):
    def test_llm_almost_json_is_salvaged(self):
        salvage = SuggestionsMixin._salvage_json_list
        self.assertEqual(salvage('["Which region sells most?", "Top 5 products?",]'),
                         ["Which region sells most?", "Top 5 products?"])
        self.assertEqual(salvage("1. Which store sells most?\n2) How has revenue changed?"),
                         ["Which store sells most?", "How has revenue changed?"])

    def test_llm_identifiers_and_blocked_types_are_dropped(self):
        mixin = SuggestionsMixin.__new__(SuggestionsMixin)
        got = mixin._clean_llm_suggestions([
            "Show orders.total_due by month", "Forecast sales next month?",
            "Which region has the highest sales?", "which region has the highest sales?"])
        self.assertEqual(got, ["Which region has the highest sales?"])


if __name__ == "__main__":
    unittest.main()


class TestAuditRegressions(unittest.TestCase):
    """Fixes found by the dataset A/B/C wiring check (work/findings.md)."""

    def test_timeline_rows_are_described_as_movement_not_ranking(self):
        rows = [{"period": 2024.0, "value": 875102.45}, {"period": 2025.0, "value": 930707.85}]
        text = synthesize_answer(rows, "total amount", "group")
        self.assertNotIn("leads", text)
        self.assertNotIn("2024.0", text)
        self.assertIn("increased", text)

    def test_ranking_uses_real_order_and_honest_margin(self):
        rows = [{"region": "North", "value": 300.0}, {"region": "South", "value": 388.0},
                {"region": "West", "value": 370.0}]
        text = synthesize_answer(rows, "amount", "region")
        self.assertTrue(text.startswith("Region South leads"), text)
        self.assertIn("just ahead", text)

    def test_yearly_questions_group_by_year(self):
        agent = GoalAgent.__new__(GoalAgent)
        agent.dialect = "sqlite"
        agent._month_expr = lambda t, c, d: "strftime('%Y-%m', d)"
        self.assertEqual(agent._period_expr("t", "d", "TEXT", "total amount by year"),
                         "SUBSTR(CAST(strftime('%Y-%m', d) AS TEXT), 1, 4)")
        self.assertEqual(agent._period_expr("t", "d", "TEXT", "monthly total"),
                         "strftime('%Y-%m', d)")
        self.assertEqual(agent._current_question_text(
            "Conversation context:\nQ: amount by year\nCurrent question: monthly total"),
            "monthly total")

    def test_kpi_cards_never_round_small_counts_up(self):
        from services.kpi_service import _fmt
        self.assertEqual(_fmt(1500), "1,500")
        self.assertEqual(_fmt(1071222.0), "1.1M")
        self.assertEqual(_fmt(4.37), "4.37")
        self.assertEqual(_fmt(float("nan")), "N/A")

    def test_provider_key_errors_are_plain_words(self):
        from core.errors import provider_key_error
        msg = provider_key_error("cloud", "Error code: 401 - {'error': {'message': 'Invalid API Key'}}")
        self.assertTrue(msg.startswith("Groq did not accept this API key"), msg)
        self.assertNotIn("{", msg)
        self.assertIn("internet", provider_key_error("cloud", "Connection timed out"))

    def test_embedder_is_loaded_once_per_process(self):
        from copilot.embeddings import create_embedder
        a = create_embedder(model_name="__missing_model__", prefer_local=False)
        b = create_embedder(model_name="__missing_model__", prefer_local=False)
        self.assertIs(a, b)


class TestDatasetBRegressions(unittest.TestCase):
    """Fixes found by the dataset B (CamelCase PostgreSQL) wiring check."""

    @staticmethod
    def _orders_agent():
        def t(cols, fks=()):
            return {"columns": {c: {"data_type": d} for c, d in cols.items()},
                    "primary_key": [],
                    "foreign_keys": [{"column": c, "referenced_table": r} for c, r in fks]}
        agent = GoalAgent.__new__(GoalAgent)
        agent.tables = {
            "sales.Customer": t({"CustomerID": "integer", "Region": "text"}),
            "production.Product": t({"ProductID": "integer", "CategoryName": "text"}),
            "sales.SalesOrderHeader": t(
                {"SalesOrderID": "integer", "CustomerID": "integer", "TotalDue": "numeric"},
                [("CustomerID", "sales.Customer")]),
            "sales.SalesOrderDetail": t(
                {"SalesOrderID": "integer", "ProductID": "integer", "LineTotal": "numeric"},
                [("SalesOrderID", "sales.SalesOrderHeader"), ("ProductID", "production.Product")]),
        }
        return agent

    def _resolve(self, dim_table):
        ir = {"metrics": [{"resolved_table": "sales.SalesOrderHeader",
                           "resolved_column": "TotalDue", "aggregation": "SUM"}],
              "dimensions": [{"resolved_table": dim_table, "resolved_column": "x"}]}
        self._orders_agent()._avoid_fan_out(ir)
        return ir["metrics"][0]

    def test_order_total_is_never_summed_across_its_lines(self):
        m = self._resolve("production.Product")
        self.assertEqual((m["resolved_table"], m["resolved_column"]),
                         ("sales.SalesOrderDetail", "LineTotal"))
        self.assertEqual(m["substituted_from"], "sales.SalesOrderHeader.TotalDue")

    def test_order_total_by_parent_dimension_is_kept(self):
        m = self._resolve("sales.Customer")
        self.assertEqual(m["resolved_column"], "TotalDue")
        self.assertNotIn("substituted_from", m)

    def test_labels_never_say_total_twice(self):
        from core.semantic import kpi_label
        self.assertEqual(kpi_label("SUM", "TotalDue"), "Total Due")
        self.assertEqual(kpi_label("SUM", "LineTotal"), "Line Total")
        self.assertEqual(kpi_label("SUM", "amt"), "Total Amount")


class TestWiringAuditFixes(unittest.TestCase):
    """Fixes from the Playwright wiring audit (ARIA_WIRING_AUDIT_REPORT.md)."""

    def test_shorthand_date_names_are_dates(self):  # H2
        from core.data_intelligence import classify_column, is_date_name
        for name in ("txn_dt", "created_ts", "order_date", "OrderDate"):
            self.assertTrue(is_date_name(name), name)
        self.assertEqual(classify_column("txn_dt", "TEXT"), "datetime")
        self.assertEqual(classify_column("pay_mthd", "TEXT"), "categorical")

    def test_period_question_never_answered_with_one_total(self):  # H2 safety net
        from core.analytical_result import analyze_result
        out = analyze_result({}, ["total"], [{"total": 3160}], goal="monthly total amount",
                             sql='SELECT SUM("amount") AS total FROM t')
        self.assertFalse(out["valid"])
        self.assertIn("date", out["answer"])

    def test_forecast_defaults_to_event_dates(self):  # M2
        from api.predictive_routes import _time_dim_rank
        self.assertLess(_time_dim_rank("OrderDate"), _time_dim_rank("ShipDate"))
        self.assertLess(_time_dim_rank("txn_dt"), _time_dim_rank("ModifiedDate"))

    def test_dataset_title_is_plain_words(self):  # L1
        from api.kpi_routes import _dataset_phrase
        self.assertEqual(_dataset_phrase("dataset_c_messy_txns"), "Dataset c messy transactions")
        self.assertEqual(_dataset_phrase(""), "your data")
