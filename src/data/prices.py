from __future__ import annotations

from datetime import datetime, timezone
import logging

import yfinance as yf

from src.config import CACHE_TTL, FINNHUB_API_KEY
from src.data import _cache
from src.data.finnhub import fetch_quote as finnhub_quote

# Quiet yfinance's noisy "possibly delisted" / no data warnings that pollute
# API logs during prewarm and scans for tickers that have died (common in
# meme/universe lists). Failures still raise DataUnavailable cleanly.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


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
    close_price = latest["close"]
    volume = latest["volume"]

    # Prefer Finnhub for the live quote when available (much more reliable than yfinance)
    if FINNHUB_API_KEY:
        try:
            q = finnhub_quote(ticker)
            if q and q.get("current_price"):
                close_price = q["current_price"]
                # Keep the bar volume but we now have a fresher price
        except Exception:
            pass  # silent fallback

    full = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "bars": bars,
        "close": close_price,
        "volume": volume,
        "live_quote": FINNHUB_API_KEY and "finnhub" or None,  # marker
    }
    _cache.put("prices", ticker, full)
    return _slice(full, period)
