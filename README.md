# BSE Trades Dashboard

A full-stack technical assessment project. A **FastAPI** backend serves a mock BSE trades API, a separate
**Python worker** pulls the trades in batches into **SQLite**, and a **React (Vite)** dashboard shows them.
The dashboard updates live over **Server-Sent Events (SSE)** as each batch is stored, with no polling and no page refresh.

See [Architecture.md](Architecture.md) for the design in detail.

## Features

- `GET /getTrades`: a mock BSE API with **5,000 deterministic, realistic trades** (seeded) and a
  configurable artificial delay. Use about 20 s for development or **900 s (15 minutes)** for a realistic full pull.
- **Non-blocking pulls.** `POST /api/pulls` returns a job id in milliseconds (HTTP 202). No HTTP request is
  ever held open for the length of the pull.
- **Background worker** (a separate process) that fetches in short batches, retries transient errors, and
  stores each batch atomically with its resume cursor. It resumes interrupted jobs after a restart.
- **No duplicates.** `UNIQUE(trade_id)` plus `INSERT … ON CONFLICT DO NOTHING`, and one active pull at a time
  (enforced by a partial unique index and also by the API with a 409 response).
- **Live dashboard.** Stat cards, pull progress, last successful pull, and a searchable, paginated trades table.
  New trades slide in through SSE. Missed updates are replayed on reconnect using SSE event ids (`Last-Event-ID`).
- 30 backend tests run with pytest, using short delays.

## Project structure

```
BSE-Trades-Dashboard/
├── backend/app/            FastAPI application
│   ├── main.py             entry point (uvicorn backend.app.main:app)
│   ├── app_factory.py      builds the app (used by tests too)
│   ├── config.py           settings from environment / .env
│   ├── database.py         SQLite connection + transaction helpers
│   ├── repository.py       all SQL: jobs, trades, stats, events
│   ├── mock_data.py        deterministic sample trade generator
│   ├── mock_api.py         GET /getTrades (mock BSE API)
│   ├── routes.py           REST API under /api
│   └── sse.py              GET /api/stream (Server-Sent Events)
├── worker/worker.py        background pull worker (separate process)
├── database/schema.sql     tables, unique constraints, indexes (trades.db is created here at runtime)
├── tests/                  pytest suite
├── frontend/               React + Vite dashboard
│   └── src/
│       ├── App.jsx / App.css
│       ├── api.js                 REST helpers
│       ├── hooks/useLiveEvents.js SSE subscription
│       ├── components/            Header, StatsCards, PullPanel, TradesTable, Pagination, Notice (+ .css each)
│       ├── styles/global.css      design tokens and shared styles
│       └── utils/format.js        INR / number / date formatting
├── .env.example            documented configuration with safe defaults
├── requirements.txt
├── pytest.ini
├── README.md
└── Architecture.md
```

## Prerequisites (Windows)

- **Python 3.10+** (tested with 3.13): `python --version`
- **Node.js 18+** (tested with Node 24 / npm 11): `node --version`

## Setup (once)

Open **PowerShell** in the project folder:

```powershell
cd "$HOME\BSE-Trades-Dashboard"

# 1. Python virtual environment + backend dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 2. Configuration (optional - the defaults already work)
Copy-Item .env.example .env

# 3. Create the SQLite database and tables (optional - the API and worker also do this on start-up)
python -m backend.app.database

# 4. Frontend dependencies
cd frontend
npm install
cd ..
```

> If PowerShell blocks `Activate.ps1` with "running scripts is disabled", run this once and try again:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

## Run (three terminals)

**Terminal 1: API (FastAPI + mock BSE API)**

```powershell
cd "$HOME\BSE-Trades-Dashboard"
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2: background worker**

```powershell
cd "$HOME\BSE-Trades-Dashboard"
.\.venv\Scripts\Activate.ps1
python -m worker.worker
```

**Terminal 3: dashboard (Vite dev server)**

```powershell
cd "$HOME\BSE-Trades-Dashboard\frontend"
npm run dev
```

| What | URL |
|---|---|
| Dashboard | http://localhost:5173 |
| API docs (Swagger UI) | http://127.0.0.1:8000/docs |
| Mock BSE API | http://127.0.0.1:8000/getTrades?page=1&page_size=100 |
| Live event stream | http://127.0.0.1:8000/api/stream |

Stop any process with **Ctrl+C**. The worker finishes its current page first. Press Ctrl+C a second time to force it.

## Try it: live updates without waiting 15 minutes

The default `MOCK_FULL_PULL_SECONDS=20` makes a full pull of 5,000 trades take about 20 seconds (50 batches of 100).

1. Start all three processes and open http://localhost:5173. Existing trades load immediately.
2. Click **Pull Trades**. The button returns at once, the badge switches to *Running*, and the progress bar fills.
3. Watch the stat cards and the table update batch by batch. New rows flash yellow. Nothing is refreshed.
4. Open a **second browser tab**. It loads the trades stored so far straight away and then receives the rest live.
5. Click **Pull Trades** again after it completes. The job finishes with *0 new trades, 5,000 duplicates skipped*,
   and the totals do not change, because no duplicates are stored.
6. Click **Pull Trades** twice quickly. The second click is rejected with "A pull is already running".

To start from an empty database: stop the API and worker, then run `Remove-Item database\trades.db*`.

### Demonstrate recovery and error handling

- **Worker restart:** start a pull, close the worker terminal (or Ctrl+C) mid-pull, and start it again. The log
  shows `Recovered interrupted job(s) [N]` and `starting at page K (attempt 2)`. The job resumes where it stopped.
- **Worker not running:** start a pull with no worker. The job stays *Queued* ("Waiting for the worker process…")
  and starts as soon as you run the worker.
- **Upstream failure:** set `MOCK_FAIL_PAGE=10` in `.env` and restart the API. The worker retries page 10 three
  times, then the job becomes *Failed* with the error message shown on the dashboard. Pages 1–9 stay stored.
  Set it back to `0` afterwards.
- **SSE reconnect:** stop the API (Ctrl+C) while the dashboard is open. The header shows *Reconnecting…*.
  Restart the API and it returns to *Live* and catches up on missed events.

## Switching to the realistic 15-minute pull

Edit `.env` (create it with `Copy-Item .env.example .env`):

```ini
MOCK_FULL_PULL_SECONDS=900
```

Restart the **API** terminal. A full pull now takes 15 minutes: each of the 50 requests waits 18 seconds,
which keeps every single HTTP request under the 30-second network limit. The dashboard, start-pull button and
SSE behave exactly the same, just more slowly.

Keep `MOCK_FULL_PULL_SECONDS × WORKER_BATCH_SIZE ÷ MOCK_TOTAL_TRADES` under ~25 s. If you raise the total
time further, lower `WORKER_BATCH_SIZE`.

## Running the tests

```powershell
cd "$HOME\BSE-Trades-Dashboard"
.\.venv\Scripts\Activate.ps1
python -m pytest -v
```

Tests use a temporary database and short delays (0–3 s). The 15-minute setting is checked by calculation only.

| Requirement | Test(s) |
|---|---|
| Mock API returns seeded records | `test_mock_api.py::test_returns_thousands_of_seeded_trades`, `test_data_is_deterministic` |
| 15-minute delay is configurable | `test_delay_is_applied_and_configurable`, `test_fifteen_minute_configuration_keeps_each_request_short`, `test_delay_is_read_from_environment` |
| Start-pull responds quickly | `test_pulls.py::test_start_pull_returns_immediately`, `test_start_pull_is_fast_even_with_15_minute_config` |
| Existing trades load while a pull runs | `test_trades_api.py::test_existing_trades_load_while_pull_is_running` |
| New trades reach an open client via SSE | `test_sse.py::test_open_stream_receives_new_trades_live` (real uvicorn server) |
| Reconnect recovers missed events | `test_sse.py::test_reconnect_with_last_event_id_recovers_missed_events`, `test_resync_when_history_was_pruned` |
| No duplicate trades | `test_second_pull_creates_no_duplicates`, `test_store_batch_is_idempotent`, SSE uniqueness assertions |
| No duplicate simultaneous pulls | `test_duplicate_simultaneous_pull_is_rejected`, `test_database_enforces_single_active_job` |
| Errors handled and reported | `test_upstream_error_is_retried_then_reported`, `test_malformed_data_fails_job_with_message`, `test_connection_errors_are_reported` |
| Recovery after worker restart | `test_interrupted_job_resumes_where_it_stopped` |

Production build of the frontend: `cd frontend; npm run build` (output in `frontend/dist`, which git ignores).

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/getTrades?page=&page_size=` | Mock BSE API (slow, paged, deterministic) |
| POST | `/api/pulls` | Queue a pull, returning **202** `{job_id, status}` or **409** if one is already active |
| GET | `/api/pulls/{id}` | Job status, progress %, counts, error |
| GET | `/api/pulls/latest` | Latest job + last successful pull time |
| GET | `/api/trades?page=&page_size=&search=` | Stored trades, newest first; search on trade id / client / symbol |
| GET | `/api/stats` | Totals for the stat cards |
| GET | `/api/dashboard` | Consistent snapshot of all of the above + `last_event_id` |
| GET | `/api/stream?since=` | SSE stream (`trades`, `job`, `ready`, `resync` events) |

## REST vs SSE, and why a worker?

**REST** is request/response: the browser asks, the server answers, and the connection is done. It suits
everything the user *asks for*: loading a page of trades, searching, starting a pull, reading a job's status.

**SSE** is a one-way, long-lived stream from server to browser over plain HTTP. The browser's built-in
`EventSource` keeps it open, reconnects automatically, and reports the last event id it received, so the server
can resend anything missed. It suits everything the server needs to *tell* the user: "a batch was stored",
"the job finished". WebSockets would also work, but they are two-way, which this app doesn't need.

**Why not polling:** asking `GET /api/trades` every few seconds would mostly return "nothing changed",
waste requests, and still show new trades late (up to one interval behind). With SSE the server sends an update
the moment a batch is committed, and only when something actually happened.

**Why a background worker:** the pull takes up to 15 minutes, but the network kills any HTTP connection older
than 30 seconds. If the API did the pull inside the `POST` request, the request would be cut off, and the work
would die with it. So the API only *records* the request (a `queued` job row) and answers at once. A separate
worker process does the slow work in short requests and saves progress after every batch. It survives browser
refreshes, can be restarted independently, and resumes interrupted jobs. The SSE stream also respects the
30-second rule: the server ends each stream after 25 s and the browser reconnects within about 1 s without losing events.

## Recording a short video walkthrough

1. Reset to an empty database (`Remove-Item database\trades.db*` with the API and worker stopped), then start all three terminals.
2. Arrange the browser and the worker terminal side by side.
3. Start recording with **Win + Alt + R** (Xbox Game Bar), or use **Snipping Tool → Record** (Win + Shift + S, then choose video) on Windows 11.
4. Suggested 2–3 minute script:
   - Show the empty dashboard and the *Live* indicator.
   - Click **Pull Trades**: point out the instant response, the progress bar, and rows flashing in. Mention that there is no refresh.
   - Open a second tab mid-pull to show existing data loading immediately.
   - Ctrl+C the worker mid-pull, restart it, and show it resuming from the saved page.
   - Pull again to show "0 new, 5,000 duplicates skipped".
   - Search for `RELIANCE`, page through results, and narrow the window to show the responsive layout.
   - Run `python -m pytest` and show the tests passing.
5. Press Win + Alt + R again to stop. Game Bar saves recordings to `Videos\Captures`.

## Limitations

- The mock API runs inside the same FastAPI process for convenience. A real deployment would point
  `MOCK_BSE_BASE_URL` at the real exchange API, which would need its own auth, rate limits and data contract.
- The worker reads the job queue from SQLite (a 1-second check in the worker, not in the browser). SQLite and a
  single worker are right for this scale. For more scale, use PostgreSQL plus a real queue (Redis/RQ, Celery).
- On start-up the worker re-queues *all* `running` jobs, assuming it is the only worker. With several workers,
  rely on the heartbeat timeout (`WORKER_STALE_SECONDS`) instead.
- The SSE endpoint checks the events table every 0.5 s on the server, so live updates can lag by up to about half a second.
- The worker isn't interrupted in the middle of an HTTP request. With the 15-minute setting, Ctrl+C can take up to about 18 s.
- No authentication: this is a local demo.
- The trade data is synthetic: real BSE symbols with fictional clients and prices.
