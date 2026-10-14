"""Shared fixtures. Every test gets its own temporary SQLite database and short delays."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import repository as repo  # noqa: E402
from backend.app.app_factory import create_app  # noqa: E402
from backend.app.config import Settings  # noqa: E402
from backend.app.database import open_db  # noqa: E402
from worker.worker import HttpTradeSource  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "test.db",
        mock_total_trades=1000,
        mock_seed=42,
        mock_full_pull_seconds=0.0,  # no artificial delay unless a test asks for one
        worker_batch_size=100,
        worker_poll_seconds=0.05,
        worker_max_retries=2,
        worker_retry_backoff_seconds=0.0,
        sse_max_connection_seconds=3.0,
        sse_poll_seconds=0.05,
        sse_ping_seconds=1.0,
        sse_retry_ms=100,
    )


@pytest.fixture
def make_client():
    """Factory: build an app + TestClient for given settings (lets tests tweak settings)."""
    clients = []

    def _make(s: Settings) -> TestClient:
        c = TestClient(create_app(s))
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def client(settings, make_client) -> TestClient:
    return make_client(settings)


@pytest.fixture
def source(client) -> HttpTradeSource:
    """Worker trade source that talks to the mock API through the in-process TestClient."""
    return HttpTradeSource(base_url="http://testserver", timeout=10, client=client)


@pytest.fixture
def db(settings, client):
    with open_db(settings.database_path) as conn:
        yield conn


def with_settings(s: Settings, **changes) -> Settings:
    return replace(s, **changes)


def count_trades(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]


__all__ = ["repo", "with_settings", "count_trades"]
