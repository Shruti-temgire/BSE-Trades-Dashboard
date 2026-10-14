"""Mock BSE trades API: GET /getTrades.

Simulates a slow upstream. MOCK_FULL_PULL_SECONDS is the total time needed to
download *every* trade; each page sleeps for its share of that time. With the
realistic setting (900 s = 15 min), 5000 trades and pages of 100, every request
takes ~18 s, which stays below the 30 s network limit, while the full pull takes 15 min.
"""

from __future__ import annotations

import asyncio
import math

from fastapi import APIRouter, HTTPException, Query, Request

from .config import Settings
from .mock_data import generate_trades

router = APIRouter(tags=["mock-bse"])

MAX_PAGE_SIZE = 1000


def simulated_delay_seconds(settings: Settings, records_returned: int) -> float:
    """Artificial delay for one request, proportional to the number of records returned."""
    if settings.mock_total_trades <= 0 or records_returned <= 0:
        return 0.0
    return settings.mock_full_pull_seconds * records_returned / settings.mock_total_trades


@router.get("/getTrades")
async def get_trades(
    request: Request,
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(500, ge=1, le=MAX_PAGE_SIZE),
) -> dict:
    settings: Settings = request.app.state.settings
    all_trades = generate_trades(settings.mock_total_trades, settings.mock_seed)
    total = len(all_trades)
    total_pages = max(1, math.ceil(total / page_size))

    start = (page - 1) * page_size
    items = list(all_trades[start : start + page_size])

    delay = simulated_delay_seconds(settings, len(items))
    if delay > 0:
        await asyncio.sleep(delay)  # non-blocking: other requests are still served

    if settings.mock_fail_page and page == settings.mock_fail_page:
        raise HTTPException(status_code=503, detail=f"Mock BSE outage while serving page {page}")

    return {
        "trades": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_more": page < total_pages,
        "simulated_delay_seconds": round(delay, 3),
    }
