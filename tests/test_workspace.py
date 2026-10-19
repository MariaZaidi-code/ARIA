"""Workspace routes (api/workspace_routes.py, export, integrations).

Covers the monitor / target / glossary / inbox surface:
- every workspace route requires auth; writes require a writable session;
- NL monitor text parses into (condition, cadence), check-now evaluates the
  stored query and records a run;
- targets/glossary bulk-save; glossary rewrites ask questions;
- notifications inbox (list/read/clear) and webhook delivery never raise;
- Slack command token flow resolves the user; unanswered loopback degrades
  to a friendly message;
- story export renders pptx/xlsx/print-HTML from the posted envelope.
"""

import os
import sqlite3
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE orders (region TEXT, month TEXT, revenue REAL)")
        conn.executemany(
            "INSERT INTO orders VALUES (?, ?, ?)",
            [("North", "1998-01", 100.0), ("North", "1998-02", 80.0),
             ("North", "1998-03", 50.0), ("South", "1998-01", 70.0),
             ("South", "1998-02", 90.0), ("South", "1998-03", 60.0),
             ("East", "1998-01", 40.0), ("East", "1998-02", 45.0),
             ("East", "1998-03", 44.0)],
        )
        conn.commit()
    finally:
        conn.close()


_SQL = "SELECT month, SUM(revenue) AS revenue FROM orders GROUP BY month ORDER BY month"


class TestWorkspaceRoutes(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        import auth
        self._orig_db = auth.DB_PATH
        auth.DB_PATH = self.tmp / "test_auth.db"
        self.addCleanup(setattr, auth, "DB_PATH", self._orig_db)

        from core import config
        self._orig_users_dir = config.USERS_DIR
        config.USERS_DIR = self.tmp / "users"
        config.USERS_DIR.mkdir(parents=True, exist_ok=True)
        self.addCleanup(setattr, config, "USERS_DIR", self._orig_users_dir)

        self.db_path = self.tmp / "orders.db"
        _make_db(self.db_path)
        self.db_uri = f"sqlite:///{self.db_path.as_posix()}"

    def _client(self):
        from fastapi.testclient import TestClient
        import app as app_module
        return TestClient(app_module.app, raise_server_exceptions=False,
                           headers={"Origin": "http://127.0.0.1:8000"})

    def _user_id(self, username: str) -> int:
        import auth
        conn = auth._get_db()
        try:
            row = conn.execute("SELECT id FROM users WHERE username = ?",
                               (username,)).fetchone()
            return int(row["id"])
        finally:
            conn.close()

    def _authed_client(self):
        prev = os.environ.get("ARIA_COOKIE_SECURE")
        os.environ["ARIA_COOKIE_SECURE"] = "0"
        self.addCleanup(
            lambda: os.environ.pop("ARIA_COOKIE_SECURE", None)
            if prev is None else os.environ.__setitem__("ARIA_COOKIE_SECURE", prev)
        )
        c = self._client()
        user = f"ws_{int(time.time() * 1000) % 100000000}"
        r = c.post("/api/auth/register",
                   json={"username": user, "password": "Secret123!"})
        self.assertEqual(r.status_code, 200, r.text[:200])
        return c, self._user_id(user)

    def _session_patch(self):
        return patch("core.config.get_session",
                     lambda uid=None: {"db_uri": self.db_uri,
                                       "source_type": "semi-structured"})

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def test_workspace_routes_require_auth(self):
        c = self._client()
        self.assertEqual(c.get("/api/workspace/monitors").status_code, 401)
        self.assertEqual(c.get("/api/workspace/targets").status_code, 401)
        self.assertEqual(c.get("/api/workspace/glossary").status_code, 401)
        self.assertEqual(c.get("/api/workspace/notifications").status_code, 401)
        self.assertEqual(c.get("/api/workspace/webhooks").status_code, 401)
        self.assertEqual(c.get("/api/workspace/integrations").status_code, 401)
        self.assertEqual(c.post("/api/export/story",
                                json={"format": "html"}).status_code, 401)

    # ------------------------------------------------------------------
    # Monitors
    # ------------------------------------------------------------------

    def test_monitor_text_parsing(self):
        c, _uid = self._authed_client()

        def preview(text):
            r = c.post("/api/workspace/monitors/preview", json={"text": text})
            self.assertEqual(r.status_code, 200, r.text[:200])
            return r.json()

        p = preview("tell me when revenue drops more than 10% week over week")
        self.assertTrue(p["matched"])
        self.assertEqual(p["condition"]["type"], "drops_pct")
        self.assertEqual(p["condition"]["value"], 10.0)
        self.assertEqual(p["cadence"], "weekly")

        p = preview("alert me if orders rise 5% hourly")
        self.assertEqual(p["condition"]["type"], "rises_pct")
        self.assertEqual(p["cadence"], "hourly")

        p = preview("notify me when revenue goes above 5K")
        self.assertEqual(p["condition"]["type"], "above")
        self.assertEqual(p["condition"]["value"], 5000.0)
        self.assertEqual(p["cadence"], "daily")

        p = preview("ping me if revenue falls below $1,200")
        self.assertEqual(p["condition"]["type"], "below")
        self.assertEqual(p["condition"]["value"], 1200.0)

        p = preview("just keep an eye on things")
        self.assertFalse(p["matched"])

    def test_monitor_create_check_and_notify(self):
        c, _uid = self._authed_client()

        # Unparseable condition text -> 422.
        self.assertEqual(c.post("/api/workspace/monitors", json={
            "name": "x", "sql": _SQL, "condition_text": "watch it"}).status_code, 422)

        r = c.post("/api/workspace/monitors", json={
            "name": "Revenue drop watch",
            "question": "monthly revenue",
            "sql": _SQL,
            "condition": {"type": "drops_pct", "value": 10},
            "cadence": "manual",
            "measure_column": "revenue",
            "time_column": "month",
        })
        self.assertEqual(r.status_code, 200, r.text[:200])
        mon = r.json()["item"]

        with self._session_patch():
            r = c.post(f"/api/workspace/monitors/{mon['id']}/check")
        self.assertEqual(r.status_code, 200, r.text[:200])
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["triggered"])  # 154 vs 190 -> -18.9% <= -10%
        self.assertIn("condition met", body["message"])

        # Trigger wrote an inbox notification.
        inbox = c.get("/api/workspace/notifications").json()
        self.assertGreaterEqual(inbox["unread"], 1)
        self.assertEqual(inbox["items"][-1]["kind"], "monitor")

        # Run history recorded on the monitor; disable via PATCH.
        body = c.get("/api/workspace/monitors").json()
        m = body["items"][0]
        self.assertEqual(m["last_status"], "triggered")
        self.assertGreaterEqual(m["run_count"], 1)
        self.assertEqual(len(m["runs"]), 1)

        r = c.patch(f"/api/workspace/monitors/{mon['id']}", json={"enabled": False})
        self.assertFalse(r.json()["item"]["enabled"])

        self.assertEqual(c.delete(f"/api/workspace/monitors/{mon['id']}").status_code, 200)
        self.assertEqual(c.get("/api/workspace/monitors").json()["total"], 0)
        self.assertEqual(
            c.post(f"/api/workspace/monitors/{mon['id']}/check").status_code, 404)

    # ------------------------------------------------------------------
    # Targets + glossary
    # ------------------------------------------------------------------

    def test_targets_and_glossary_bulk_save(self):
        c, uid = self._authed_client()

        r = c.put("/api/workspace/targets", json={"targets": [
            {"metric": "Revenue", "target": 150, "direction": "above"},
            {"metric": "bad"},  # dropped (no target value)
        ]})
        self.assertEqual(r.status_code, 200)
        items = r.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target"], 150.0)
        self.assertEqual(c.get("/api/workspace/targets").json()["total"], 1)

        r = c.put("/api/workspace/glossary", json={"entries": [
            {"term": "sales", "maps_to": "revenue"},
            {"term": "north", "maps_to": "region = 'North'"},
        ]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/api/workspace/glossary").json()["total"], 2)

        # apply_glossary (unit level): rewrites recognized terms only.
        from services.workspace_service import apply_glossary
        rewritten, applied = apply_glossary(uid, "what were sales in the north last month?")
        self.assertEqual(rewritten, "what were revenue in the region = 'North' last month?")
        self.assertIn("sales", applied)

    # ------------------------------------------------------------------
    # Notifications + webhooks
    # ------------------------------------------------------------------

    def test_webhook_delivery_pins_validated_dns_result(self):
        from services import workspace_service as ws
        import socket

        ws._save(123456, "webhooks.json", [{
            "id": "dns-rebind",
            "url": "https://hooks.example.test/webhook",
            "kind": "generic",
            "name": "DNS rebind test",
        }])
        public_answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                          ("8.8.8.8", 443))]
        private_answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                           ("127.0.0.1", 443))]
        real_adapter = ws._pinned_webhook_adapter
        adapters = []

        def capture_adapter(hostname, port, address):
            adapter = real_adapter(hostname, port, address)
            adapters.append(adapter)
            return adapter

        with patch("services.workspace_service.socket.getaddrinfo",
                   side_effect=[public_answer, private_answer]) as resolve, \
                patch("services.workspace_service._pinned_webhook_adapter",
                      side_effect=capture_adapter), \
                patch("requests.Session.post") as post:
            post.return_value.status_code = 204
            post.return_value.close.return_value = None
            outcomes = ws.deliver_webhooks(123456, "title", "body")

            self.assertEqual(outcomes[0]["status"], "ok")
            # The sender resolves once and uses that numeric address for the
            # connection even if the hostname would later resolve privately.
            resolve.assert_called_once()
            target = post.call_args.args[0]
            self.assertEqual(target, "https://hooks.example.test/webhook")
            self.assertEqual(post.call_args.kwargs["headers"]["Host"],
                             "hooks.example.test")
            import requests
            adapter = adapters[0]
            request = requests.Request("POST", target).prepare()
            pool = adapter.get_connection_with_tls_context(
                request, verify=True, proxies={}
            )
            self.assertEqual(pool.host, "8.8.8.8")
            self.assertEqual(pool.assert_hostname, "hooks.example.test")
            self.assertEqual(pool.conn_kw["server_hostname"], "hooks.example.test")

    def test_notifications_inbox_and_webhook_delivery_never_raises(self):
        c, _uid = self._authed_client()

        self.assertEqual(c.get("/api/workspace/notifications").json()["unread"], 0)

        # Invalid and private-network URLs are rejected (SSRF guard).
        self.assertEqual(c.post("/api/workspace/webhooks",
                                json={"url": "not-a-url"}).status_code, 422)
        r = c.post("/api/workspace/webhooks",
                   json={"name": "Slack", "url": "http://127.0.0.1:9/hook"})
        self.assertEqual(r.status_code, 422, r.text[:200])
        # Old stored hooks are revalidated at delivery time too.
        from services import workspace_service as ws
        legacy = {"id": "legacy-private", "url": "http://127.0.0.1:9/hook",
                  "kind": "generic", "name": "Legacy"}
        ws._save(_uid, "webhooks.json", [legacy])
        self.assertFalse(c.post("/api/workspace/webhooks/legacy-private/test")
                         .json()["ok"])
        self.assertEqual(c.post("/api/workspace/webhooks/nope/test").status_code, 404)

        # Populate the inbox directly via the service, then mark read/clear.
        me = c.get("/api/auth/me").json()
        uid = int(me["user_id"])
        ws.add_notification(uid, {"kind": "monitor", "title": "t", "message": "m"})
        ws.add_notification(uid, {"kind": "info", "title": "t2", "message": "m2"})
        inbox = c.get("/api/workspace/notifications").json()
        self.assertEqual(inbox["unread"], 2)

        r = c.post("/api/workspace/notifications/read", json={"all": True})
        self.assertEqual(r.json()["unread"], 0)

        self.assertEqual(c.delete("/api/workspace/notifications").status_code, 200)
        self.assertEqual(c.get("/api/workspace/notifications").json()["total"], 0)

        self.assertEqual(c.delete("/api/workspace/webhooks/legacy-private").status_code, 200)

    # ------------------------------------------------------------------
    # Slack integration
    # ------------------------------------------------------------------

    def test_slack_token_flow(self):
        c, _uid = self._authed_client()

        self.assertFalse(c.get("/api/workspace/integrations").json()["data"]["slack_configured"])

        r = c.post("/api/workspace/integrations",
                   json={"regenerate_slack_token": True})
        token = r.json()["data"]["slack_command_token"]
        self.assertGreaterEqual(len(token), 20)
        # The reveal response returns the token separately and keeps it out of
        # URLs so browser history, proxy logs, and referrers cannot expose it.
        self.assertNotIn("token=" + token, r.json()["data"]["slack_command_url"])

        # Masked in the read path — the secret must never appear in a status GET.
        data = c.get("/api/workspace/integrations").json()["data"]
        self.assertTrue(data["slack_configured"])
        self.assertNotEqual(data["slack_command_token"], token)
        self.assertNotIn(token, data["slack_command_url"])
        self.assertNotIn("token=", data["slack_command_url"])

        # Wrong token -> 401.
        r = c.post("/api/integrations/slack/command",
                   data={"token": "wrong", "text": "hi"})
        self.assertEqual(r.status_code, 401)

        # Empty text -> help, ephemeral.
        r = c.post("/api/integrations/slack/command",
                   data={"token": token, "text": ""})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["response_type"], "ephemeral")

        # With a question, the bot answers through /api/ask (stubbed here to
        # keep the test hermetic; the wiring returns the summary text).
        with patch("api.integrations_routes._ask_sync",
                   return_value="*q*\n> stub answer"):
            r = c.post("/api/integrations/slack/command",
                       data={"token": token, "text": "why did revenue drop?"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["response_type"], "in_channel")
        self.assertIn("stub answer", r.json()["text"])

    # ------------------------------------------------------------------
    # Story export
    # ------------------------------------------------------------------

    ENVELOPE = {
        "question": "Why did revenue drop in March?",
        "answer": "Revenue fell 19% from February to March.",
        "story": "Revenue trended down over the quarter.",
        "why": "Most of the fall is concentrated in the North.",
        "hypothesis": "North region demand softened.",
        "drivers": [{"label": "North", "value": 50.0, "delta": -30.0,
                     "contribution_pct": 62.5, "basis": "change"},
                    {"label": "South", "value": 60.0, "delta": -30.0,
                     "contribution_pct": 37.5, "basis": "change"}],
        "columns": ["month", "revenue"],
        "rows": [{"month": "1998-01", "revenue": 190.0},
                 {"month": "1998-02", "revenue": 190.0},
                 {"month": "1998-03", "revenue": 154.0}],
        "sql": _SQL,
        "as_of": "2026-01-01T00:00:00+00:00",
        "include_sql": True,
    }

    def test_export_story_formats(self):
        c, _uid = self._authed_client()

        r = c.post("/api/export/story", json={**self.ENVELOPE, "format": "pptx"})
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertIn("presentationml", r.headers["content-type"])
        self.assertTrue(r.content.startswith(b"PK"))
        self.assertIn("attachment", r.headers.get("content-disposition", ""))

        r = c.post("/api/export/story", json={**self.ENVELOPE, "format": "xlsx"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r.headers["content-type"])
        self.assertTrue(r.content.startswith(b"PK"))

        r = c.post("/api/export/story", json={**self.ENVELOPE, "format": "html"})
        self.assertEqual(r.status_code, 200)
        body = r.text
        self.assertIn("Why did revenue drop in March?", body)
        self.assertIn("62.5", body)  # driver contribution bar
        self.assertIn("Underlying query", body)

        self.assertEqual(c.post("/api/export/story",
                                json={"format": "pdf"}).status_code, 422)

    def test_xlsx_export_keeps_formula_like_user_text_literal(self):
        from io import BytesIO
        from openpyxl import load_workbook

        c, _uid = self._authed_client()
        payload = {
            **self.ENVELOPE,
            "format": "xlsx",
            "question": "=1+1",
            "columns": ["=header"],
            "rows": [{"=header": "=1+1"}],
        }
        response = c.post("/api/export/story", json=payload)
        self.assertEqual(response.status_code, 200, response.text[:200])

        workbook = load_workbook(BytesIO(response.content), data_only=False)
        summary = workbook["Summary"]
        data = workbook["Data"]
        self.assertEqual(summary["B5"].value, "=1+1")
        self.assertEqual(summary["B5"].data_type, "s")
        self.assertEqual(data["A1"].value, "=header")
        self.assertEqual(data["A1"].data_type, "s")
        self.assertEqual(data["A2"].value, "=1+1")
        self.assertEqual(data["A2"].data_type, "s")


if __name__ == "__main__":
    unittest.main()
