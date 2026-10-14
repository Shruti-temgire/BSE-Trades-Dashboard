"""Requirement 3: live updates over Server-Sent Events, reconnect recovery and no duplicates.

These tests start a real uvicorn server on a free port and read the stream with httpx,
exactly like a browser's EventSource would.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from backend.app import repository as repo
from backend.app.app_factory import create_app
from backend.app.database import open_db
from worker.worker import HttpTradeSource, run_job
from tests.conftest import with_settings


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(settings):
    s = with_settings(settings, mock_full_pull_seconds=2.0)  # 0.2 s per page
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(f"{base}/api/health", timeout=1)
            break
        except httpx.TransportError:
            time.sleep(0.05)
    yield base, s
    server.should_exit = True
    thread.join(5)


def read_events(base: str, params=None, headers=None, until=None, timeout=20.0) -> list[dict]:
    """Read SSE messages from one connection until `until(event)` is true or the server closes it."""
    events, current = [], {}
    with httpx.stream("GET", f"{base}/api/stream", params=params, headers=headers,
                      timeout=httpx.Timeout(timeout)) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line == "":
                if "event" in current:
                    events.append(current)
                    if until and until(current):
                        break
                current = {}
            elif line.startswith(":"):
                continue  # keep-alive comment
            else:
                field, _, value = line.partition(": ")
                if field == "data":
                    value = json.loads(value)
                current[field] = value
    return events


def _start_pull_in_background(base: str, s) -> threading.Thread:
    assert httpx.post(f"{base}/api/pulls").status_code == 202

    def work():
        with open_db(s.database_path) as conn, httpx.Client(base_url=base, timeout=10) as http:
            run_job(conn, repo.claim_next_job(conn), HttpTradeSource(base, 10, client=http), s)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


def _job_finished(ev) -> bool:
    return ev["event"] == "job" and ev["data"]["job"]["status"] in ("succeeded", "failed")


def test_open_stream_receives_new_trades_live(live_server):
    """An already-open 'dashboard' connection receives every new trade as batches are stored."""
    base, s = live_server
    snapshot = httpx.get(f"{base}/api/dashboard").json()
    collected: list[dict] = []
    worker = None
    done = False

    # Connect first (like an open browser tab), then start the pull.
    def on_event(ev):
        nonlocal worker, done
        if ev["event"] == "ready" and worker is None:
            worker = _start_pull_in_background(base, s)
        if ev["event"] == "trades":
            collected.extend(ev["data"]["trades"])
        done = done or _job_finished(ev)
        return done

    events = []
    since = snapshot["last_event_id"]
    # The server closes each connection after a few seconds; reconnect with Last-Event-ID like EventSource does.
    last_id = None
    deadline = time.time() + 30
    while not done and time.time() < deadline:
        headers = {"Last-Event-ID": last_id} if last_id else None
        batch = read_events(base, params={"since": since}, headers=headers, until=on_event)
        events += batch
        ids = [e["id"] for e in batch if "id" in e]
        last_id = ids[-1] if ids else last_id
    assert done, "pull did not finish in time"
    worker.join(10)

    trade_ids = [t["trade_id"] for t in collected]
    assert len(trade_ids) == 1000
    assert len(set(trade_ids)) == 1000  # no duplicates delivered
    final_stats = [e for e in events if e["event"] == "trades"][-1]["data"]["stats"]
    assert final_stats["total_trades"] == 1000
    ids = [int(e["id"]) for e in events if e["event"] in ("trades", "job")]
    assert ids == sorted(ids) and len(ids) == len(set(ids))  # ordered, never repeated


def test_reconnect_with_last_event_id_recovers_missed_events(live_server):
    base, s = live_server
    worker = _start_pull_in_background(base, s)
    worker.join(30)

    # A client that saw events up to `middle` (then disconnected) must get exactly the rest.
    with open_db(s.database_path) as conn:
        all_events = repo.fetch_events_after(conn, 0, 10_000)
    middle = all_events[len(all_events) // 2]["id"]
    expected = [e["id"] for e in all_events if e["id"] > middle]

    events = read_events(base, headers={"Last-Event-ID": str(middle)}, until=_job_finished)
    received = [int(e["id"]) for e in events if e["event"] in ("trades", "job")]
    assert received == expected


def test_last_event_id_header_wins_over_since(live_server):
    base, s = live_server
    _start_pull_in_background(base, s).join(30)
    with open_db(s.database_path) as conn:
        newest = repo.last_event_id(conn)
    events = read_events(base, params={"since": 0}, headers={"Last-Event-ID": str(newest)},
                         until=lambda e: e["event"] == "ready")
    assert events[0]["event"] == "ready" and int(events[0]["id"]) == newest


def test_resync_when_history_was_pruned(live_server):
    base, s = live_server
    _start_pull_in_background(base, s).join(30)
    with open_db(s.database_path) as conn:
        conn.execute("DELETE FROM events WHERE id < (SELECT MAX(id) FROM events) - 2")
    events = read_events(base, params={"since": 1}, until=lambda e: True)
    assert events[0]["event"] == "resync"


def test_server_closes_stream_before_30_seconds(live_server):
    base, s = live_server
    started = time.perf_counter()
    read_events(base)  # no `until`: returns only when the server ends the connection
    elapsed = time.perf_counter() - started
    assert s.sse_max_connection_seconds <= elapsed < 30
