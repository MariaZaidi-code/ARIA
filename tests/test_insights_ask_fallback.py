"""Regression: POST /api/insights/{id}/ask without a card payload.

The id-only contract regenerates insights server-side and id-matches the
target card. A function-local ``import time`` inside ask_about_insight made
the earlier ``time.time()`` an UnboundLocalError, so this documented
fallback crashed with 500 while the frontend's cheap path (posting the full
card) kept the defect invisible.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import insights_routes

USER = {"user_id": 902502, "username": "asktester",
        "email": "asktester@example.test"}
TARGET = {"id": "ins-target-1", "title": "Revenue dip in Q3",
          "description": "Revenue fell versus Q2."}


class InsightAskIdOnlyFallbackTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="aria_ask_"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))

        db = tmp / "ask.sqlite"
        db.touch()
        schema = tmp / "schema.json"
        schema.write_text(json.dumps({"tables": {}}), encoding="utf-8")

        self.session = {
            "user_id": USER["user_id"],
            "db_name": "asktest",
            "db_type": "sqlite",
            "db_uri": f"sqlite:///{db.as_posix()}",
            "db": {"dialect_ok": True},
            "schema_path": str(schema),
            "schemas": [],
            "provider": None,
            "api_keys": {},
        }

        app = FastAPI()
        app.include_router(insights_routes.router)
        app.dependency_overrides[insights_routes.require_writable] = (
            lambda: USER
        )
        self.client = TestClient(app)

        # Keep artifact writes inside the temp dir.
        self._orig_processed = insights_routes.PROCESSED_DIR
        insights_routes.PROCESSED_DIR = tmp / "processed"
        self.addCleanup(setattr, insights_routes, "PROCESSED_DIR",
                        self._orig_processed)

    def test_id_only_ask_does_not_crash(self):
        with (
            patch("core.config.get_session", return_value=self.session),
            patch.object(insights_routes.InsightsEngine,
                         "generate_all_insights",
                         return_value=[dict(TARGET)]),
            patch("goal_agent.agent.GoalAgent") as agent_cls,
            patch("goal_agent.schema.load_user_overrides",
                  return_value={"pk": {}, "fk": {}, "rejected": []}),
        ):
            agent_cls.return_value.process_goal.return_value = {
                "sql_used": "SELECT 1", "rows": [],
            }
            r = self.client.post(
                "/api/insights/ins-target-1/ask",
                json={"question": "Why did revenue dip?"},
            )
        self.assertEqual(r.status_code, 200, r.text[:300])
        body = r.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("insight_id"), "ins-target-1")

    def test_card_payload_short_circuits_regeneration(self):
        with (
            patch("core.config.get_session", return_value=self.session),
            patch.object(insights_routes.InsightsEngine,
                         "generate_all_insights") as generate,
            patch("goal_agent.agent.GoalAgent") as agent_cls,
            patch("goal_agent.schema.load_user_overrides",
                  return_value={"pk": {}, "fk": {}, "rejected": []}),
        ):
            agent_cls.return_value.process_goal.return_value = {"ok": True}
            r = self.client.post(
                "/api/insights/ins-target-1/ask",
                json={"question": "Why?", "insight": dict(TARGET)},
            )
        self.assertEqual(r.status_code, 200, r.text[:300])
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
