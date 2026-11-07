"""RL feedback routes (api/rl_routes.py): popup reward mapping, status, rank.

Covers the model-ready RL contract:
- auth is required (401) on every /api/rl route;
- POST /api/rl/feedback validates 1-5 star input and maps it linearly to a
  reward in [-1, +1], capping the stored comment;
- GET /api/rl/status reports the replaceable baseline policy and aggregates
  reward directions from recorded events;
- POST /api/rl/rank ranks only caller-supplied candidates through the active
  policy and enforces request bounds.
"""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class TestRLFeedbackRoutes(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        import auth
        self._orig_db = auth.DB_PATH
        auth.DB_PATH = Path(self._tmp.name) / "test_auth.db"
        self.addCleanup(setattr, auth, "DB_PATH", self._orig_db)

    def _client(self):
        from fastapi.testclient import TestClient
        import app as app_module
        return TestClient(app_module.app, raise_server_exceptions=False,
                           headers={"Origin": "http://127.0.0.1:8000"})

    def _register(self, c):
        user = f"rl_fb_{int(time.time() * 1000) % 100000000}@example.test"
        from helpers import register_verified_email
        r = register_verified_email(c, user)
        self.assertEqual(r.status_code, 200, r.text[:200])
        return user

    def _authed_client(self):
        # Explicit local-HTTP dev opt-out: TestClient runs over plain HTTP,
        # so Secure cookies would not round-trip without this.
        prev = os.environ.get("ARIA_COOKIE_SECURE")
        os.environ["ARIA_COOKIE_SECURE"] = "0"
        self.addCleanup(
            lambda: os.environ.pop("ARIA_COOKIE_SECURE", None)
            if prev is None else os.environ.__setitem__("ARIA_COOKIE_SECURE", prev)
        )
        c = self._client()
        self._register(c)
        return c

    def test_rl_routes_require_auth(self):
        c = self._client()
        self.assertEqual(c.post("/api/rl/feedback", json={"rating": 5}).status_code, 401)
        self.assertEqual(c.get("/api/rl/status").status_code, 401)
        self.assertEqual(c.post("/api/rl/rank", json={"candidates": []}).status_code, 401)

    def test_popup_feedback_reward_mapping_and_validation(self):
        c = self._authed_client()

        r = c.post("/api/rl/feedback", json={"rating": 5, "comment": "great", "page": "dashboard"})
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertAlmostEqual(r.json()["reward"], 1.0)

        r = c.post("/api/rl/feedback", json={"rating": 1})
        self.assertAlmostEqual(r.json()["reward"], -1.0)
        r = c.post("/api/rl/feedback", json={"rating": 3})
        self.assertAlmostEqual(r.json()["reward"], 0.0)

        # Out-of-range ratings are rejected (422), never stored.
        self.assertEqual(c.post("/api/rl/feedback", json={"rating": 0}).status_code, 422)
        self.assertEqual(c.post("/api/rl/feedback", json={"rating": 6}).status_code, 422)
        self.assertEqual(c.post("/api/rl/feedback", json={}).status_code, 422)

        # Comment is capped server-side; event carries the reward label.
        r = c.post("/api/rl/feedback", json={"rating": 4, "comment": "x" * 1000})
        self.assertEqual(r.status_code, 200)
        ev = c.get("/api/rl/events?limit=1").json()["events"][-1]
        self.assertEqual(ev["event"], "popup_feedback")
        self.assertLessEqual(len(ev["outcome"]["comment"]), 500)
        self.assertEqual(ev["reward"]["label"], "positive")
        self.assertAlmostEqual(ev["reward"]["value"], 0.5)
        self.assertEqual(ev["action"]["value"], 4)

    def test_status_reports_baseline_policy_and_reward_summary(self):
        c = self._authed_client()
        c.post("/api/rl/feedback", json={"rating": 5})
        c.post("/api/rl/feedback", json={"rating": 2})
        c.post("/api/rl/feedback", json={"rating": 3})

        body = c.get("/api/rl/status").json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["policy"]["name"], "baseline-v1")
        self.assertTrue(body["policy"]["replaceable"])
        self.assertIsNone(body["model"])  # no trained model yet
        self.assertGreaterEqual(body["events_seen"], 3)
        self.assertGreaterEqual(body["reward_summary"]["positive"], 1)
        self.assertGreaterEqual(body["reward_summary"]["negative"], 1)
        self.assertGreaterEqual(body["reward_summary"]["neutral"], 1)
        self.assertIsNotNone(body["last_event_ts"])

    def test_rank_orders_candidates_and_enforces_bounds(self):
        c = self._authed_client()
        r = c.post("/api/rl/rank", json={
            "candidates": [
                {"id": "a", "score": 1.0},
                {"id": "b", "score": 2.0},
                {"id": "c", "score": 0.5},
            ],
            "state": {"page": "dashboard"},
        })
        self.assertEqual(r.status_code, 200, r.text[:200])
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["policy"], "baseline-v1")
        self.assertEqual([cand["id"] for cand in body["ordered"]], ["b", "a", "c"])
        self.assertFalse(body["fallback"])

        # Route-level contract is strict: every candidate must be a dict
        # (pre-validated only). Non-dict items -> 422, never promoted.
        self.assertEqual(
            c.post("/api/rl/rank", json={"candidates": ["bad", {"id": "x", "score": 1}]}).status_code,
            422,
        )

        # Malformed shape -> 422; oversized batch -> 400.
        self.assertEqual(c.post("/api/rl/rank", json={"candidates": "nope"}).status_code, 422)
        big = {"candidates": [{"id": str(i), "score": i} for i in range(201)]}
        self.assertEqual(c.post("/api/rl/rank", json=big).status_code, 400)


if __name__ == "__main__":
    unittest.main()
