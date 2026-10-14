"""Builds the FastAPI application. Kept separate from main.py so tests can create
isolated apps (with their own temporary database) without side effects."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import mock_api, routes, sse
from .config import Settings, load_settings
from .database import init_db


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    init_db(settings.database_path)

    app = FastAPI(
        title="BSE Trades Dashboard API",
        version="1.0.0",
        description="Mock BSE trades API, pull-job control, trade queries and live SSE updates.",
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(mock_api.router)
    app.include_router(routes.router)
    app.include_router(sse.router)

    logging.getLogger("uvicorn.error").info(
        "Database: %s | full mock pull: %ss for %s trades",
        settings.database_path, settings.mock_full_pull_seconds, settings.mock_total_trades,
    )
    return app

