"""
ATR-based risk model + concrete trade plan for swing setups.

Swing reliability comes less from picking *better* and more from cutting
losers fast and letting winners run at a known reward-to-risk. Every swing
candidate therefore gets an explicit plan: entry, a stop placed under
structural support (with a volatility floor), R-multiple targets, and a
position size normalized to a fixed *account-risk* budget.

Position size scales INVERSELY with stop distance — a name whose logical stop
is 4% away earns a much larger allocation than one whose stop is 12% away, for
the same dollar risk. That is the mechanical core of "maximum gains with
managed drawdown": concentrate capital where risk-per-share is smallest.

Pure functions over the price `bundle` (bars = OHLCV dicts). No fetching.
"""
from __future__ import annotations

from typing import Any

ATR_PERIOD = 14
SWING_LOW_LOOKBACK = 10          # bars used to locate the most recent higher-low
STOP_ATR_FLOOR_MULT = 2.0        # volatility floor when structural stop is too tight
STOP_STRUCT_BUFFER_ATR = 0.25    # place structural stop this far under the swing low
DEFAULT_ACCOUNT_RISK_PCT = 1.0   # risk this % of the account per trade
MAX_POSITION_PCT = 25.0          # never allocate more than this to one name
WIDE_STOP_RISK_PCT = 12.0        # risk wider than this = extended/low-quality entry
TIGHT_STOP_RISK_PCT = 6.0        # risk tighter than this = high-quality, low-risk entry
TARGET_R_MULTIPLES = (2.0, 3.0)  # profit targets expressed in units of risk (R)


def atr(bars: list[dict], period: int = ATR_PERIOD) -> float | None:
    """Wilder's Average True Range over `period`. None if insufficient bars."""
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        h = bars[i]["high"]
        lo = bars[i]["low"]
        prev_close = bars[i - 1]["close"]
        trs.append(max(h - lo, abs(h - prev_close), abs(lo - prev_close)))
    if len(trs) < period:
        return None
    a = sum(trs[:period]) / period  # seed = simple average of first `period` TRs
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period  # Wilder smoothing
    return a


def fifty_two_week_high(bars: list[dict]) -> float | None:
    return max((b["high"] for b in bars), default=None) if bars else None


def build_trade_plan(
    prices: dict | None,
    account_risk_pct: float = DEFAULT_ACCOUNT_RISK_PCT,
) -> dict[str, Any] | None:
    """Concrete entry/stop/target/size plan from the price series.

    Stop = max(structural swing-low − 0.25·ATR, volatility floor entry − 2·ATR),
    i.e. we take the *tighter* of the two only when structural support is far
    enough below entry to absorb noise; otherwise the 2·ATR floor protects
    against a too-tight stop. Targets are R-multiples of the per-share risk.
    Position size is the allocation that risks exactly `account_risk_pct` of the
    account if the stop is hit, capped at MAX_POSITION_PCT.
    """
    bars = (prices or {}).get("bars") or []
    if len(bars) < ATR_PERIOD + 2:
        return None

    entry = bars[-1]["close"]
    if entry <= 0:
        return None

    a = atr(bars)
    if not a or a <= 0:
        return None
    atr_pct = a / entry * 100

    swing_low = min(b["low"] for b in bars[-SWING_LOW_LOOKBACK:])
    structural_stop = swing_low - STOP_STRUCT_BUFFER_ATR * a
    vol_stop = entry - STOP_ATR_FLOOR_MULT * a

    # Prefer the structural stop, but never let it sit closer than 0.5·ATR
    # (would get noise-stopped) — fall back to the volatility floor there.
    stop = structural_stop
    if entry - stop < 0.5 * a:
        stop = vol_stop
    # Guard against degenerate data putting the stop at/above entry.
    if stop >= entry:
        stop = vol_stop
    if stop >= entry or stop <= 0:
        return None

    risk_per_share = entry - stop
    risk_pct = risk_per_share / entry * 100

    targets = [round(entry + m * risk_per_share, 4) for m in TARGET_R_MULTIPLES]

    # Account-risk-normalized sizing, independent of account size.
    # allocation% = account_risk% / risk% , capped.
    position_pct = account_risk_pct / (risk_pct / 100)
    position_capped = position_pct > MAX_POSITION_PCT
    position_pct = min(position_pct, MAX_POSITION_PCT)

    high_52w = fifty_two_week_high(bars)
    overhead_to_52w_high_pct = (
        round((high_52w / entry - 1) * 100, 2) if high_52w and high_52w > entry else 0.0
    )

    if risk_pct <= TIGHT_STOP_RISK_PCT:
        grade = "tight"
    elif risk_pct <= WIDE_STOP_RISK_PCT:
        grade = "ok"
    else:
        grade = "wide"

    return {
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "stop_basis": "structural" if stop == structural_stop else "atr_floor",
        "risk_per_share": round(risk_per_share, 4),
        "risk_pct": round(risk_pct, 2),
        "atr": round(a, 4),
        "atr_pct": round(atr_pct, 2),
        "targets": targets,                  # [2R, 3R]
        "target_r_multiples": list(TARGET_R_MULTIPLES),
        "position_pct": round(position_pct, 1),
        "position_capped": position_capped,
        "account_risk_pct": account_risk_pct,
        "overhead_to_52w_high_pct": overhead_to_52w_high_pct,
        "grade": grade,
    }


def risk_quality_multiplier(plan: dict | None) -> float:
    """Reward low-risk (tight-stop, good R:R) entries; penalize extended ones.

    Applied to the swing composite so the rank prefers setups where the same
    dollar move earns more R. Bounded so it adjusts, never dominates, the score.
    """
    if not plan:
        return 1.0
    grade = plan.get("grade")
    if grade == "tight":
        return 1.06
    if grade == "wide":
        return 0.85
    return 1.0
