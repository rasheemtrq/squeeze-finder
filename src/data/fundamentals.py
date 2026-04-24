from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf

from src.config import CACHE_TTL
from src.data import _cache
from src.data.prices import DataUnavailable


def fetch(ticker: str, force_refresh: bool = False) -> dict:
    """
    Returns dict with float, short interest, days-to-cover, market cap.
    yfinance .info is a cached aggregate from multiple sources; SI data here
    comes originally from FINRA but staleness is opaque.
    """
    if not force_refresh:
        cached = _cache.get("fundamentals", ticker, CACHE_TTL["fundamentals"])
        if cached:
            return cached

    tk = yf.Ticker(ticker)
    try:
        info = tk.info or {}
    except Exception as e:
        raise DataUnavailable(f"yfinance.info failed for {ticker}: {e}") from e

    if not info.get("regularMarketPrice") and not info.get("currentPrice"):
        raise DataUnavailable(f"yfinance returned empty info for {ticker}")

    float_shares = info.get("floatShares") or info.get("sharesOutstanding")
    shares_short = info.get("sharesShort")
    si_pct = None
    if shares_short and float_shares:
        si_pct = shares_short / float_shares

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "price": info.get("regularMarketPrice") or info.get("currentPrice"),
        "market_cap": info.get("marketCap"),
        "float_shares": float_shares,
        "shares_outstanding": info.get("sharesOutstanding"),
        "shares_short": shares_short,
        "shares_short_prior_month": info.get("sharesShortPriorMonth"),
        "short_ratio": info.get("shortRatio"),
        "short_percent_of_float": info.get("shortPercentOfFloat") or si_pct,
        "shares_short_date": info.get("dateShortInterest"),
        "avg_volume_30d": info.get("averageVolume") or info.get("averageDailyVolume10Day"),
        "sector": info.get("sector"),
        "name": info.get("longName") or info.get("shortName") or ticker,
    }
    _cache.put("fundamentals", ticker, result)
    return result
