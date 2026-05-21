from __future__ import annotations

import math

from src.config import DEFAULT_WEIGHTS

# Sentiment gate centered at SI=10%. At SI<10% there's no meaningful short
# base to squeeze — Allen et al. 2025 mechanism. Sigmoid-dampened sentiment
# weight; the lost weight is redistributed pro-rata to the other 4 factors
# so the composite still sums to 1.0.
SENTIMENT_GATE_CENTER_PCT = 10.0  # in percent
SENTIMENT_GATE_STEEPNESS = 5.0    # in percent — wider = gentler ramp


def _sentiment_gate(si_pct_float: float | None) -> float:
    """Sigmoid in [0, 1]. SI=0% → ~0.12, 5% → ~0.27, 10% → 0.50, 15% → ~0.73, 20% → ~0.88."""
    si = (si_pct_float or 0) * 100  # convert decimal to percent
    return 1.0 / (1.0 + math.exp(-(si - SENTIMENT_GATE_CENTER_PCT) / SENTIMENT_GATE_STEEPNESS))


def gated_weights(weights: dict[str, float], fund: dict | None) -> dict[str, float]:
    """Apply the SI-gated sentiment dampener; redistribute lost weight pro-rata."""
    w = dict(weights)
    si_pct = (fund or {}).get("short_percent_of_float") or 0
    gate = _sentiment_gate(si_pct)
    w_sent_orig = w["sentiment"]
    w["sentiment"] = w_sent_orig * gate
    lost = w_sent_orig - w["sentiment"]
    if lost > 0:
        others = [k for k in w if k != "sentiment"]
        other_total = sum(w[k] for k in others)
        if other_total > 0:
            for k in others:
                w[k] += lost * (w[k] / other_total)
    return w


def composite(
    factors: dict,
    weights: dict[str, float] | None = None,
    fund: dict | None = None,
) -> float:
    """Linear-weighted 5-factor composite. When `fund` is supplied, the
    sentiment weight is gated by SI%float (no shorts, no squeeze).
    """
    w = weights or DEFAULT_WEIGHTS
    if fund is not None:
        w = gated_weights(w, fund)
    total = sum(
        factors[k]["score"] * w[k]
        for k in ("sentiment", "options", "si", "ta", "catalyst")
    )
    return round(total, 1)


def collect_flags(factors: dict) -> list[str]:
    flags = []
    for key in ("sentiment", "options", "si", "ta", "catalyst"):
        flag = factors[key]["signals"].get("flag")
        if flag:
            flags.append(f"{key}:{flag}")
    return flags


def is_red_flag(bundle: dict) -> tuple[bool, str | None]:
    """Auto-exclude rules from squeeze-thesis skill."""
    fund = bundle.get("fundamentals") or {}
    prices = bundle.get("prices") or {}

    mcap = fund.get("market_cap") or 0
    if 0 < mcap < 50_000_000:
        avg_dollar_vol = (fund.get("avg_volume_30d") or 0) * (prices.get("close") or 0)
        if avg_dollar_vol < 5_000_000:
            return True, "illiquid"

    bars = prices.get("bars") or []
    if len(bars) > 60:
        sixty_day_return = (bars[-1]["close"] / bars[-61]["close"]) - 1
        if sixty_day_return > 2.0:
            return False, "post_blowoff"  # demote, not exclude
    if len(bars) > 5:
        five_day_return = (bars[-1]["close"] / bars[-6]["close"]) - 1
        if five_day_return > 0.50:
            return False, "late_party"  # demote, not exclude

    return False, None
