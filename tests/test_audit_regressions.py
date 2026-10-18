"""Regression coverage for issues found in the current codebase audit."""

from pathlib import Path

import auth
from core import config
from services import intelligence_service as intel


def test_token_verification_fails_closed_when_revocation_store_is_unavailable(monkeypatch):
    monkeypatch.setattr(auth, "_REVOKE_CACHE", {})
    token = auth.issue_token(902341, "audit-regression", ttl_days=1)
    monkeypatch.setattr(auth, "_get_db", lambda: (_ for _ in ()).throw(OSError("offline")))

    assert auth.verify_token(token) is None
    assert auth._REVOKE_CACHE == {}


def test_session_save_keeps_api_path_working_if_disk_persistence_fails(monkeypatch, tmp_path):
    user_id = 902342
    previous = config.SESSION_STORE.pop(user_id, None)
    monkeypatch.setattr(config, "_ensure_user_paths", lambda *_args: None)
    monkeypatch.setattr(config, "SESSION_STORE_PATH", Path(tmp_path) / "sessions.json")
    monkeypatch.setattr(
        config, "_atomic_write_text",
        lambda *_args: (_ for _ in ()).throw(PermissionError("read-only")),
    )
    monkeypatch.setattr(config, "_redis_save_one", lambda *_args: None)

    try:
        config.save_session(user_id, {"provider_name": "local"})
        assert config.SESSION_STORE[user_id][1]["provider_name"] == "local"
    finally:
        config.SESSION_STORE.pop(user_id, None)
        if previous is not None:
            config.SESSION_STORE[user_id] = previous


def test_engine_pool_stays_bounded_after_repeated_borrows(monkeypatch):
    class FakeEngine:
        def __init__(self):
            self.disposed = False

        def dispose(self):
            self.disposed = True

    created = []

    def make_engine(*_args, **_kwargs):
        engine = FakeEngine()
        created.append(engine)
        return engine

    monkeypatch.setattr(intel, "_ENGINE_POOL", {})
    monkeypatch.setattr("sqlalchemy.create_engine", make_engine)

    for index in range(intel._ENGINE_POOL_MAX + 8):
        intel._pooled_engine(f"sqlite:///audit-{index}.db")

    assert len(intel._ENGINE_POOL) == intel._ENGINE_POOL_MAX
    assert sum(engine.disposed for engine in created) == 8
