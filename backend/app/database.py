"""SQLite connection helpers.

Each caller opens its own short-lived connection. WAL mode lets the API read
while the worker process writes, and busy_timeout makes writers wait instead of failing.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import PROJECT_ROOT

SCHEMA_PATH = PROJECT_ROOT / "database" / "schema.sql"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


@contextmanager
def open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """Run a block atomically. IMMEDIATE takes the write lock up front (no lock upgrade races)."""
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open_db(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    # Create the database file and tables explicitly: python -m backend.app.database
    # (The API and the worker also do this automatically on start-up.)
    from .config import load_settings

    path = load_settings().database_path
    init_db(path)
    print(f"Database ready: {path}")
