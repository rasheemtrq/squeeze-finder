from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf

from src.config import CACHE_TTL
from src.data import _cache


class DataUnavailable(Exception):
    pass


_PERIOD_DAYS = {
    "1d": 1,
    "5d": 5,
    "1mo": 22,
    "3mo": 66,
    "6mo": 132,
    "ytd": 260,
    "1y": 252,
    "2y": 504,
    "5y": 1260,
}


def _slice(full: dict, period: str) -> dict:
    """Return a view of the cached 1y bundle narrowed to `period`."""
    bars = full["bars"]
    n = _PERIOD_DAYS.get(period, len(bars))
    sliced = bars[-n:] if n < len(bars) else bars
    return {
        **full,
        "bars": sliced,
        "period": period,
    }


def fetch(ticker: str, period: str = "6mo", force_refresh: bool = False) -> dict:
    """
    Return OHLCV history + latest quote.
    Internally always caches the 1y series; slices on return.
    This unifies cache keys across callers (scan wants 6mo, chart wants 3mo, etc.)
    """
    ttl = CACHE_TTL["prices_eod"]

    if not force_refresh:
        cached = _cache.get("prices", ticker, ttl)
        if cached:
            return _slice(cached, period)

    tk = yf.Ticker(ticker)
    hist = tk.history(period="1y", auto_adjust=True)
    if hist.empty:
        raise DataUnavailable(f"no price history for {ticker}")

    hist = hist.reset_index()
    bars = [
        {
            "date": str(row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
        for _, row in hist.iterrows()
    ]
    latest = bars[-1]
    full = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "bars": bars,
        "close": latest["close"],
        "volume": latest["volume"],
    }
    _cache.put("prices", ticker, full)
    return _slice(full, period)
