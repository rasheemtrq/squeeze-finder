"""
Lightweight Alpha Vantage integration (prototype).

Intended use: Post-scan enrichment only on the final top N tickers
to avoid burning the extremely limited free tier (25 calls/day).

Currently implements:
- Company Overview (good fundamentals backup: shares outstanding, market cap, sector, etc.)
- News & Sentiment (supplements StockTwits/Apewisdom)

Usage in scanner/CLI:
    from src.data.alphavantage import enrich_top_results
    results = enrich_top_results(results, top_n=5)

Requires ALPHAVANTAGE_API_KEY in .env
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import ALPHAVANTAGE_API_KEY
from src.data.prices import DataUnavailable

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alphavantage.co/query"


def _enabled() -> bool:
    return bool(ALPHAVANTAGE_API_KEY)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
def _get(params: dict) -> dict:
    if not _enabled():
        raise DataUnavailable("ALPHAVANTAGE_API_KEY not set")
    params = {**params, "apikey": ALPHAVANTAGE_API_KEY}
    r = httpx.get(BASE_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if "Error Message" in data or "Information" in data:
        # Rate limit or invalid key message
        msg = data.get("Information") or data.get("Error Message")
        raise DataUnavailable(f"Alpha Vantage: {msg}")
    return data


def fetch_overview(ticker: str) -> dict | None:
    """Company overview / fundamentals."""
    if not _enabled():
        return None
    try:
        data = _get({"function": "OVERVIEW", "symbol": ticker})
        if not data or "Symbol" not in data:
            return None
        return {
            "symbol": data.get("Symbol"),
            "name": data.get("Name"),
            "sector": data.get("Sector"),
            "industry": data.get("Industry"),
            "market_cap": _safe_int(data.get("MarketCapitalization")),
            "shares_outstanding": _safe_int(data.get("SharesOutstanding")),
            "float_shares": _safe_int(data.get("SharesOutstanding")),  # best proxy
            "pe_ratio": data.get("PERatio"),
            "eps": data.get("EPS"),
            "dividend_yield": data.get("DividendYield"),
            "source": "alphavantage",
        }
    except Exception as e:
        logger.debug("Alpha Vantage overview failed for %s: %s", ticker, e)
        return None


def fetch_news_sentiment(ticker: str, limit: int = 5) -> dict | None:
    """News & sentiment for the ticker."""
    if not _enabled():
        return None
    try:
        data = _get({"function": "NEWS_SENTIMENT", "tickers": ticker, "limit": str(limit)})
        feed = data.get("feed", [])
        if not feed:
            return None

        sentiments = []
        for item in feed[:limit]:
            score = item.get("overall_sentiment_score")
            label = item.get("overall_sentiment_label")
            if score is not None:
                sentiments.append({"score": float(score), "label": label})

        avg_score = sum(s["score"] for s in sentiments) / len(sentiments) if sentiments else 0.0

        return {
            "ticker": ticker,
            "articles": len(feed),
            "avg_sentiment_score": round(avg_score, 3),
            "recent_labels": [s["label"] for s in sentiments[:3]],
            "source": "alphavantage",
        }
    except Exception as e:
        logger.debug("Alpha Vantage news failed for %s: %s", ticker, e)
        return None


def _safe_int(val: str | None) -> int | None:
    try:
        return int(val) if val else None
    except (ValueError, TypeError):
        return None


def enrich_ticker(result: dict) -> dict:
    """
    Enrich a single scan result (post-scan) with Alpha Vantage data.
    Only calls if key is present. Very conservative.
    """
    if not _enabled():
        return result

    ticker = result["ticker"]
    overview = fetch_overview(ticker)
    news = fetch_news_sentiment(ticker)

    if overview:
        # Only fill gaps, don't overwrite good yfinance data
        fund = result.get("fundamentals") or {}
        if not fund.get("shares_outstanding"):
            fund["shares_outstanding"] = overview.get("shares_outstanding")
        if not fund.get("market_cap"):
            fund["market_cap"] = overview.get("market_cap")
        result["fundamentals"] = fund
        result.setdefault("alphavantage", {})["overview"] = overview

    if news:
        result.setdefault("alphavantage", {})["news_sentiment"] = news

    return result


def enrich_top_results(results: list[dict], top_n: int = 5) -> list[dict]:
    """Enrich only the top N results after the main scan."""
    if not _enabled() or not results:
        return results

    for r in results[:top_n]:
        enrich_ticker(r)

    return results