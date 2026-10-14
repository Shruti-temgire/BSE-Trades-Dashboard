"""Requirement 2/3: stored trades are queryable - including while a pull is still running."""

import threading
import time

from backend.app import repository as repo
from worker.worker import run_job
from tests.conftest import with_settings


def _pull_all(client, db, source, settings):
    client.post("/api/pulls")
    run_job(db, repo.claim_next_job(db), source, settings)


def test_pagination(client, db, source, settings):
    _pull_all(client, db, source, settings)
    page1 = client.get("/api/trades", params={"page": 1, "page_size": 25}).json()
    page2 = client.get("/api/trades", params={"page": 2, "page_size": 25}).json()

    assert page1["total"] == 1000 and page1["total_pages"] == 40
    assert len(page1["items"]) == 25
    assert not {t["trade_id"] for t in page1["items"]} & {t["trade_id"] for t in page2["items"]}
    assert page1["items"][0]["id"] > page1["items"][-1]["id"]  # newest stored first


def test_search_by_symbol_client_and_id(client, db, source, settings):
    _pull_all(client, db, source, settings)

    by_symbol = client.get("/api/trades", params={"search": "RELIANCE", "page_size": 100}).json()
    assert by_symbol["total"] > 0
    assert all("RELIANCE" in t["symbol"] for t in by_symbol["items"])

    by_id = client.get("/api/trades", params={"search": "BSE202610120000007"}).json()
    assert by_id["total"] == 1

    client_name = by_symbol["items"][0]["client"]
    by_client = client.get("/api/trades", params={"search": client_name.lower()}).json()
    assert all(t["client"] == client_name for t in by_client["items"])

    assert client.get("/api/trades", params={"search": "%"}).json()["total"] == 0  # LIKE is escaped


def test_stats(client, db, source, settings):
    _pull_all(client, db, source, settings)
    stats = client.get("/api/stats").json()
    trades = client.get("/getTrades", params={"page_size": 1000}).json()["trades"]

    assert stats["total_trades"] == 1000
    assert stats["unique_clients"] == len({t["client"] for t in trades})
    assert stats["unique_symbols"] == len({t["symbol"] for t in trades})
    expected_value = sum(round(t["price"] * 100) * t["quantity"] for t in trades) / 100
    assert abs(stats["total_value"] - expected_value) < 0.01


def test_empty_database_dashboard(client):
    snap = client.get("/api/dashboard").json()
    assert snap["stats"]["total_trades"] == 0
    assert snap["trades"]["items"] == []
    assert snap["latest_job"] is None
    assert snap["last_successful_pull_at"] is None


def test_existing_trades_load_while_pull_is_running(settings, make_client):
    """Run a real (slowed-down) pull in a background thread and query the API during it."""
    s = with_settings(settings, mock_full_pull_seconds=3.0)  # 0.3 s per page, 10 pages
    client = make_client(s)
    from backend.app.database import open_db
    from worker.worker import HttpTradeSource

    client.post("/api/pulls")
    source = HttpTradeSource("http://testserver", 10, client=client)

    def worker():
        with open_db(s.database_path) as conn:
            run_job(conn, repo.claim_next_job(conn), source, s)

    thread = threading.Thread(target=worker)
    thread.start()

    observed = []
    while thread.is_alive():
        started = time.perf_counter()
        snap = client.get("/api/dashboard").json()
        assert time.perf_counter() - started < 1.0  # reads are never blocked by the pull
        if snap["latest_job"]["status"] == "running":
            observed.append(snap["stats"]["total_trades"])
        time.sleep(0.1)
    thread.join()

    partial = [n for n in observed if 0 < n < 1000]
    assert partial, f"expected to see partial data while running, saw {observed}"
    assert observed == sorted(observed)  # counts only grow
    assert client.get("/api/stats").json()["total_trades"] == 1000
