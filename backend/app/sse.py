"""Server-Sent Events: GET /api/stream.

The worker writes every change to the `events` table in the same transaction as the data
itself. This endpoint tails that table and forwards new rows to the browser.

Reliability:
* Every message carries `id: <events.id>`. When the connection drops, the browser's
  EventSource reconnects automatically and sends `Last-Event-ID`; we resume right after it.
* The first connection passes `?since=<last_event_id>` from the REST snapshot.
* If the requested id is older than the retained history, we send `resync` and the
  dashboard reloads its snapshot via REST.
* Connections are closed after SSE_MAX_CONNECTION_SECONDS (default 25 s), i.e. before the
  network's 30 s limit, and the browser reconnects after `retry` milliseconds with no data lost.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from . import repository as repo
from .config import Settings
from .database import open_db

router = APIRouter(prefix="/api", tags=["live"])


def format_sse(event_type: str, data: dict, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


def _read(settings: Settings, fn, *args):
    with open_db(settings.database_path) as conn:
        return fn(conn, *args)


def _parse_start(last_event_id: str | None, since: int | None) -> int | None:
    if last_event_id and last_event_id.strip().isdigit():
        return int(last_event_id.strip())
    return since


async def event_generator(request: Request, settings: Settings, start: int | None):
    oldest, newest = await run_in_threadpool(_read, settings, repo.event_bounds)
    cursor = newest if start is None else start

    yield f"retry: {settings.sse_retry_ms}\n\n"
    if start is not None and newest and oldest > cursor + 1:
        # Some events the client needs were pruned: ask it to reload from REST.
        cursor = newest
        yield format_sse("resync", {"reason": "history_pruned"}, cursor)
    else:
        yield format_sse("ready", {"cursor": cursor}, cursor)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.sse_max_connection_seconds
    last_sent = time.monotonic()

    while True:
        if await request.is_disconnected():
            return
        events = await run_in_threadpool(_read, settings, repo.fetch_events_after, cursor, 100)
        for ev in events:
            cursor = ev["id"]
            yield format_sse(ev["type"], ev["data"], ev["id"])
            last_sent = time.monotonic()
        if len(events) == 100:
            continue  # more backlog waiting, keep draining
        if loop.time() >= deadline:
            return  # close before the network's 30 s limit; browser reconnects with Last-Event-ID
        if time.monotonic() - last_sent >= settings.sse_ping_seconds:
            yield ": ping\n\n"  # comment line keeps proxies from treating the stream as idle
            last_sent = time.monotonic()
        await asyncio.sleep(settings.sse_poll_seconds)


@router.get("/stream")
async def stream(
    request: Request,
    since: int | None = Query(None, ge=0, description="Start after this event id (first connect)"),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    settings: Settings = request.app.state.settings
    start = _parse_start(last_event_id, since)
    return StreamingResponse(
        event_generator(request, settings, start),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
