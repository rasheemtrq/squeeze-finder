"""
Finnhub integration — strong free tier option (60 calls/min).

Finnhub is one of the best free (or low-cost) sources for:
- Real-time / delayed stock quotes (much more reliable than yfinance)
- Company fundamentals / profile (good shares outstanding, market cap, etc.)
- Earnings + other calendars

This module follows the project fetcher contract and is designed to be used
as a primary or fallback source when FINNHUB_API_KEY is present.

Recommended usage in scanner:
- Use for prices (replaces or supplements yfinance quote)
- Use for richer fundamentals
- Already used for earnings catalysts (expand here if needed)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import FINNHUB_API_KEY

class DataUnavailable(Exception):
    """Local copy to avoid circular import with prices.py."""
    pass

logger = logging.getLogger(__name__)

BASE = "https://finnhub.io/api/v1"


def _enabled() -> bool:
    return bool(FINNHUB_API_KEY)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=4))
def _get(path: str, params: dict | None = None) -> dict:
    if not _enabled():
        raise DataUnavailable("FINNHUB_API_KEY not set")
    params = params or {}
    params["token"] = FINNHUB_API_KEY
    r = httpx.get(f"{BASE}{path}", params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("error"):
        raise DataUnavailable(f"Finnhub error: {data['error']}")
    return data


def fetch_quote(ticker: str) -> dict | None:
    """Real-time / delayed quote. Excellent replacement for slow yfinance quotes."""
    if not _enabled():
        return None
    try:
        data = _get("/quote", {"symbol": ticker})
        if not data or "c" not in data:
            return None
        return {
            "ticker": ticker,
            "current_price": data.get("c"),
            "change": data.get("d"),
            "percent_change": data.get("dp"),
            "high": data.get("h"),
            "low": data.get("l"),
            "open": data.get("o"),
            "previous_close": data.get("pc"),
            "timestamp": data.get("t"),
            "source": "finnhub",
        }
    except Exception as e:
        logger.debug("Finnhub quote failed for %s: %s", ticker, e)
        return None


def fetch_profile(ticker: str) -> dict | None:
    """Company profile — good for shares outstanding, market cap, sector, etc."""
    if not _enabled():
        return None
    try:
        data = _get("/stock/profile2", {"symbol": ticker})
        if not data or "ticker" not in data:
            return None
        return {
            "ticker": ticker,
            "name": data.get("name"),
            "market_cap": data.get("marketCapitalization"),
            "shares_outstanding": data.get("shareOutstanding"),
            "float_shares": data.get("shareOutstanding"),  # best available proxy
            "country": data.get("country"),
            "currency": data.get("currency"),
            "exchange": data.get("exchange"),
            "ipo": data.get("ipo"),
            "sector": data.get("finnhubIndustry"),  # or 'gind' for GICS
            "source": "finnhub",
        }
    except Exception as e:
        logger.debug("Finnhub profile failed for %s: %s", ticker, e)
        return None


def fetch_earnings_calendar(ticker: str, from_date: str | None = None, to_date: str | None = None) -> dict | None:
    """Earnings calendar (already used in catalysts.py, exposed here for consistency)."""
    if not _enabled():
        return None
    try:
        params = {"symbol": ticker}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        data = _get("/calendar/earnings", params)
        return data
    except Exception as e:
        logger.debug("Finnhub earnings calendar failed for %s: %s", ticker, e)
        return None


def enrich_ticker(result: dict) -> dict:
    """Post-scan enrichment using Finnhub (prices + profile)."""
    if not _enabled():
        return result

    ticker = result["ticker"]

    # Prices / quote (often faster and more reliable than yfinance)
    quote = fetch_quote(ticker)
    if quote and quote.get("current_price"):
        # Update price if we have better data
        if not result.get("price") or abs((result.get("price") or 0) - quote["current_price"]) > 0.01:
            result["price"] = quote["current_price"]
        result.setdefault("finnhub", {})["quote"] = quote

    # Fundamentals / profile
    profile = fetch_profile(ticker)
    if profile:
        fund = result.get("fundamentals") or {}
        # Fill gaps, don't overwrite strong yfinance data
        if not fund.get("market_cap") and profile.get("market_cap"):
            fund["market_cap"] = profile["market_cap"]
        if not fund.get("shares_outstanding") and profile.get("shares_outstanding"):
            fund["shares_outstanding"] = profile["shares_outstanding"]
        if not fund.get("float_shares") and profile.get("float_shares"):
            fund["float_shares"] = profile["float_shares"]
        if not fund.get("sector") and profile.get("sector"):
            fund["sector"] = profile["sector"]
        result["fundamentals"] = fund
        result.setdefault("finnhub", {})["profile"] = profile

    return result


def is_valid_ticker(ticker: str) -> bool:
    """Fast check using Finnhub quote. Returns False quickly for delisted/invalid symbols."""
    if not _enabled():
        return True  # can't check, assume ok
    try:
        q = fetch_quote(ticker)
        return bool(q and q.get("current_price"))
    except Exception:
        return False


def enrich_top_results(results: list[dict], top_n: int = 8) -> list[dict]:
    """Enrich top results after main scan (respects rate limits)."""
    if not _enabled() or not results:
        return results
    for r in results[:top_n]:
        enrich_ticker(r)
    return results