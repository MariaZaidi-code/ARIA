"""API-level tests: auth flow, SQLite hypothesis path, prediction gating.

Hermetic: auth uses a temp DB (monkeypatched), hypothesis/prediction are
pure-math helpers on temp data. No network, no LLM, no live database.
"""

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import auth


class TestAuthFlow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig_db = auth.DB_PATH
        auth.DB_PATH = Path(self._tmp.name) / "test_auth.db"
        self.addCleanup(setattr, auth, "DB_PATH", self._orig_db)

    def test_register_login_me(self):
        from fastapi.testclient import TestClient
        import app as app_module

        c = TestClient(app_module.app, raise_server_exceptions=False)
        user = f"apitest_{int(time.time() * 1000) % 1000000}"
        r = c.post("/api/auth/register", json={"username": user, "password": "Secret123!"})
        self.assertEqual(r.status_code, 200, r.text[:200])
        token = r.json()["token"]
        self.assertTrue(token)

        r = c.post("/api/auth/login", json={"username": user, "password": "Secret123!"})
        self.assertEqual(r.status_code, 200)

        r = c.post("/api/auth/login", json={"username": user, "password": "wrong"})
        self.assertEqual(r.status_code, 401)

        r = c.post("/api/auth/register", json={"username": user, "password": "Secret123!"})
        self.assertEqual(r.status_code, 400)

        r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["username"], user)

        r = c.get("/api/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_ttl_env_parsing(self):
        import importlib
        import os

        os.environ["TOKEN_TTL_DAYS"] = "1"
        try:
            self.assertEqual(auth._token_ttl_days(), 1)
        finally:
            del os.environ["TOKEN_TTL_DAYS"]
        self.assertEqual(auth._token_ttl_days(), 7)


class TestHypothesisSqlite(unittest.TestCase):
    def _make_engine(self, stmts, table="sales"):
        from sqlalchemy import create_engine

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        for s in stmts:
            conn.execute(s)
        conn.commit()
        conn.close()
        engine = create_engine(f"sqlite:///{tmp.name}")

        def _cleanup(path=tmp.name, eng=engine):
            try:
                eng.dispose()
            finally:
                Path(path).unlink(missing_ok=True)

        self.addCleanup(_cleanup)
        return engine

    def _sales_engine(self, n=30):
        stmts = ["CREATE TABLE sales (order_id INTEGER, amount REAL, qty INTEGER)"]
        stmts += [
            f"INSERT INTO sales VALUES ({i}, {100.0 + i * 2.0}, {i % 5 + 1})"
            for i in range(1, n + 1)
        ]
        return self._make_engine(stmts)

    def test_sqlite_tables_and_pairs(self):
        from api import hypothesis_routes as hyp

        engine = self._sales_engine()
        with engine.connect() as conn:
            tables = hyp._get_tables(conn, "sqlite")
            self.assertIn("sales", tables)
            pairs = hyp._find_numeric_pairs(conn, tables, "sqlite")
            # order_id is id-like and excluded; amount+qty must pair up.
            flat = [(x, y) for x, y, _ in pairs]
            self.assertIn(("amount", "qty"), flat)

    def test_run_test_honest_verdict(self):
        from api import hypothesis_routes as hyp

        engine = self._sales_engine()
        req = SimpleNamespace(hypothesis="higher quantity means higher amount")
        out = hyp._run_test(engine, "sqlite", req)
        self.assertTrue(out["ok"])
        self.assertIn("supported", out)
        self.assertIn("stats", out)
        self.assertGreaterEqual(len(out["scatter_data"]), 10)

    def test_run_test_insufficient_data(self):
        from api import hypothesis_routes as hyp

        engine = self._make_engine(
            ["CREATE TABLE tiny (a REAL, b REAL)", "INSERT INTO tiny VALUES (1.0, 2.0)"]
        )
        req = SimpleNamespace(hypothesis="a relates to b")
        out = hyp._run_test(engine, "sqlite", req)
        self.assertFalse(out["ok"])
        self.assertIn("detail", out)


class TestPredictionGating(unittest.TestCase):
    def test_empty_refuses(self):
        from prediction.agent import PredictionAgent

        out = PredictionAgent().forecast({"data": []})
        self.assertFalse(out["valid"])

    def test_trending_series_valid(self):
        from prediction.agent import PredictionAgent

        rows = [{"d": f"2024-{m:02d}-01", "amount": 100.0 + m * 10.0} for m in range(1, 13)]
        out = PredictionAgent().forecast({"data": rows, "user_goal": "forecast amount"})
        self.assertIn("valid", out)
        if out["valid"]:
            self.assertTrue(out.get("points"))

    def test_id_only_refuses(self):
        from prediction.agent import PredictionAgent

        rows = [{"order_id": i} for i in range(10)]
        out = PredictionAgent().forecast({"data": rows})
        self.assertFalse(out["valid"])


if __name__ == "__main__":
    unittest.main()
