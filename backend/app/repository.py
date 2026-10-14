"""All SQL lives here. Used by both the API process and the worker process."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .database import transaction

ACTIVE_STATUSES = ("queued", "running")
MAX_PAGE_SIZE = 100


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# --------------------------------------------------------------------------- serialisers


def job_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    job = dict(row)
    pages_total = job.get("pages_total")
    if job["status"] == "succeeded":
        progress = 100.0
    elif pages_total:
        progress = round(min(100.0, 100.0 * job["pages_done"] / pages_total), 1)
    else:
        progress = 0.0
    job["progress_percent"] = progress
    job.pop("heartbeat_at", None)
    return job


def trade_to_dict(row: sqlite3.Row | dict) -> dict:
    r = dict(row)
    price_paise = r["price_paise"]
    return {
        "id": r["id"],
        "trade_id": r["trade_id"],
        "client": r["client"],
        "symbol": r["symbol"],
        "quantity": r["quantity"],
        "price": price_paise / 100,
        "value": round(price_paise * r["quantity"] / 100, 2),
        "timestamp": r["timestamp"],
        "stored_at": r["stored_at"],
    }


# --------------------------------------------------------------------------- events


def add_event(conn: sqlite3.Connection, event_type: str, payload: dict) -> int:
    cur = conn.execute(
        "INSERT INTO events (type, payload, created_at) VALUES (?, ?, ?)",
        (event_type, json.dumps(payload), utc_now()),
    )
    return int(cur.lastrowid)


def fetch_events_after(conn: sqlite3.Connection, after_id: int, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT id, type, payload FROM events WHERE id > ? ORDER BY id LIMIT ?",
        (after_id, limit),
    ).fetchall()
    return [{"id": r["id"], "type": r["type"], "data": json.loads(r["payload"])} for r in rows]


def event_bounds(conn: sqlite3.Connection) -> tuple[int, int]:
    """(oldest retained event id, newest event id); (0, 0) when there are none."""
    row = conn.execute("SELECT MIN(id) AS lo, MAX(id) AS hi FROM events").fetchone()
    return int(row["lo"] or 0), int(row["hi"] or 0)


def last_event_id(conn: sqlite3.Connection) -> int:
    return event_bounds(conn)[1]


def prune_events(conn: sqlite3.Connection, keep: int) -> int:
    cur = conn.execute(
        "DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (keep,)
    )
    return cur.rowcount


# --------------------------------------------------------------------------- pull jobs


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    return job_to_dict(conn.execute("SELECT * FROM pull_jobs WHERE id = ?", (job_id,)).fetchone())


def get_latest_job(conn: sqlite3.Connection) -> dict | None:
    return job_to_dict(conn.execute("SELECT * FROM pull_jobs ORDER BY id DESC LIMIT 1").fetchone())


def get_active_job(conn: sqlite3.Connection) -> dict | None:
    return job_to_dict(
        conn.execute(
            "SELECT * FROM pull_jobs WHERE status IN ('queued', 'running') ORDER BY id LIMIT 1"
        ).fetchone()
    )


def last_successful_pull_at(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT MAX(finished_at) AS t FROM pull_jobs WHERE status = 'succeeded'"
    ).fetchone()
    return row["t"]


def create_pull_job(conn: sqlite3.Connection) -> tuple[dict, bool]:
    """Queue a new pull. Returns (job, created). If a pull is already active, returns it with created=False."""
    try:
        with transaction(conn, immediate=True):
            active = get_active_job(conn)
            if active:
                return active, False
            now = utc_now()
            cur = conn.execute(
                "INSERT INTO pull_jobs (status, created_at, updated_at) VALUES ('queued', ?, ?)",
                (now, now),
            )
            job = get_job(conn, int(cur.lastrowid))
            add_event(conn, "job", {"job": job})
            return job, True
    except sqlite3.IntegrityError:
        # The partial UNIQUE index caught a concurrent insert from another process.
        return get_active_job(conn), False


def _update_job_and_emit(conn: sqlite3.Connection, job_id: int, sql: str, params: Iterable[Any]) -> dict:
    conn.execute(sql, (*params, job_id))
    job = get_job(conn, job_id)
    add_event(conn, "job", {"job": job, "last_successful_pull_at": last_successful_pull_at(conn)})
    return job


def claim_next_job(conn: sqlite3.Connection) -> dict | None:
    """Atomically move the oldest queued job to 'running'. Safe if several workers race."""
    with transaction(conn, immediate=True):
        row = conn.execute(
            "SELECT id FROM pull_jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        now = utc_now()
        return _update_job_and_emit(
            conn,
            row["id"],
            "UPDATE pull_jobs SET status = 'running', started_at = COALESCE(started_at, ?), "
            "updated_at = ?, heartbeat_at = ?, attempts = attempts + 1, error = NULL WHERE id = ?",
            (now, now, now),
        )


def requeue_interrupted_jobs(conn: sqlite3.Connection, stale_seconds: float | None = None) -> list[int]:
    """Put 'running' jobs back in the queue so they resume from their saved next_page.

    stale_seconds=None requeues every running job (used when the single worker starts up:
    anything still 'running' was left behind by a previous worker that crashed or was stopped).
    Otherwise only jobs whose heartbeat is older than stale_seconds are requeued.
    """
    with transaction(conn, immediate=True):
        if stale_seconds is None:
            rows = conn.execute("SELECT id FROM pull_jobs WHERE status = 'running'").fetchall()
        else:
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)).isoformat(
                timespec="milliseconds"
            )
            rows = conn.execute(
                "SELECT id FROM pull_jobs WHERE status = 'running' AND heartbeat_at < ?", (cutoff,)
            ).fetchall()
        ids = [r["id"] for r in rows]
        for job_id in ids:
            _update_job_and_emit(
                conn,
                job_id,
                "UPDATE pull_jobs SET status = 'queued', updated_at = ?, "
                "error = 'Worker stopped unexpectedly; job re-queued and will resume.' WHERE id = ?",
                (utc_now(),),
            )
        return ids


def record_job_warning(conn: sqlite3.Connection, job_id: int, message: str) -> dict:
    """Store a non-fatal message (e.g. 'retrying') on a running job and notify the dashboard."""
    with transaction(conn, immediate=True):
        now = utc_now()
        return _update_job_and_emit(
            conn, job_id,
            "UPDATE pull_jobs SET error = ?, updated_at = ?, heartbeat_at = ? WHERE id = ?",
            (message, now, now),
        )


def mark_job_succeeded(conn: sqlite3.Connection, job_id: int) -> dict:
    with transaction(conn, immediate=True):
        now = utc_now()
        return _update_job_and_emit(
            conn, job_id,
            "UPDATE pull_jobs SET status = 'succeeded', finished_at = ?, updated_at = ?, "
            "error = NULL WHERE id = ?",
            (now, now),
        )


def mark_job_failed(conn: sqlite3.Connection, job_id: int, error: str) -> dict:
    with transaction(conn, immediate=True):
        now = utc_now()
        return _update_job_and_emit(
            conn, job_id,
            "UPDATE pull_jobs SET status = 'failed', finished_at = ?, updated_at = ?, error = ? "
            "WHERE id = ?",
            (now, now, error[:1000]),
        )


def store_batch(
    conn: sqlite3.Connection,
    job_id: int,
    trades: list[dict],
    *,
    next_page: int,
    pages_total: int,
    total_expected: int,
) -> dict:
    """Insert one batch, advance the job's resume cursor and emit an SSE event - all in ONE transaction.

    Either everything is committed or nothing is, so a crash can never leave trades stored
    without the cursor moving (or vice versa). Trades that already exist are skipped by the
    UNIQUE(trade_id) constraint; only genuinely new rows are sent to the dashboard.
    """
    with transaction(conn, immediate=True):
        now = utc_now()
        new_rows: list[dict] = []
        for t in trades:
            price_paise = int(round(float(t["price"]) * 100))
            cur = conn.execute(
                "INSERT INTO trades (trade_id, client, symbol, quantity, price_paise, timestamp, job_id, stored_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(trade_id) DO NOTHING",
                (t["trade_id"], t["client"], t["symbol"], int(t["quantity"]), price_paise,
                 t["timestamp"], job_id, now),
            )
            if cur.rowcount == 1:
                new_rows.append(
                    {"id": cur.lastrowid, "trade_id": t["trade_id"], "client": t["client"],
                     "symbol": t["symbol"], "quantity": int(t["quantity"]),
                     "price_paise": price_paise, "timestamp": t["timestamp"], "stored_at": now}
                )

        inserted = len(new_rows)
        conn.execute(
            "UPDATE pull_jobs SET next_page = ?, pages_done = ?, pages_total = ?, total_expected = ?, "
            "fetched_count = fetched_count + ?, inserted_count = inserted_count + ?, "
            "duplicate_count = duplicate_count + ?, updated_at = ?, heartbeat_at = ?, error = NULL "
            "WHERE id = ?",
            (next_page, next_page - 1, pages_total, total_expected, len(trades), inserted,
             len(trades) - inserted, now, now, job_id),
        )
        job = get_job(conn, job_id)
        payload = {"job": job, "stats": get_stats(conn)}
        if new_rows:
            payload["trades"] = [trade_to_dict(r) for r in new_rows]
            add_event(conn, "trades", payload)
        else:
            add_event(conn, "job", payload)
        return {"inserted": inserted, "duplicates": len(trades) - inserted, "job": job}


# --------------------------------------------------------------------------- trades & stats


def get_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS total_trades, COUNT(DISTINCT client) AS unique_clients, "
        "COUNT(DISTINCT symbol) AS unique_symbols, COALESCE(SUM(price_paise * quantity), 0) AS value_paise "
        "FROM trades"
    ).fetchone()
    return {
        "total_trades": row["total_trades"],
        "unique_clients": row["unique_clients"],
        "unique_symbols": row["unique_symbols"],
        "total_value": round(row["value_paise"] / 100, 2),
    }


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_trades(conn: sqlite3.Connection, page: int = 1, page_size: int = 25, search: str = "") -> dict:
    page = max(1, page)
    page_size = max(1, min(MAX_PAGE_SIZE, page_size))
    search = (search or "").strip()

    where, params = "", []
    if search:
        pattern = f"%{_escape_like(search)}%"
        where = ("WHERE trade_id LIKE ? ESCAPE '\\' OR client LIKE ? ESCAPE '\\' "
                 "OR symbol LIKE ? ESCAPE '\\'")
        params = [pattern, pattern, pattern]

    total = conn.execute(f"SELECT COUNT(*) FROM trades {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM trades {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return {
        "items": [trade_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
        "search": search,
    }


def dashboard_snapshot(conn: sqlite3.Connection, page: int, page_size: int, search: str) -> dict:
    """Everything the dashboard needs on first load, read in ONE consistent snapshot.

    `last_event_id` tells the browser where to start the SSE stream, so no update that
    happens after this snapshot can be missed and none from before it is replayed.
    """
    with transaction(conn):
        return {
            "stats": get_stats(conn),
            "trades": list_trades(conn, page, page_size, search),
            "latest_job": get_latest_job(conn),
            "last_successful_pull_at": last_successful_pull_at(conn),
            "last_event_id": last_event_id(conn),
        }
