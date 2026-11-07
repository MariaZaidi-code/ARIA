"""Smoke/contract tests for API routers that previously had no dedicated coverage."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)

PROTECTED_SAMPLES = [
    ("GET", "/api/dashboard/kpis"),
    ("GET", "/api/prescriptions/context"),
    ("POST", "/api/intelligence/explore"),
    ("GET", "/api/workspace/monitors"),
    ("POST", "/api/feedback"),
    ("GET", "/api/autocomplete"),
    ("GET", "/api/settings/providers"),
    ("POST", "/api/hypothesis"),
    ("POST", "/api/rl/feedback"),
    ("GET", "/api/data/summary"),
    ("GET", "/api/predictive/eligibility"),
    ("GET", "/api/copilot/suggestions"),
]


@pytest.mark.parametrize("method,path", PROTECTED_SAMPLES)
def test_protected_endpoint_requires_auth(method, path):
    r = client.request(method, path)
    assert r.status_code in (401, 403), (method, path, r.status_code, r.text[:200])


def test_openapi_lists_all_routers():
    schema = app_module.app.openapi()
    paths = set(schema["paths"].keys())
    expected_prefixes = [
        "/api/auth", "/api/connect", "/api/dashboard", "/api/predictive",
        "/api/prescriptions", "/api/insights", "/api/intelligence",
        "/api/workspace", "/api/feedback", "/api/autocomplete",
        "/api/schema", "/api/settings", "/api/verify",
        "/api/hypothesis", "/api/rl", "/api/data", "/api/copilot",
        "/api/suggestions", "/api/documents", "/api/export", "/api/integrations",
    ]
    for prefix in expected_prefixes:
        assert any(p.startswith(prefix) for p in paths), f"missing router prefix {prefix}"


def test_health_or_root_available():
    # Backend-only CI has no built frontend at root; use the liveness endpoint.
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json().get("ok") is True
