"""Application settings, read from environment variables (and an optional .env file).

Every value has a safe development default, so the project runs without a .env file.
See .env.example for documentation of each variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _get(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _int(name: str, default: int) -> int:
    return int(_get(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(_get(name, str(default)))


@dataclass(frozen=True)
class Settings:
    # Storage
    database_path: Path = PROJECT_ROOT / "database" / "trades.db"

    # Mock BSE API (GET /getTrades)
    mock_total_trades: int = 5000
    mock_seed: int = 42
    # Total artificial delay for pulling ALL trades. 900 = realistic 15 minutes.
    # The delay is spread across pages, so each individual HTTP request stays short.
    mock_full_pull_seconds: float = 20.0
    # Make this page number fail with HTTP 503 (0 = never). Used to demo error handling.
    mock_fail_page: int = 0

    # Worker
    mock_base_url: str = "http://127.0.0.1:8000"
    worker_batch_size: int = 100
    worker_poll_seconds: float = 1.0
    worker_max_retries: int = 3
    worker_retry_backoff_seconds: float = 2.0
    worker_request_timeout_seconds: float = 28.0
    worker_stale_seconds: float = 120.0

    # Server-Sent Events
    # The network kills connections older than 30 s, so the server politely ends each
    # stream before that; the browser reconnects automatically with Last-Event-ID.
    sse_max_connection_seconds: float = 25.0
    sse_poll_seconds: float = 0.5
    sse_ping_seconds: float = 10.0
    sse_retry_ms: int = 1000
    event_retention: int = 5000

    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")


def load_settings() -> Settings:
    """Build Settings from the environment (after loading PROJECT_ROOT/.env if present)."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    defaults = Settings()

    db_path = Path(_get("DATABASE_PATH", str(defaults.database_path)))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    return Settings(
        database_path=db_path,
        mock_total_trades=_int("MOCK_TOTAL_TRADES", defaults.mock_total_trades),
        mock_seed=_int("MOCK_SEED", defaults.mock_seed),
        mock_full_pull_seconds=_float("MOCK_FULL_PULL_SECONDS", defaults.mock_full_pull_seconds),
        mock_fail_page=_int("MOCK_FAIL_PAGE", defaults.mock_fail_page),
        mock_base_url=_get("MOCK_BSE_BASE_URL", defaults.mock_base_url),
        worker_batch_size=_int("WORKER_BATCH_SIZE", defaults.worker_batch_size),
        worker_poll_seconds=_float("WORKER_POLL_SECONDS", defaults.worker_poll_seconds),
        worker_max_retries=_int("WORKER_MAX_RETRIES", defaults.worker_max_retries),
        worker_retry_backoff_seconds=_float(
            "WORKER_RETRY_BACKOFF_SECONDS", defaults.worker_retry_backoff_seconds
        ),
        worker_request_timeout_seconds=_float(
            "WORKER_REQUEST_TIMEOUT_SECONDS", defaults.worker_request_timeout_seconds
        ),
        worker_stale_seconds=_float("WORKER_STALE_SECONDS", defaults.worker_stale_seconds),
        sse_max_connection_seconds=_float(
            "SSE_MAX_CONNECTION_SECONDS", defaults.sse_max_connection_seconds
        ),
        sse_poll_seconds=_float("SSE_POLL_SECONDS", defaults.sse_poll_seconds),
        sse_ping_seconds=_float("SSE_PING_SECONDS", defaults.sse_ping_seconds),
        sse_retry_ms=_int("SSE_RETRY_MS", defaults.sse_retry_ms),
        event_retention=_int("EVENT_RETENTION", defaults.event_retention),
        cors_origins=tuple(
            o.strip()
            for o in _get("CORS_ORIGINS", ",".join(defaults.cors_origins)).split(",")
            if o.strip()
        ),
    )
