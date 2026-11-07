"""Shared helpers for the hermetic pipeline test suite.

No live PostgreSQL/MySQL is required: tests exercise the pipeline layers with a
ValueProfiler-shaped fake or with `profiler=None`, which the classifier and
evidence layers already support. Real-database regression coverage lives in
`benchmark_fk.py`.
"""

from types import SimpleNamespace
from unittest.mock import patch


def register_verified_email(client, email: str, password: str = "Secret123!"):
    """Register and verify an email with a mocked mail transport for API tests."""
    sent = {}
    with (
        patch(
            "auth.send_email_verification",
            side_effect=lambda recipient, token: sent.update(
                recipient=recipient, token=token
            ),
        ),
        patch("api.auth_routes._check_login_rate_limit"),
    ):
        response = client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
        if response.status_code == 200 and sent.get("token"):
            verified = client.post(
                "/api/auth/verify-email", json={"token": sent["token"]}
            )
            if verified.status_code != 200:
                raise AssertionError(
                    f"Email verification failed: {verified.status_code} {verified.text[:200]}"
                )
            login = client.post(
                "/api/auth/login", json={"email": email, "password": password}
            )
            if login.status_code != 200:
                raise AssertionError(
                    f"Verified email login failed: {login.status_code} {login.text[:200]}"
                )
    return response


def fake_profiler(src=None, rows=100, hit=None, exact_hit=None,
                  exhausted=False, types_ok=True, pk_index=None):
    """ValueProfiler-shaped fake.

    `src`: {(table, col): set of type-tagged values} fed to source_values().
    `hit`: the 5-tuple `(target_table, target_col, ratio, matched, ambiguous)`
           returned by strongest_overlap() (the "SAMPLED" path).
    `exact_hit`: the 5-tuple returned by strongest_exact_overlap() (the
           "EXACT" verification path).
    `exhausted`: whether the profiling budget is spent (PART 8 truthfulness).
    `types_ok`: value returned by types_compatible().
    `pk_index`: [(table, pk_col, set-of-values), ...]; the target pool.
    """
    src = src or {}
    pk_index = pk_index or []

    class _Fake:
        MIN_OVERLAP = 0.85
        MAX_SAMPLE = 500

        def __init__(self):
            self.budget = SimpleNamespace(exhausted=exhausted, used=0, remaining=400)
            self.sole_key_tables = set()
            self.pk_index = pk_index
            self.schema = "public"
            self.db_type = "postgresql"

        def source_values(self, table, col):
            return src.get((table, col))

        def _pk_values(self, table):
            for t, _pk, tset in self.pk_index:
                if t == table:
                    return tset
            return set()

        def row_count(self, table):
            return rows

        def types_compatible(self, *args):
            return types_ok

        def column_type(self, table, col):
            return "integer"

        def should_profile(self, col):
            return True

        def strongest_overlap(self, src_set, **kwargs):
            return hit

        def strongest_exact_overlap(self, *args, **kwargs):
            return exact_hit

        def quote(self, name):
            return '"' + str(name).replace('"', "") + '"'

    return _Fake()