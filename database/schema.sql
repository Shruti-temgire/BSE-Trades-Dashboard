-- BSE Trades Dashboard - SQLite schema
-- Applied automatically on startup by backend/app/database.py (idempotent).

-- Stored trades. trade_id is UNIQUE so the same trade can never be stored twice,
-- even if a batch is fetched again after a crash or a second pull is started.
CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,   -- insertion order, used for "newest first"
    trade_id     TEXT    NOT NULL UNIQUE,
    client       TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    price_paise  INTEGER NOT NULL CHECK (price_paise > 0),  -- money stored as integer paise (no float rounding)
    timestamp    TEXT    NOT NULL,                    -- ISO-8601 trade time from the exchange
    job_id       INTEGER REFERENCES pull_jobs(id),    -- the pull that first stored this trade
    stored_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_trades_client ON trades(client);
CREATE INDEX IF NOT EXISTS ix_trades_symbol ON trades(symbol);

-- One row per "Pull Trades" request. The worker process picks up queued jobs.
CREATE TABLE IF NOT EXISTS pull_jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    status           TEXT    NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    created_at       TEXT    NOT NULL,
    started_at       TEXT,
    finished_at      TEXT,
    updated_at       TEXT    NOT NULL,
    heartbeat_at     TEXT,
    next_page        INTEGER NOT NULL DEFAULT 1,      -- resume point; committed together with each batch
    pages_done       INTEGER NOT NULL DEFAULT 0,
    pages_total      INTEGER,
    total_expected   INTEGER,
    fetched_count    INTEGER NOT NULL DEFAULT 0,
    inserted_count   INTEGER NOT NULL DEFAULT 0,
    duplicate_count  INTEGER NOT NULL DEFAULT 0,
    attempts         INTEGER NOT NULL DEFAULT 0,      -- how many times a worker has (re)started this job
    error            TEXT
);

-- At most ONE active (queued or running) pull at a time, enforced by the database itself.
-- Every active row produces the same index value (1), so a second active row violates UNIQUE.
CREATE UNIQUE INDEX IF NOT EXISTS ux_pull_jobs_one_active
    ON pull_jobs ((status IN ('queued', 'running')))
    WHERE status IN ('queued', 'running');

-- Append-only event log used by Server-Sent Events.
-- The id doubles as the SSE event id, so a reconnecting browser can say
-- "I last saw event 41" and receive everything after it.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT    NOT NULL,
    payload     TEXT    NOT NULL,   -- JSON
    created_at  TEXT    NOT NULL
);
