"""
US-equity market regime classifier.

Squeezes are dispersion-fueled: when the broad market is in risk-off, retail
flows out of speculative names, gamma chases unwind, and even the cleanest
setup gets steamrolled. Conversely a risk-on regime amplifies the same
setup. This module turns SPY trend + VIX into a single multiplier we apply
to the composite score so the scan adapts to context instead of pretending
2024-style chop is the same as 2021-style frothy momentum.

Classification (read top-to-bottom; first match wins):
- risk_off : SPY < 50d EMA OR VIX > 25         -> 0.70x composite
- frothy   : SPY > 50d EMA AND VIX < 14        -> 1.05x (mild, frothy
             markets sometimes punish vol-chasers)
- risk_on  : default (SPY > 50d EMA, VIX 14-25) -> 1.00x

Free, single yfinance call; cached 1 hour.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import yfinance as yf

from src.data import _cache
from src.data.prices import DataUnavailable

CACHE_TTL_SECONDS = 3600
EMA_LOOKBACK = 50


def _ema(series, period: int) -> float | None:
    """Standard EMA, returns the last value or None if insufficient data."""
    if len(series) < period:
        return None
    k = 2 / (period + 1)
    ema = float(series.iloc[0])
    for v in series.iloc[1:]:
        ema = float(v) * k + ema * (1 - k)
    return ema


def fetch(force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = _cache.get("regime", "us_equity", CACHE_TTL_SECONDS)
        if cached:
            return cached

    try:
        spy_hist = yf.Ticker("SPY").history(period="6mo", auto_adjust=True)
        vix_hist = yf.Ticker("^VIX").history(period="5d", auto_adjust=False)
    except Exception as e:
        raise DataUnavailable(f"regime fetch failed: {e}") from e

    if spy_hist.empty or vix_hist.empty:
        raise DataUnavailable("regime fetch returned empty SPY/VIX series")

    spy_close = float(spy_hist["Close"].iloc[-1])
    spy_ema = _ema(spy_hist["Close"], EMA_LOOKBACK)
    vix_close = float(vix_hist["Close"].iloc[-1])

    if spy_ema is None:
        raise DataUnavailable(f"insufficient SPY history for {EMA_LOOKBACK}d EMA")

    spy_above_ema = spy_close > spy_ema
    spy_distance_pct = (spy_close / spy_ema - 1) * 100

    if not spy_above_ema or vix_close > 25:
        regime = "risk_off"
        multiplier = 0.70
    elif spy_above_ema and vix_close < 14:
        regime = "frothy"
        multiplier = 1.05
    else:
        regime = "risk_on"
        multiplier = 1.00

    result = {
        "as_of": datetime.now(UTC).isoformat(),
        "spy_close": round(spy_close, 2),
        "spy_50d_ema": round(spy_ema, 2),
        "spy_above_ema": spy_above_ema,
        "spy_distance_pct": round(spy_distance_pct, 2),
        "vix": round(vix_close, 2),
        "regime": regime,
        "multiplier": multiplier,
    }
    _cache.put("regime", "us_equity", result)
    return result
