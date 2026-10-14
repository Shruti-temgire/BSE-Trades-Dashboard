"""Requirement 1: mock GET /getTrades with seeded data and a configurable delay."""

import time

from backend.app.config import load_settings
from backend.app.mock_api import simulated_delay_seconds
from tests.conftest import with_settings

FIELDS = {"trade_id", "client", "symbol", "quantity", "price", "timestamp"}


def test_returns_thousands_of_seeded_trades(settings, make_client):
    client = make_client(with_settings(settings, mock_total_trades=5000))
    body = client.get("/getTrades", params={"page": 1, "page_size": 1000}).json()

    assert body["total"] == 5000
    assert body["total_pages"] == 5
    assert body["has_more"] is True
    assert len(body["trades"]) == 1000
    for trade in body["trades"]:
        assert FIELDS <= trade.keys()
        assert trade["quantity"] > 0 and trade["price"] > 0
    assert len({t["trade_id"] for t in body["trades"]}) == 1000  # unique ids


def test_data_is_deterministic(client):
    first = client.get("/getTrades", params={"page": 3, "page_size": 50}).json()["trades"]
    second = client.get("/getTrades", params={"page": 3, "page_size": 50}).json()["trades"]
    assert first == second
    assert first[0]["trade_id"] == "BSE202610120000101"


def test_pages_cover_all_trades_exactly_once(client):
    ids = []
    page = 1
    while True:
        body = client.get("/getTrades", params={"page": page, "page_size": 300}).json()
        ids += [t["trade_id"] for t in body["trades"]]
        if not body["has_more"]:
            break
        page += 1
    assert len(ids) == 1000 == len(set(ids))


def test_delay_is_applied_and_configurable(settings, make_client):
    # 2 s for a full pull of 1000 trades => 0.5 s for a 250-trade page
    client = make_client(with_settings(settings, mock_full_pull_seconds=2.0))
    started = time.perf_counter()
    body = client.get("/getTrades", params={"page": 1, "page_size": 250}).json()
    elapsed = time.perf_counter() - started
    assert body["simulated_delay_seconds"] == 0.5
    assert 0.45 <= elapsed < 2.0


def test_fifteen_minute_configuration_keeps_each_request_short(settings):
    """900 s total for 5000 trades in pages of 100 => 18 s per request (< 30 s network limit).
    Calculated only - we never actually wait 15 minutes in tests."""
    full = with_settings(settings, mock_full_pull_seconds=900, mock_total_trades=5000)
    per_request = simulated_delay_seconds(full, 100)
    assert per_request == 18.0
    assert per_request * 50 == 900  # 50 pages add up to the full 15 minutes
    assert per_request < 30


def test_delay_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("MOCK_FULL_PULL_SECONDS", "900")
    monkeypatch.setenv("MOCK_TOTAL_TRADES", "5000")
    s = load_settings()
    assert s.mock_full_pull_seconds == 900.0
    assert s.mock_total_trades == 5000


def test_rejects_invalid_paging(client):
    assert client.get("/getTrades", params={"page": 0}).status_code == 422
    assert client.get("/getTrades", params={"page_size": 100000}).status_code == 422
