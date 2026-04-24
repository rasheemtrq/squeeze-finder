"""
Apewisdom aggregates per-ticker mentions from r/wallstreetbets, r/stocks,
r/options, and r/cryptocurrency, with 24h-ago deltas. Free, no auth, one
call returns the top-100 of each filter — perfect for scan-wide lookups.

We use the `wallstreetbets` filter since squeeze plays are historically
WSB-driven; rank + mention velocity are the relevant early signals.

https://apewisdom.io/api/
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data import _cache
from src.data.prices import DataUnavailable

URL = "https://apewisdom.io/api/v1.0/filter/wallstreetbets/page/1"
CACHE_TTL_SECONDS = 900  # 15 min


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get() -> dict:
    r = httpx.get(URL, timeout=20, headers={"User-Agent": "squeeze-finder/0.1"})
    r.raise_for_status()
    return r.json()


def fetch_all(force_refresh: bool = False) -> dict:
    """
    Returns { as_of, tickers: { TICKER: {rank, mentions, upvotes, rank_24h_ago, mentions_24h_ago, velocity} } }
    Cached 15 min — called once per scan, all per-ticker lookups hit cache.
    """
    if not force_refresh:
        cached = _cache.get("apewisdom", "wsb_page1", CACHE_TTL_SECONDS)
        if cached:
            return cached

    try:
        data = _get()
    except Exception as e:
        raise DataUnavailable(f"apewisdom fetch failed: {e}") from e

    tickers: dict[str, dict] = {}
    for r in data.get("results", []):
        try:
            t = str(r["ticker"]).upper()
            mentions = int(r["mentions"])
            prior = r.get("mentions_24h_ago")
            velocity = None
            if prior is not None and prior > 0:
                velocity = round(mentions / prior, 3)
            tickers[t] = {
                "rank": int(r["rank"]),
                "name": r.get("name"),
                "mentions": mentions,
                "upvotes": int(r.get("upvotes") or 0),
                "rank_24h_ago": r.get("rank_24h_ago"),
                "mentions_24h_ago": prior,
                "velocity": velocity,
            }
        except (KeyError, TypeError, ValueError):
            continue

    result = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "apewisdom/wallstreetbets",
        "total_ranked": len(tickers),
        "tickers": tickers,
    }
    _cache.put("apewisdom", "wsb_page1", result)
    return result


def fetch(ticker: str, force_refresh: bool = False) -> dict | None:
    """Per-ticker lookup. Returns None if ticker is not in WSB top-100."""
    try:
        full = fetch_all(force_refresh=force_refresh)
    except DataUnavailable:
        return None
    stats = full["tickers"].get(ticker.upper())
    if not stats:
        return None
    return {
        "ticker": ticker.upper(),
        "as_of": full["as_of"],
        "in_top100": True,
        **stats,
    }
