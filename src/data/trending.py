"""
StockTwits trending symbols — top names with surging message activity.

Free, no auth, single GET. Used as a "what's hot right now" feed for the
dynamic universe layer in src.data.universe.
"""
from __future__ import annotations

from datetime import UTC, datetime

from curl_cffi import requests as curl_requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data import _cache
from src.data.prices import DataUnavailable

URL = "https://api.stocktwits.com/api/2/trending/symbols.json"
CACHE_TTL_SECONDS = 900  # 15 min


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get() -> dict:
    r = curl_requests.get(URL, timeout=15, impersonate="chrome124")
    r.raise_for_status()
    return r.json()


def fetch(force_refresh: bool = False) -> dict:
    """{ as_of, tickers: [SYMBOL, ...] } — equities only, in trending order."""
    if not force_refresh:
        cached = _cache.get("stocktwits_trending", "all", CACHE_TTL_SECONDS)
        if cached:
            return cached

    try:
        data = _get()
    except Exception as e:
        raise DataUnavailable(f"stocktwits trending fetch failed: {e}") from e

    tickers: list[str] = []
    for s in data.get("symbols", []):
        sym = (s.get("symbol") or "").upper()
        if not sym or "." in sym or "-" in sym:
            # filter out crypto (BTC.X) and forex (EUR-USD) — equities only
            continue
        tickers.append(sym)

    result = {
        "as_of": datetime.now(UTC).isoformat(),
        "source": "stocktwits/trending",
        "tickers": tickers,
    }
    _cache.put("stocktwits_trending", "all", result)
    return result
