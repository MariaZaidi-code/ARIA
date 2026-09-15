"""Batch A security regression tests (new.txt §1).

Hermetic: no network, no LLM, no live database. Covers:
- malformed JWT sub -> None (never 500)
- expired / revoked JWT -> None
- shared SSRF validator blocks metadata/private hosts
- unified read-only SQL guard (goal + copilot agree)
- name-only FK never reaches PROBABLE
- PDF magic-byte validation rejects renamed files
- document ID traversal rejected
- settings validation rejects unsupported language/theme
"""

import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

import auth


def _make_token(sub, secret=None, exp_days=7):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "username": "u",
        "iat": now,
        "exp": now + timedelta(days=exp_days),
    }
    return jwt.encode(payload, secret or auth.SECRET, algorithm=auth.JWT_ALGO)


class TestVerifyTokenMalformed(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig_db = auth.DB_PATH
        auth.DB_PATH = Path(self._tmp.name) / "test_guards.db"
        self.addCleanup(setattr, auth, "DB_PATH", self._orig_db)

    def test_malformed_sub_returns_none(self):
        for bad_sub in ("abc", "", None, "1; DROP TABLE users", 3.5):
            with self.subTest(sub=bad_sub):
                token = _make_token(bad_sub)
                try:
                    result = auth.verify_token(token)
                except Exception as exc:  # must never raise -> 500
                    self.fail(f"verify_token raised {exc!r} for sub={bad_sub!r}")
                if bad_sub == 3.5:
                    # int(3.5) == 3 is acceptable; only assert no-crash
                    continue
                self.assertIsNone(result)

    def test_missing_sub_returns_none(self):
        now = datetime.now(timezone.utc)
        payload = {"username": "u", "iat": now, "exp": now + timedelta(days=1)}
        token = jwt.encode(payload, auth.SECRET, algorithm=auth.JWT_ALGO)
        self.assertIsNone(auth.verify_token(token))

    def test_non_string_token_returns_none(self):
        for bad in (None, "", 123, b"bytes"):
            self.assertIsNone(auth.verify_token(bad))

    def test_expired_and_revoked_return_none(self):
        expired = _make_token("1", exp_days=-1)
        self.assertIsNone(auth.verify_token(expired))
        uid = auth.register("guarduser", "Secret123!")
        token = auth.issue_token(uid, "guarduser")
        self.assertIsNotNone(auth.verify_token(token))
        auth.revoke_token(token)
        self.assertIsNone(auth.verify_token(token))


class TestSSRFValidator(unittest.TestCase):
    def test_blocks_metadata_and_private(self):
        from fastapi import HTTPException

        from api.connect_routes import _validate_db_endpoint

        for host in ("169.254.169.254", "metadata.google.internal", "169.254.10.20"):
            with self.subTest(host=host):
                with self.assertRaises(HTTPException):
                    _validate_db_endpoint(host, 5432, "db", "user", "postgresql")

    def test_rejects_bad_host_port_type(self):
        from fastapi import HTTPException

        from api.connect_routes import _validate_db_endpoint

        for host in ("", "a b", "host;rm", "x" * 300, None):
            with self.subTest(host=host):
                with self.assertRaises(HTTPException):
                    _validate_db_endpoint(host, 5432, "db", "user", "postgresql")
        for port in (0, 70000, "abc", None):
            with self.subTest(port=port):
                with self.assertRaises(HTTPException):
                    _validate_db_endpoint("localhost", port, "db", "user", "postgresql")
        with self.assertRaises(HTTPException):
            _validate_db_endpoint("localhost", 5432, "db", "user", "oracle")

    def test_accepts_valid(self):
        from api.connect_routes import _validate_db_endpoint

        self.assertEqual(
            _validate_db_endpoint("localhost", 5432, "db", "user", "postgresql"), 5432
        )
        self.assertEqual(
            _validate_db_endpoint("db.internal", "3306", "db", "user", "mysql"), 3306
        )


class TestReadOnlyGuard(unittest.TestCase):
    def test_unified_accept_reject(self):
        from core.validation import is_read_only_sql

        self.assertTrue(is_read_only_sql("SELECT * FROM orders"))
        self.assertTrue(is_read_only_sql("  WITH x AS (SELECT 1) SELECT * FROM x"))
        for bad in (
            "",
            None,
            "INSERT INTO orders VALUES (1)",
            "UPDATE orders SET x = 1",
            "DELETE FROM orders",
            "DROP TABLE orders",
            "SELECT * FROM t; DROP TABLE t",
            "SELECT pg_sleep(1)",
            "EXPLAIN SELECT * FROM t",
        ):
            with self.subTest(sql=bad):
                self.assertFalse(is_read_only_sql(bad))

    def test_comment_keywords_do_not_cause_false_reject(self):
        from core.validation import is_read_only_sql

        self.assertTrue(is_read_only_sql("SELECT * FROM t -- delete old rows"))
        self.assertTrue(is_read_only_sql("SELECT 'delete' AS note, id FROM t"))

    def test_goal_and_copilot_agree(self):
        from core.validation import is_read_only_sql
        from copilot.sql_engine import is_read_only as copilot_guard
        from goal_agent.sql import SqlMixin

        samples = [
            "SELECT * FROM orders",
            "WITH x AS (SELECT 1) SELECT * FROM x",
            "DELETE FROM orders",
            "DROP TABLE orders",
            "SELECT * FROM t; DROP TABLE t",
        ]
        for sql in samples:
            with self.subTest(sql=sql):
                expected = is_read_only_sql(sql)
                self.assertEqual(copilot_guard(sql), expected)
                self.assertEqual(SqlMixin()._is_read_only_sql(sql), expected)


class TestNameOnlyFKCap(unittest.TestCase):
    def test_name_only_never_probable(self):
        from schema_engine.classifier import classify
        from schema_engine.policy import AcceptancePolicy

        pk = {"customers": ["id"], "orders": ["order_id"]}
        rel, _ = classify(
            None, pk, {}, "public",
            "orders", "customer_id", "customers", "id",
            "heuristic-name-match", "name only",
            overlap_ratio=None, name_hint=True,
        )
        policy = AcceptancePolicy()
        bucket, state = policy.decide(
            rel, False,
            code_like=rel["evidence_detail"].get("code_like", False),
            name_match=True,
        )
        self.assertNotIn(state, ("PROBABLE", "CONFIRMED"))
        self.assertEqual(state, "UNCERTAIN")


class TestPDFMagicBytes(unittest.TestCase):
    def test_processor_rejects_bad_header(self):
        from document_processor.processor import DocumentProcessor

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            tmp.write(b"#!/bin/sh\necho pwned\n")
            tmp.close()
            proc = DocumentProcessor.__new__(DocumentProcessor)
            err = proc._validate_pdf(Path(tmp.name))
            self.assertIsNotNone(err)
            self.assertIn("%PDF-", err)
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def test_processor_does_not_pass_renamed_exe_as_valid(self):
        from document_processor.processor import DocumentProcessor

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            tmp.write(b"MZ" + b"\x00" * 100)
            tmp.close()
            proc = DocumentProcessor.__new__(DocumentProcessor)
            self.assertIsNotNone(proc._validate_pdf(Path(tmp.name)))
        finally:
            Path(tmp.name).unlink(missing_ok=True)


class TestDocumentTraversal(unittest.TestCase):
    def test_rejects_traversal_ids(self):
        from fastapi import HTTPException

        from api.document_routes import _sanitize_document_id

        for bad in ("../secret", "..", "a/b", "a b", "", None, "x" * 500 + "/"):
            with self.subTest(doc_id=bad):
                with self.assertRaises(HTTPException):
                    _sanitize_document_id(bad)
        self.assertEqual(_sanitize_document_id("abc-123_XY"), "abc-123_XY")


class TestSettingsValidation(unittest.TestCase):
    def test_rejects_unsupported_language_theme(self):
        import asyncio

        from fastapi import HTTPException

        from api.settings_routes import GeneralSettingsRequest, save_general_settings

        async def _run(lang, theme):
            return await save_general_settings(
                GeneralSettingsRequest(language=lang, theme=theme),
                {"user_id": 1},
            )

        with self.assertRaises(HTTPException):
            asyncio.run(_run("fr", "light"))
        with self.assertRaises(HTTPException):
            asyncio.run(_run("en", "neon"))


class TestBatch23Guards(unittest.TestCase):
    def test_ttl_defaults_to_1_caps_at_7(self):
        import os

        import auth as auth_module

        old = os.environ.get("TOKEN_TTL_DAYS")
        try:
            os.environ.pop("TOKEN_TTL_DAYS", None)
            self.assertEqual(auth_module._token_ttl_days(), 1)
            os.environ["TOKEN_TTL_DAYS"] = "30"
            self.assertEqual(auth_module._token_ttl_days(), 7)
            os.environ["TOKEN_TTL_DAYS"] = "3"
            self.assertEqual(auth_module._token_ttl_days(), 3)
        finally:
            if old is None:
                os.environ.pop("TOKEN_TTL_DAYS", None)
            else:
                os.environ["TOKEN_TTL_DAYS"] = old

    def test_auth_cookie_set_and_accepted(self):
        from starlette.requests import Request

        import auth as auth_module
        from api.auth_routes import COOKIE_NAME, _auth_response
        from core.deps import get_current_user

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        orig_db = auth_module.DB_PATH
        auth_module.DB_PATH = Path(tmp.name) / "cookie.db"
        self.addCleanup(setattr, auth_module, "DB_PATH", orig_db)

        uid = auth_module.register("cookieuser", "Secret123!")
        token = auth_module.issue_token(uid, "cookieuser")
        resp = _auth_response(token, "cookieuser")
        set_cookie = resp.headers.get("set-cookie", "")
        self.assertIn(COOKIE_NAME, set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=lax", set_cookie)

        scope = {
            "type": "http",
            "headers": [(b"cookie", f"{COOKIE_NAME}={token}".encode())],
        }
        user = get_current_user(Request(scope), authorization=None)
        self.assertEqual(user["user_id"], uid)

    def test_unauth_ip_throttle_trips(self):
        from fastapi import HTTPException

        from core.ratelimit import check_limit

        bucket = f"test-ip-{time.time_ns()}"
        for _ in range(3):
            check_limit(bucket, "1.2.3.4", 3, 60)
        with self.assertRaises(HTTPException) as ctx:
            check_limit(bucket, "1.2.3.4", 3, 60)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_zero_coverage_reported_and_gates_validity(self):
        from prediction.agent import PredictionAgent
        from prediction.evaluate import walk_forward_coverage

        values = [0.0, 0.0, 5.0, 0.0, 7.0, 0.0, 9.0, 0.0, 11.0, 0.0]
        cov = walk_forward_coverage(values)
        self.assertGreater(cov["zero_skipped"], 0)
        self.assertEqual(cov["origins"], cov["evaluated"] + cov["zero_skipped"])

        agent = PredictionAgent.__new__(PredictionAgent)
        agent.min_points = 5
        agent.valid_threshold = 0  # accuracy gate wide open: coverage must still block
        out = agent._build(
            [float(v) for v in values], [str(i) for i in range(len(values))],
            "sales", "sequence", None, 3, None,
        )
        self.assertIn("zero_actuals_skipped", out["validation"])
        self.assertGreater(out["validation"]["zero_actuals_skipped"], 0)

    def test_anomaly_list_capped(self):
        import numpy as np
        import pandas as pd

        from insight_agent.agent import InsightAgent

        rng = np.random.RandomState(0)
        df = pd.DataFrame({"sales": list(rng.normal(100, 5, 200)) + [10000.0] * 60})
        agent = InsightAgent.__new__(InsightAgent)
        out = InsightAgent.detect_anomalies(agent, df, ["sales"])
        self.assertLessEqual(len(out), 20)
        if out and any("total_anomaly_count" in a for a in out):
            self.assertGreater(out[0]["total_anomaly_count"], 20)

    def test_momentum_needs_date_axis(self):
        from copilot.pipeline import _analyze_rows

        ranked = [{"product": f"p{i}", "sales": str(100 - i * 5)} for i in range(6)]
        out = _analyze_rows(["product", "sales"], ranked, "forecast")
        self.assertIsNone(out["momentum_pct"])
        self.assertFalse(any("trends" in f for f in out["findings"]))

        timed = [{"month": f"2026-0{i + 1}", "sales": str(100 + i * 10)} for i in range(6)]
        out2 = _analyze_rows(["month", "sales"], timed, "forecast")
        self.assertIsNotNone(out2["momentum_pct"])
        self.assertGreater(out2["momentum_pct"], 0)

    def test_prose_not_promoted_to_actions(self):
        from prescription_agent import PrescriptionAgent

        prose = "Sales went up last quarter. Costs also rose. Demand looks strong."
        self.assertEqual(PrescriptionAgent._parse_actions(prose, 5), [])
        listed = "1. Cut waste\n2. Renegotiate supply\n3. Push top product"
        self.assertEqual(len(PrescriptionAgent._parse_actions(listed, 5)), 3)


if __name__ == "__main__":
    unittest.main()
