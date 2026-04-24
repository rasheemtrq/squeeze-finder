from __future__ import annotations

from src.config import DEFAULT_WEIGHTS


def composite(factors: dict, weights: dict[str, float] | None = None) -> float:
    w = weights or DEFAULT_WEIGHTS
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
    if len(bars) >= 5:
        five_day_return = (bars[-1]["close"] / bars[-6]["close"]) - 1 if len(bars) > 5 else 0
        if five_day_return > 0.50:
            return False, "late_party"  # demote, not exclude

    return False, None
