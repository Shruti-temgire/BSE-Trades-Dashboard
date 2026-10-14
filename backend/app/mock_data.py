"""Deterministic, realistic-looking sample trades for the mock BSE API.

The same seed always produces exactly the same trades, so tests and demos are repeatable.
Client names are fictional.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from functools import lru_cache

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_START = datetime(2026, 10, 12, 9, 15, tzinfo=IST)  # BSE equity session 09:15-15:30 IST
SESSION_SECONDS = (6 * 60 + 15) * 60

# Symbol -> approximate reference price in INR
SYMBOLS: dict[str, float] = {
    "RELIANCE": 2950.0, "TCS": 4100.0, "HDFCBANK": 1650.0, "INFY": 1850.0,
    "ICICIBANK": 1250.0, "HINDUNILVR": 2700.0, "ITC": 480.0, "SBIN": 820.0,
    "BHARTIARTL": 1600.0, "KOTAKBANK": 1780.0, "LT": 3650.0, "AXISBANK": 1180.0,
    "ASIANPAINT": 3000.0, "MARUTI": 12500.0, "SUNPHARMA": 1800.0, "TITAN": 3500.0,
    "BAJFINANCE": 7200.0, "ULTRACEMCO": 11000.0, "WIPRO": 520.0, "NESTLEIND": 2500.0,
    "TATAMOTORS": 950.0, "TATASTEEL": 155.0, "POWERGRID": 330.0, "NTPC": 400.0,
    "HCLTECH": 1750.0, "ADANIPORTS": 1400.0, "ONGC": 270.0, "COALINDIA": 480.0,
    "JSWSTEEL": 950.0, "TECHM": 1650.0,
}

_CLIENT_PREFIXES = [
    "Sahyadri", "Narmada", "Indus", "Konkan", "Deccan", "Vindhya", "Malabar", "Kaveri",
    "Ganga", "Aravalli", "Satpura", "Godavari", "Himalaya", "Coromandel", "Thar",
]
_CLIENT_SUFFIXES = [
    "Capital", "Securities", "Wealth Partners", "Investments", "Asset Management",
    "Family Office", "Broking", "Holdings",
]
NUM_CLIENTS = 60


def _build_clients(rng: random.Random) -> list[str]:
    names = [f"{p} {s}" for p in _CLIENT_PREFIXES for s in _CLIENT_SUFFIXES]
    return sorted(rng.sample(names, NUM_CLIENTS))


@lru_cache(maxsize=8)
def generate_trades(count: int, seed: int) -> tuple[dict, ...]:
    """Return `count` trades ordered by timestamp. Cached because the data never changes."""
    rng = random.Random(seed)
    clients = _build_clients(rng)
    symbols = sorted(SYMBOLS)
    offsets = sorted(rng.uniform(0, SESSION_SECONDS) for _ in range(count))

    trades = []
    for i, offset in enumerate(offsets, start=1):
        symbol = rng.choice(symbols)
        # Price moves ~1% around the reference price, rounded to the 0.05 tick size.
        raw_price = SYMBOLS[symbol] * (1 + rng.gauss(0, 0.01))
        price = round(round(raw_price * 20) / 20, 2)
        quantity = max(1, min(5000, int(rng.lognormvariate(3.5, 1.1))))
        ts = SESSION_START + timedelta(seconds=offset)
        trades.append(
            {
                "trade_id": f"BSE{SESSION_START:%Y%m%d}{i:07d}",
                "client": rng.choice(clients),
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "timestamp": ts.isoformat(timespec="milliseconds"),
            }
        )
    return tuple(trades)
