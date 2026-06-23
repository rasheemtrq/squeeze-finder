"""
Spot-crypto momentum scanner.

Crypto has no short-interest / gamma / FTD microstructure, so the squeeze model
doesn't apply. This ranks on **trend + volume-confirmed breakout + relative
strength vs BTC** — the same price-only factors the equity swing system uses,
which work on any OHLCV series. BTC is the benchmark (the crypto-native analog
of "vs SPY"); a coin outperforming BTC is showing real relative strength.

Composite (0-100) = 0.30·trend(stage2) + 0.40·breakout + 0.30·RS-vs-BTC.
Each candidate also gets ATR/volume-profile entry/stop/TP levels for sizing.

Pure read path: yfinance OHLCV (cached) only. Places no orders.
"""
from __future__ import annotations

from typing import Any

from src.crypto.universe import to_yf, tradable_pairs
from src.data import prices as prices_data
from src.score.levels import compute_chart_levels
from src.score.swing_factors import (
    score_breakout_volume,
    score_relative_strength,
    score_stage2,
)

WEIGHTS = {"trend": 0.30, "breakout": 0.40, "rs": 0.30}
BENCHMARK = "BTC-USD"


def _flags(trend_sig: dict, br_sig: dict, rs_sig: dict) -> list[str]:
    """Namespaced signal flags (graph convention: '<factor>:<flag>')."""
    flags = ["asset:crypto"]
    for prefix, sig in (("trend", trend_sig), ("ta", br_sig), ("rs", rs_sig)):
        fl = sig.get("flag")
        if fl:
            flags.append(f"{prefix}:{fl}")
    return flags


def score_pair(pair: str, prices: dict, btc_prices: dict | None) -> dict[str, Any] | None:
    """Momentum score + trade levels for one coin, or None if no usable history."""
    bars = prices.get("bars") or []
    if len(bars) < 80:
        return None

    s_trend, sig_trend = score_stage2(prices)
    s_break, sig_break = score_breakout_volume(prices)
    s_rs, sig_rs = score_relative_strength(prices, btc_prices)

    composite = (
        s_trend * WEIGHTS["trend"]
        + s_break * WEIGHTS["breakout"]
        + s_rs * WEIGHTS["rs"]
    )
    try:
        levels = compute_chart_levels(bars)
    except Exception:
        return None

    return {
        "ticker": pair,                       # canonical 'BTC/USD' (Alpaca order symbol)
        "yf_symbol": to_yf(pair),
        "score": round(composite, 1),
        "price": prices.get("close") or bars[-1]["close"],
        "flags": _flags(sig_trend, sig_break, sig_rs),
        "factors": {
            "trend": {"score": round(s_trend, 1), "flag": sig_trend.get("flag")},
            "breakout": {
                "score": round(s_break, 1),
                "rvol": sig_break.get("rvol"),
                "flag": sig_break.get("flag"),
            },
            "rs_vs_btc": {
                "score": round(s_rs, 1),
                "rs_1m_pp": sig_rs.get("rs_1m_pp"),
                "rs_3m_pp": sig_rs.get("rs_3m_pp"),
                "flag": sig_rs.get("flag"),
            },
        },
        "levels": levels,
    }


def scan_crypto(limit: int = 15, min_score: float = 0.0) -> dict[str, Any]:
    """Rank the tradable crypto universe by momentum composite (desc)."""
    pairs = tradable_pairs()

    try:
        btc_prices = prices_data.fetch(BENCHMARK, period="1y")
    except Exception:
        btc_prices = None

    results: list[dict] = []
    errors: list[str] = []
    for pair in pairs:
        try:
            prices = prices_data.fetch(to_yf(pair), period="1y")
        except Exception as e:  # noqa: BLE001 - skip un-loadable coins, keep scanning
            errors.append(f"{pair}: {e}")
            continue
        row = score_pair(pair, prices, btc_prices)
        if row and row["score"] >= min_score:
            results.append(row)

    results.sort(key=lambda r: r["score"], reverse=True)
    return {
        "universe": len(pairs),
        "scored": len(results),
        "errors": errors,
        "results": results[:limit],
    }
