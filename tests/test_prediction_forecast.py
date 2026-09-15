"""Forecasting rebuild + intelligent model selection (n.txt items 3, 4).

Hermetic: pure-math pipeline on temp data. No network, no LLM, no database.
"""

import re
import unittest

import numpy as np

from prediction import selection as selection_mod
from prediction.agent import PredictionAgent
from prediction.evaluate import backtest_competing, holdout_backtest, mape, rmse

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def monthly_rows(n, start_year=2024, start_month=1, fn=None):
    rows = []
    y, m = start_year, start_month
    for i in range(n):
        val = fn(i) if fn else 100.0 + i * 10.0
        rows.append({"d": f"{y}-{m:02d}-01", "amount": float(val)})
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return rows


class TestForecastContract(unittest.TestCase):
    def test_contract_shape(self):
        out = PredictionAgent().forecast(
            {"data": monthly_rows(12), "user_goal": "forecast amount"})
        for key in ("historical", "forecast", "frequency", "target",
                    "model", "horizon", "metrics"):
            self.assertIn(key, out, f"missing contract key {key}")
        self.assertTrue(out["historical"])
        self.assertTrue(out["forecast"])
        for h in out["historical"]:
            self.assertIn("date", h)
            self.assertIn("value", h)
        for f in out["forecast"]:
            self.assertIn("date", f)
            self.assertIn("value", f)
            self.assertIn("lower", f)
            self.assertIn("upper", f)
            self.assertLessEqual(f["lower"], f["value"])
            self.assertLessEqual(f["value"], f["upper"])
        self.assertEqual(out["target"], "amount")
        self.assertEqual(out["frequency"], "MS")
        self.assertEqual(out["horizon"], len(out["forecast"]))
        for key in ("mae", "rmse", "mape"):
            self.assertIn(key, out["metrics"])

    def test_backend_timestamps_only(self):
        """x-axis dates come from the backend: history months verbatim, future
        months continuing after the last one — never index labels."""
        rows = monthly_rows(12)
        out = PredictionAgent().forecast(
            {"data": rows, "user_goal": "forecast amount"})
        hist_dates = [h["date"] for h in out["historical"]]
        self.assertEqual(hist_dates, [r["d"] for r in rows[-len(hist_dates):]])
        for h in out["historical"]:
            self.assertRegex(h["date"], DATE_RE)
        fut_dates = [f["date"] for f in out["forecast"]]
        self.assertTrue(all(DATE_RE.match(d) for d in fut_dates))
        self.assertGreater(min(fut_dates), max(hist_dates))
        self.assertEqual(len(set(fut_dates)), len(fut_dates))

    def test_legacy_keys_preserved(self):
        out = PredictionAgent().forecast(
            {"data": monthly_rows(12), "user_goal": "forecast amount"})
        for key in ("column", "period", "method", "valid", "validation",
                    "points", "history", "last_actual", "projected_pct_change"):
            self.assertIn(key, out)
        self.assertEqual(out["column"], out["target"])
        self.assertEqual(out["method"], out["model"])
        self.assertEqual(
            [p["label"] for p in out["points"]],
            [f["date"] for f in out["forecast"]],
        )
        self.assertEqual(
            [h["label"] for h in out["history"]],
            [h["date"] for h in out["historical"]],
        )

    def test_empty_is_contract_safe(self):
        out = PredictionAgent().forecast({"data": []})
        self.assertFalse(out["valid"])
        self.assertEqual(out["historical"], [])
        self.assertEqual(out["forecast"], [])
        self.assertEqual(
            out["metrics"], {"mae": None, "rmse": None, "mape": None})


class TestSeriesCleaning(unittest.TestCase):
    def test_duplicates_merged_and_gap_filled(self):
        rows = monthly_rows(8)
        rows.append(dict(rows[3]))  # duplicate timestamp
        rows.pop(5)  # missing month
        out = PredictionAgent().forecast(
            {"data": rows, "user_goal": "forecast amount"})
        diag = out["model_notes"].get("series_diagnostics", {})
        self.assertEqual(diag.get("duplicate_timestamps_merged"), 1)
        self.assertEqual(diag.get("missing_periods"), 1)
        self.assertEqual(diag.get("missing_periods_filled"), 1)
        # Continuous monthly axis restored: 8 history points, dated.
        self.assertEqual(len(out["historical"]), 8)
        self.assertTrue(all(DATE_RE.match(h["date"]) for h in out["historical"]))


class TestIntelligentSelection(unittest.TestCase):
    def test_little_history_uses_naive_family(self):
        out = PredictionAgent().forecast(
            {"data": monthly_rows(5), "user_goal": "forecast amount"})
        self.assertIn(out["model"], ("naive", "seasonal_naive", "mean", "drift"))
        self.assertIn("too little", out["model_notes"].get("shortlist_reason", ""))

    def test_seasonality_routes_to_seasonal(self):
        rows = monthly_rows(
            30, start_year=2022,
            fn=lambda i: 100 + 2 * i + 15 * np.sin(2 * np.pi * i / 12))
        out = PredictionAgent().forecast(
            {"data": rows, "user_goal": "forecast amount"})
        notes = out["model_notes"]
        self.assertTrue(notes["features"]["clear_seasonality"])
        self.assertIn("seasonality", notes.get("shortlist_reason", ""))
        self.assertIn(out["model"],
                      ("seasonal_naive", "holt_winters_additive", "auto_ets",
                       "sarima", "tbats", "theta", "holt_linear_damped"))

    def test_statement_cites_best_holdout(self):
        out = PredictionAgent().forecast(
            {"data": monthly_rows(12), "user_goal": "forecast amount"})
        self.assertIn(selection_mod.HOLDOUT_STATEMENT, out["selection_statement"])
        self.assertIn(out["model"], out["selection_statement"])

    def test_irregular_flagged_unreliable(self):
        vals = [100.0, 105.0, 98.0, 102.0, 99.0, 101.0, 2000.0,
                103.0, 97.0, 104.0, 100.0, 99.0, 1800.0, 101.0]
        rows = [{"d": f"2024-{m:02d}-01", "amount": v}
                for m, v in enumerate(vals, start=1)]
        out = PredictionAgent().forecast(
            {"data": rows, "user_goal": "forecast amount"})
        notes = out["model_notes"]
        self.assertTrue(notes["features"]["irregular"])
        self.assertIn("unreliable", out["selection_statement"].lower()
                      + notes.get("reliability_note", "").lower())

    def test_holdout_picks_best_on_holdout(self):
        values = np.array([100.0 + 2 * i for i in range(12)])
        ranking = backtest_competing(
            selection_mod._resolve(
                ["naive", "drift", "linear_trend"], 12, None), values, None)
        self.assertTrue(ranking)
        best = ranking[0]
        self.assertLessEqual(
            best["mape"] if best["mape"] is not None else float("inf"),
            ranking[-1]["mape"] if ranking[-1]["mape"] is not None else float("inf"))
        res = holdout_backtest(selection_mod._BY_NAME["linear_trend"], values, None)
        self.assertIsNotNone(res["mae"])
        self.assertIsNotNone(res["rmse"])
        self.assertEqual(res["holdout_points"], 3)

    def test_metrics_helpers(self):
        self.assertAlmostEqual(
            mape([100.0, 200.0], [110.0, 190.0]), 7.5)
        self.assertIsNone(mape([0.0, 0.0], [1.0, 2.0]))
        self.assertAlmostEqual(rmse([1.0, 2.0], [1.0, 2.0]), 0.0)
        self.assertIsNone(rmse([], []))


if __name__ == "__main__":
    unittest.main()
