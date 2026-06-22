from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf

from src.config import CACHE_TTL, FINNHUB_API_KEY
from src.data import _cache
from src.data.prices import DataUnavailable
from src.data.finnhub import fetch_profile as finnhub_profile


def fetch(ticker: str, force_refresh: bool = False) -> dict:
    """
    Returns dict with float, short interest, days-to-cover, market cap,
    held_percent_institutions/insiders (for squeeze congestion amplifier).
    yfinance .info is a cached aggregate from multiple sources; SI data here
    comes originally from FINRA but staleness is opaque.
    """
    if not force_refresh:
        cached = _cache.get("fundamentals", ticker, CACHE_TTL["fundamentals"])
        if cached:
            return cached

    # Finnhub is now the default for profile / market data (much more reliable + generous free tier)
    profile = None
    if FINNHUB_API_KEY:
        try:
            profile = finnhub_profile(ticker)
        except Exception:
            profile = None

    # Always fall back to yfinance for full history + short interest data
    tk = yf.Ticker(ticker)
    try:
        info = tk.info or {}
    except Exception as e:
        info = {}

    # Merge: prefer Finnhub profile data where available
    if profile:
        float_shares = profile.get("float_shares") or profile.get("shares_outstanding") or info.get("floatShares") or info.get("sharesOutstanding")
        market_cap = profile.get("market_cap") or info.get("marketCap")
        shares_outstanding = profile.get("shares_outstanding") or info.get("sharesOutstanding")
        sector = profile.get("sector") or info.get("sector")
        name = profile.get("name") or info.get("longName") or info.get("shortName") or ticker
    else:
        float_shares = info.get("floatShares") or info.get("sharesOutstanding")
        market_cap = info.get("marketCap")
        shares_outstanding = info.get("sharesOutstanding")
        sector = info.get("sector")
        name = info.get("longName") or info.get("shortName") or ticker

    shares_short = info.get("sharesShort")
    si_pct = None
    if shares_short and float_shares:
        si_pct = shares_short / float_shares

    price = (profile or {}).get("current_price") or info.get("regularMarketPrice") or info.get("currentPrice")
    if not price:
        raise DataUnavailable(f"no usable price for {ticker}")

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "price": price,
        "market_cap": market_cap,
        "float_shares": float_shares,
        "shares_outstanding": shares_outstanding,
        "shares_short": shares_short,
        "shares_short_prior_month": info.get("sharesShortPriorMonth"),
        "short_ratio": info.get("shortRatio"),
        "short_percent_of_float": info.get("shortPercentOfFloat") or si_pct,
        "shares_short_date": info.get("dateShortInterest"),
        "avg_volume_30d": info.get("averageVolume") or info.get("averageDailyVolume10Day"),
        "sector": sector,
        "name": name,
        "held_percent_institutions": info.get("heldPercentInstitutions"),
        "held_percent_insiders": info.get("heldPercentInsiders"),
        "finnhub_profile_used": bool(profile),
    }
    _cache.put("fundamentals", ticker, result)
    return result
