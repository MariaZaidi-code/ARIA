"""Shared pytest setup."""
import pytest


@pytest.fixture(autouse=True)
def _document_metadata_on_files(monkeypatch):
    """Keep document metadata in each test's temp folder.

    With ARIA_RAG_DATABASE_URL in .env the app would store metadata in
    PostgreSQL, so tests would leak rows into a real database and share state
    across tmp_path. Tests that exercise the PostgreSQL backend opt in by
    setting ``insight_rag.config.RAG_METADATA_BACKEND`` themselves.
    """
    import insight_rag.config as config

    monkeypatch.setattr(config, "RAG_METADATA_BACKEND", "file")
