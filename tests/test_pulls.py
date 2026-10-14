"""Requirement 2: pull jobs - fast start, duplicates, errors, recovery."""

import threading
import time

from backend.app import repository as repo
from worker.worker import run_job, run_worker
from tests.conftest import count_trades, with_settings


def test_start_pull_returns_immediately(client):
    started = time.perf_counter()
    response = client.post("/api/pulls")
    elapsed = time.perf_counter() - started

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert isinstance(body["job_id"], int)
    assert elapsed < 1.0  # does NOT wait for the pull


def test_start_pull_is_fast_even_with_15_minute_config(settings, make_client):
    client = make_client(with_settings(settings, mock_full_pull_seconds=900))
    started = time.perf_counter()
    assert client.post("/api/pulls").status_code == 202
    assert time.perf_counter() - started < 1.0


def test_duplicate_simultaneous_pull_is_rejected(client):
    first = client.post("/api/pulls").json()
    second = client.post("/api/pulls")
    assert second.status_code == 409
    assert second.json()["job_id"] == first["job_id"]


def test_database_enforces_single_active_job(db):
    db.execute("INSERT INTO pull_jobs (status, created_at, updated_at) VALUES ('running', 'x', 'x')")
    try:
        db.execute("INSERT INTO pull_jobs (status, created_at, updated_at) VALUES ('queued', 'x', 'x')")
        raised = False
    except Exception:
        raised = True
    assert raised, "partial unique index should block a second active job"


def test_full_pull_stores_all_trades_and_reports_progress(client, db, source, settings):
    job_id = client.post("/api/pulls").json()["job_id"]
    job = repo.claim_next_job(db)
    final = run_job(db, job, source, settings)

    assert final["status"] == "succeeded"
    assert final["progress_percent"] == 100.0
    assert final["inserted_count"] == 1000
    assert final["pages_done"] == final["pages_total"] == 10
    assert count_trades(db) == 1000

    status = client.get(f"/api/pulls/{job_id}").json()
    assert status["status"] == "succeeded"
    latest = client.get("/api/pulls/latest").json()
    assert latest["last_successful_pull_at"] is not None


def test_second_pull_creates_no_duplicates(client, db, source, settings):
    for _ in range(2):
        client.post("/api/pulls")
        run_job(db, repo.claim_next_job(db), source, settings)

    assert count_trades(db) == 1000
    second = repo.get_latest_job(db)
    assert second["status"] == "succeeded"
    assert second["inserted_count"] == 0
    assert second["duplicate_count"] == 1000
    dupes = db.execute(
        "SELECT trade_id FROM trades GROUP BY trade_id HAVING COUNT(*) > 1"
    ).fetchall()
    assert dupes == []


def test_store_batch_is_idempotent(db):
    job, _ = repo.create_pull_job(db)
    trade = {"trade_id": "T1", "client": "C", "symbol": "S", "quantity": 1, "price": 10.5,
             "timestamp": "2026-10-12T09:15:00+05:30"}
    first = repo.store_batch(db, job["id"], [trade, trade], next_page=2, pages_total=1, total_expected=1)
    second = repo.store_batch(db, job["id"], [trade], next_page=2, pages_total=1, total_expected=1)
    assert first["inserted"] == 1 and first["duplicates"] == 1
    assert second["inserted"] == 0
    assert count_trades(db) == 1


def test_upstream_error_is_retried_then_reported(settings, make_client):
    s = with_settings(settings, mock_fail_page=3)
    client = make_client(s)
    from worker.worker import HttpTradeSource
    from backend.app.database import open_db

    source = HttpTradeSource("http://testserver", 10, client=client)
    job_id = client.post("/api/pulls").json()["job_id"]
    with open_db(s.database_path) as db:
        final = run_job(db, repo.claim_next_job(db), source, s)

    assert final["status"] == "failed"
    assert "503" in final["error"] and "page 3" in final["error"].lower()
    assert "after 2 retries" in final["error"]

    status = client.get(f"/api/pulls/{job_id}").json()
    assert status["status"] == "failed"
    assert status["error"]
    # Pages 1-2 were stored before the failure and are still available.
    assert client.get("/api/stats").json()["total_trades"] == 200
    # A failed job does not block a new pull.
    assert client.post("/api/pulls").status_code == 202


def test_malformed_data_fails_job_with_message(db, settings, client):
    class BadSource:
        def fetch_page(self, page, page_size):
            return {"trades": [{"trade_id": "X"}], "total": 1, "total_pages": 1, "has_more": False}

    client.post("/api/pulls")
    final = run_job(db, repo.claim_next_job(db), BadSource(), settings)
    assert final["status"] == "failed"
    assert "missing fields" in final["error"]
    assert count_trades(db) == 0


def test_connection_errors_are_reported(db, settings, client):
    from worker.worker import HttpTradeSource

    client.post("/api/pulls")
    unreachable = HttpTradeSource("http://127.0.0.1:9", timeout=1)  # nothing listens on port 9
    final = run_job(db, repo.claim_next_job(db), unreachable, settings)
    assert final["status"] == "failed"
    # Windows reports a closed port as ConnectTimeout, Linux/macOS as ConnectError.
    assert "Connect" in final["error"] and "failed after 2 retries" in final["error"]


def test_unknown_job_returns_404(client):
    assert client.get("/api/pulls/999").status_code == 404


def test_interrupted_job_resumes_where_it_stopped(client, db, source, settings):
    """Simulate a worker crash after 3 pages, then a restart."""
    client.post("/api/pulls")
    job = repo.claim_next_job(db)

    stop = threading.Event()

    class CrashAfterThreePages:
        calls = 0

        def fetch_page(self, page, page_size):
            CrashAfterThreePages.calls += 1
            if CrashAfterThreePages.calls == 3:
                stop.set()  # worker "dies" after this page is stored
            return source.fetch_page(page, page_size)

    run_job(db, job, CrashAfterThreePages(), settings, stop_event=stop)
    assert repo.get_job(db, job["id"])["status"] == "running"  # left behind by the "crash"
    assert count_trades(db) == 300

    # Restarted worker: re-queue and resume.
    assert repo.requeue_interrupted_jobs(db) == [job["id"]]
    resumed = repo.claim_next_job(db)
    assert resumed["next_page"] == 4 and resumed["attempts"] == 2
    final = run_job(db, resumed, source, settings)

    assert final["status"] == "succeeded"
    assert final["inserted_count"] == 1000
    assert final["duplicate_count"] == 0  # nothing was fetched twice
    assert count_trades(db) == 1000


def test_worker_loop_processes_queued_job(client, settings, source, db):
    client.post("/api/pulls")
    stop = threading.Event()
    thread = threading.Thread(target=run_worker, args=(settings, source, stop), daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline and repo.get_latest_job(db)["status"] != "succeeded":
        time.sleep(0.05)
    stop.set()
    thread.join(5)
    assert repo.get_latest_job(db)["status"] == "succeeded"
    assert count_trades(db) == 1000
