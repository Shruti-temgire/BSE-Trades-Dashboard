"""Background worker: pulls trades from the (mock) BSE API in batches and stores them in SQLite.

Run from the project root (separate terminal from the API):
    python -m worker.worker

How it works
1. On start-up, any job left 'running' by a previous worker is re-queued (crash recovery).
2. It waits for a 'queued' job (created by POST /api/pulls) and claims it atomically.
3. It fetches one page per short HTTP request (each well under the 30 s network limit),
   retrying transient failures with exponential back-off.
4. Each page is stored together with the job's resume cursor and an SSE event in ONE
   transaction, so after a crash the job resumes exactly where it stopped.
5. The job ends as 'succeeded' or 'failed' (with an error message the dashboard shows).
"""

from __future__ import annotations

import logging
import signal
import sqlite3
import threading
import time
from typing import Callable, Protocol

import httpx

from backend.app import repository as repo
from backend.app.config import Settings, load_settings
from backend.app.database import init_db, open_db, transaction

log = logging.getLogger("worker")

REQUIRED_FIELDS = ("trade_id", "client", "symbol", "quantity", "price", "timestamp")


class TradeSource(Protocol):
    def fetch_page(self, page: int, page_size: int) -> dict: ...


class PermanentPullError(Exception):
    """An error that retrying will not fix (bad request, invalid data...)."""


class HttpTradeSource:
    """Fetches pages from GET /getTrades. Every call is a separate, short HTTP request."""

    def __init__(self, base_url: str, timeout: float, client: httpx.Client | None = None):
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def fetch_page(self, page: int, page_size: int) -> dict:
        response = self.client.get("/getTrades", params={"page": page, "page_size": page_size})
        response.raise_for_status()
        return response.json()


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code >= 500 or code == 429
    return isinstance(exc, httpx.TransportError)  # timeouts, connection refused/reset


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            detail = exc.response.text[:200]
        return f"HTTP {exc.response.status_code} from {exc.request.url.path}: {detail}"
    return f"{type(exc).__name__}: {exc}"


def validate_page(data: dict) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("trades"), list):
        raise PermanentPullError("Malformed response from BSE API: missing 'trades' list")
    for key in ("total", "total_pages", "has_more"):
        if key not in data:
            raise PermanentPullError(f"Malformed response from BSE API: missing '{key}'")
    for t in data["trades"]:
        missing = [f for f in REQUIRED_FIELDS if f not in t]
        if missing:
            raise PermanentPullError(f"Trade record missing fields {missing}: {t!r:.200}")
        try:
            if int(t["quantity"]) <= 0 or float(t["price"]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise PermanentPullError(f"Invalid quantity/price in trade {t.get('trade_id')}") from None
    return data["trades"]


def fetch_with_retries(
    conn: sqlite3.Connection,
    source: TradeSource,
    job_id: int,
    page: int,
    settings: Settings,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    attempt = 0
    while True:
        try:
            started = time.monotonic()
            data = source.fetch_page(page, settings.worker_batch_size)
            elapsed = time.monotonic() - started
            if elapsed > 25:
                log.warning("Page %s took %.1fs - close to the 30 s network limit. "
                            "Lower WORKER_BATCH_SIZE.", page, elapsed)
            return data
        except Exception as exc:  # noqa: BLE001 - classified below
            if not _is_retryable(exc):
                raise PermanentPullError(_describe(exc)) from exc
            attempt += 1
            if attempt > settings.worker_max_retries:
                raise PermanentPullError(
                    f"Page {page} failed after {settings.worker_max_retries} retries: {_describe(exc)}"
                ) from exc
            wait = settings.worker_retry_backoff_seconds * (2 ** (attempt - 1))
            message = (f"Page {page}: {_describe(exc)} - retry {attempt}/"
                       f"{settings.worker_max_retries} in {wait:.0f}s")
            log.warning(message)
            repo.record_job_warning(conn, job_id, message)
            sleep(wait)


def run_job(
    conn: sqlite3.Connection,
    job: dict,
    source: TradeSource,
    settings: Settings,
    stop_event: threading.Event | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Process one claimed job from its saved cursor to the end. Returns the final job dict."""
    job_id = job["id"]
    page = job["next_page"]
    log.info("Job #%s: starting at page %s (attempt %s)", job_id, page, job["attempts"])
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                log.info("Job #%s: stop requested; it will resume from page %s next time", job_id, page)
                return repo.get_job(conn, job_id)
            data = fetch_with_retries(conn, source, job_id, page, settings, sleep)
            trades = validate_page(data)
            result = repo.store_batch(
                conn, job_id, trades,
                next_page=page + 1,
                pages_total=int(data["total_pages"]),
                total_expected=int(data["total"]),
            )
            log.info("Job #%s: page %s/%s stored (%s new, %s duplicates)", job_id, page,
                     data["total_pages"], result["inserted"], result["duplicates"])
            if not data["has_more"]:
                break
            page += 1
        final = repo.mark_job_succeeded(conn, job_id)
        log.info("Job #%s succeeded: %s new trades", job_id, final["inserted_count"])
        return final
    except Exception as exc:  # noqa: BLE001 - every failure must be reported on the job
        message = str(exc) if isinstance(exc, PermanentPullError) else _describe(exc)
        log.error("Job #%s failed: %s", job_id, message)
        return repo.mark_job_failed(conn, job_id, message)


def run_worker(settings: Settings, source: TradeSource | None = None,
               stop_event: threading.Event | None = None) -> None:
    stop_event = stop_event or threading.Event()
    init_db(settings.database_path)
    source = source or HttpTradeSource(settings.mock_base_url, settings.worker_request_timeout_seconds)

    with open_db(settings.database_path) as conn:
        recovered = repo.requeue_interrupted_jobs(conn)
        if recovered:
            log.info("Recovered interrupted job(s) %s; they will resume from their last saved page", recovered)
        log.info("Worker ready. Waiting for pull jobs (API: %s)", settings.mock_base_url)

        while not stop_event.is_set():
            repo.requeue_interrupted_jobs(conn, stale_seconds=settings.worker_stale_seconds)
            job = repo.claim_next_job(conn)
            if job is None:
                stop_event.wait(settings.worker_poll_seconds)
                continue
            run_job(conn, job, source, settings, stop_event)
            with transaction(conn, immediate=True):
                repo.prune_events(conn, settings.event_retention)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # our own per-page log line is enough
    stop_event = threading.Event()

    def _stop(signum, _frame):
        if stop_event.is_set():
            raise KeyboardInterrupt  # second Ctrl+C: stop immediately
        log.info("Stopping after the current page (press Ctrl+C again to force)...")
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    run_worker(load_settings(), stop_event=stop_event)
    log.info("Worker stopped.")


if __name__ == "__main__":
    main()
