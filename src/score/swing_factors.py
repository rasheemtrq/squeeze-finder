"""
Per-factor scoring for swing-trade setups.

Different game from squeezes — multi-week trend continuation on improving
fundamentals + sector tailwinds. Catches names like INTC's AI rally or
SNDK's memory-demand breakout *as they're starting*, not after a 3x move.

Five factors blended into a swing-specific composite:

  1. Stage 2 trend         — Weinstein/Minervini classic: price > 50EMA >
                             200EMA, both sloping up, not yet extended.
  2. Volume-confirmed      — breaking 60d high on >=1.5x avg volume, OR
     breakout                OBV trending up before price (smart accumulation).
  3. Relative strength     — outperforming SPY over 1m AND 3m. Real RS,
     vs SPY                   not 1-day noise.
  4. Catalyst              — recent earnings beat, upcoming earnings (mild
                             reuse of squeeze catalyst factor).
  5. Smart money confirm   — insider open-market buying or recent 13D/G.

Each function returns (score_0_100, signals_dict) like the squeeze
factors. Composite weights live in src.swing_scanner.
"""
from __future__ import annotations

import math
from typing import Any


def _clip(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    e = seed
    for v in values[period:]:
        e = float(v) * k + e * (1 - k)
    return e


# -------------------------------------------------------------- Stage 2 ----


def score_stage2(prices: dict | None) -> tuple[float, dict]:
    """Trend-stage detection. Stage 2 = uptrend (price > 50EMA > 200EMA) and,
    per Minervini's trend template, trading near its 52-week high — leaders
    break to new highs rather than languishing mid-range."""
    if not prices:
        return 0.0, {"reason": "no_data"}
    bars = prices.get("bars") or []
    if len(bars) < 220:
        return 0.0, {"reason": "insufficient_history"}

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    if ema50 is None or ema200 is None or ema50 == 0:
        return 0.0, {"reason": "ema_compute_failed"}
    last = closes[-1]

    # 50EMA / 200EMA values 30 bars ago — used to test slope
    ema50_30d_ago = _ema(closes[:-30], 50) if len(closes) > 80 else None
    ema200_30d_ago = _ema(closes[:-30], 200) if len(closes) > 230 else None

    # 52-week range from the (up to) 1y of bars we hold.
    high_52w = max(highs)
    low_52w = min(lows)
    pct_of_52w_high = last / high_52w if high_52w > 0 else 0
    pct_above_52w_low = (last / low_52w - 1) if low_52w > 0 else 0

    score = 0.0
    components: dict[str, Any] = {}

    # Component 1: price above 50EMA (15 pts) — basic uptrend membership
    if last > ema50:
        score += 15
    components["price_above_50ema"] = last > ema50

    # Component 2: 50EMA above 200EMA — golden cross / Stage 2 confirm (25 pts)
    golden = ema50 > ema200
    if golden:
        score += 25
    components["golden_cross"] = golden

    # Component 3: 50EMA sloping up (15 pts)
    slope50 = ema50_30d_ago is not None and ema50 > ema50_30d_ago
    if slope50:
        score += 15
    components["ema50_rising"] = slope50

    # Component 4: 200EMA sloping up (15 pts) — long-term trend health
    slope200 = ema200_30d_ago is not None and ema200 > ema200_30d_ago
    if slope200:
        score += 15
    components["ema200_rising"] = slope200

    # Component 5: proximity to 52-week high (20 pts) — Minervini template.
    # Within 5% of the high is prime; degrade through 15% and 25% bands.
    if pct_of_52w_high >= 0.95:
        score += 20
    elif pct_of_52w_high >= 0.85:
        score += 14
    elif pct_of_52w_high >= 0.75:
        score += 8
    # >25% below the 52w high = not a leader; no points
    components["pct_of_52w_high"] = round(pct_of_52w_high * 100, 1)
    components["pct_above_52w_low"] = round(pct_above_52w_low * 100, 1)

    # Component 6: extension from 50EMA — penalize blowoff tops (10 pts)
    extension = last / ema50
    if extension <= 1.10:
        score += 10
    elif extension <= 1.20:
        score += 7
    elif extension <= 1.35:
        score += 3
    # >1.35 = extended; no points
    components["price_vs_ema50_pct"] = round((extension - 1) * 100, 1)

    flag = None
    if golden and slope50 and slope200 and last > ema50 and extension <= 1.20 and pct_of_52w_high >= 0.85:
        flag = "stage2_clean"
    elif pct_of_52w_high >= 0.98 and golden:
        flag = "new_52w_high"
    elif extension > 1.40:
        flag = "extended"
    elif not golden:
        flag = "stage1_or_4"

    return _clip(score), {
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        **components,
        "flag": flag,
    }


# -------------------------------- Volume-confirmed breakout / OBV --------


def _obv(closes: list[float], volumes: list[int]) -> list[float]:
    """On-Balance Volume series."""
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


def score_breakout_volume(prices: dict | None) -> tuple[float, dict]:
    """Detects breakout-on-volume OR OBV-leading-price (institutional accum)."""
    if not prices:
        return 0.0, {"reason": "no_data"}
    bars = prices.get("bars") or []
    if len(bars) < 80:
        return 0.0, {"reason": "insufficient_history"}

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    volumes = [int(b["volume"]) for b in bars]

    last_close = closes[-1]
    prior_60d_high = max(highs[-61:-1])
    vol_20_avg = sum(volumes[-21:-1]) / 20 if sum(volumes[-21:-1]) > 0 else 0
    rvol = volumes[-1] / vol_20_avg if vol_20_avg > 0 else 0

    score = 0.0
    components: dict[str, Any] = {}

    # Component A: live breakout above prior 60d high (40 pts)
    breaking_out = last_close > prior_60d_high
    if breaking_out:
        if rvol >= 2.0:
            score += 40
        elif rvol >= 1.5:
            score += 30
        elif rvol >= 1.2:
            score += 15
        # rvol < 1.2 on a "breakout" = suspect, no points
    components["breaking_60d_high"] = breaking_out
    components["rvol"] = round(rvol, 2)

    # Component B: OBV trending up over last 20 bars (institutional accum, 30 pts)
    obv = _obv(closes, volumes)
    obv_now = obv[-1]
    obv_20d_ago = obv[-21] if len(obv) >= 21 else 0
    obv_uptrend = obv_now > obv_20d_ago and obv_20d_ago != 0
    if obv_uptrend:
        # Magnitude bonus — bigger jump = stronger accumulation
        obv_pct_change = (obv_now - obv_20d_ago) / max(abs(obv_20d_ago), 1)
        if obv_pct_change >= 0.50:
            score += 30
        elif obv_pct_change >= 0.20:
            score += 20
        elif obv_pct_change > 0:
            score += 10
    components["obv_uptrend_20d"] = obv_uptrend

    # Component C: tight base (low close-to-close vol over last 20d) preceded
    # by today's expansion = "coiled spring" (30 pts)
    recent_closes = closes[-21:-1]
    if len(recent_closes) >= 10 and recent_closes[0] > 0:
        std = (sum((c / recent_closes[0] - 1) ** 2 for c in recent_closes) / len(recent_closes)) ** 0.5
        # Low vol base = std < 5%; today moved >2% on rvol >= 1.5
        if std < 0.05 and abs(last_close / closes[-2] - 1) >= 0.02 and rvol >= 1.5:
            score += 30
            components["coiled_spring"] = True
        else:
            components["coiled_spring"] = False
        components["base_vol_pct"] = round(std * 100, 2)

    flag = None
    if breaking_out and rvol >= 2.0:
        flag = "breakout_high_vol"
    elif components.get("coiled_spring"):
        flag = "coiled_spring_pop"
    elif obv_uptrend and not breaking_out:
        flag = "accumulating"
    elif breaking_out:
        flag = "breakout_low_vol"

    return _clip(score), {**components, "flag": flag}


# -------------------------------- Relative Strength vs SPY --------------


def score_relative_strength(prices: dict | None, spy_prices: dict | None) -> tuple[float, dict]:
    """Outperforming SPY over 1m AND 3m AND 6m. Real RS, not noise."""
    if not prices or not spy_prices:
        return 0.0, {"reason": "no_data"}
    bars = prices.get("bars") or []
    spy_bars = spy_prices.get("bars") or []
    if len(bars) < 130 or len(spy_bars) < 130:
        return 0.0, {"reason": "insufficient_history"}

    def _pct(b: list[dict], days: int) -> float | None:
        if len(b) <= days:
            return None
        p_now = b[-1]["close"]
        p_then = b[-1 - days]["close"]
        if p_then == 0:
            return None
        return (p_now / p_then - 1) * 100

    ticker_1m, ticker_3m, ticker_6m = _pct(bars, 21), _pct(bars, 63), _pct(bars, 126)
    spy_1m, spy_3m, spy_6m = _pct(spy_bars, 21), _pct(spy_bars, 63), _pct(spy_bars, 126)

    if any(v is None for v in (ticker_1m, ticker_3m, spy_1m, spy_3m)):
        return 0.0, {"reason": "compute_failed"}

    rs_1m = ticker_1m - spy_1m
    rs_3m = ticker_3m - spy_3m
    rs_6m = ticker_6m - spy_6m if ticker_6m is not None and spy_6m is not None else 0

    score = 0.0
    # 1-month RS: 30 pts. +5pp = 15, +10pp = 30
    if rs_1m > 0:
        score += min(30, rs_1m * 3)
    # 3-month RS: 40 pts. +10pp = 20, +25pp = 40
    if rs_3m > 0:
        score += min(40, rs_3m * 1.6)
    # 6-month RS: 30 pts. +20pp = 15, +50pp = 30
    if rs_6m > 0:
        score += min(30, rs_6m * 0.6)

    flag = None
    if rs_1m > 0 and rs_3m > 0 and rs_6m > 0:
        flag = "rs_leader" if rs_3m >= 20 else "rs_positive"
    elif rs_1m < -10 and rs_3m < -10:
        flag = "rs_laggard"

    return _clip(score), {
        "ticker_1m_pct": round(ticker_1m, 1),
        "ticker_3m_pct": round(ticker_3m, 1),
        "ticker_6m_pct": round(ticker_6m, 1) if ticker_6m is not None else None,
        "spy_1m_pct": round(spy_1m, 1),
        "spy_3m_pct": round(spy_3m, 1),
        "rs_1m_pp": round(rs_1m, 1),
        "rs_3m_pp": round(rs_3m, 1),
        "rs_6m_pp": round(rs_6m, 1),
        "flag": flag,
    }


# -------------------------------- Catalyst (swing-flavored) --------------


def score_swing_catalyst(catalysts: dict | None, fundamentals: dict | None) -> tuple[float, dict]:
    """Earnings proximity + recent EPS surprise (if available)."""
    if not catalysts:
        return 0.0, {"reason": "no_data"}

    next_event = catalysts.get("next_event") or {}
    dte = catalysts.get("days_to_event")
    score = 0.0
    components: dict[str, Any] = {}

    # Earnings proximity — swings benefit from a near event but less binary
    # than squeezes; widen the window to 60d
    if dte is not None and dte <= 60:
        if dte <= 14:
            score += 50  # imminent earnings = potential trend trigger
        elif dte <= 30:
            score += 35
        else:
            score += 20
    components["days_to_event"] = dte
    components["next_event_kind"] = (next_event.get("kind") or "").lower()

    # EPS surprise from yfinance fundamentals if present (best-effort)
    eps_estimate = next_event.get("eps_estimate")
    components["eps_estimate"] = eps_estimate

    flag = None
    if dte is not None and dte <= 14:
        flag = "earnings_imminent"
    elif dte is not None and dte <= 30:
        flag = "earnings_near"

    return _clip(score), {**components, "flag": flag}


# -------------------------------- Smart-money confirm --------------------


def score_swing_smart_money(insiders: dict | None, inst_holders: dict | None) -> tuple[float, dict]:
    """Insider buying or recent 13D/G filing — same as squeeze, scored softer."""
    score = 0.0
    components: dict[str, Any] = {}

    if insiders:
        buy_value = insiders.get("total_buy_value_usd") or 0
        n_buyers = insiders.get("distinct_buyers") or insiders.get("distinct_insiders") or 0
        cluster = bool(insiders.get("cluster_buying"))
        sell_value = insiders.get("total_sell_value_usd") or 0
        components.update({
            "insider_buy_value_usd": buy_value,
            "insider_distinct_buyers": n_buyers,
            "insider_cluster": cluster,
            "insider_sell_value_usd": sell_value,
        })
        if buy_value >= 250_000:
            score += min(40, 10 + math.log10(max(buy_value / 250_000, 1)) * 14)
        if cluster:
            score = max(score, 35)
        # Penalty for net selling
        if sell_value > buy_value * 2 and sell_value >= 1_000_000:
            score -= 15

    if inst_holders:
        n_active = inst_holders.get("n_active") or 0
        n_passive = inst_holders.get("n_passive") or 0
        days_since = inst_holders.get("days_since_most_recent")
        components.update({
            "inst_active_filings": n_active,
            "inst_passive_filings": n_passive,
            "inst_days_since": days_since,
        })
        if n_active or n_passive:
            base = 25 * min(n_active, 2) + 10 * min(n_passive, 2)  # max 70
            recency_mult = (
                1.0 if days_since is None or days_since <= 14
                else 0.7 if days_since <= 30
                else 0.4 if days_since <= 60
                else 0.2
            )
            score += min(60, base * recency_mult)

    score = _clip(score)

    flag = None
    if components.get("insider_cluster"):
        flag = "insider_cluster_buying"
    elif (components.get("inst_active_filings") or 0) >= 1 and (components.get("inst_days_since") or 999) <= 30:
        flag = "activist_filed"
    elif (components.get("insider_buy_value_usd") or 0) >= 1_000_000:
        flag = "insider_buying"
    elif (components.get("insider_sell_value_usd") or 0) > 5_000_000:
        flag = "insiders_dumping"

    return score, {**components, "flag": flag}


# -------------------------------- Composite -----------------------------


SWING_WEIGHTS = {
    "stage2": 0.30,
    "breakout": 0.25,
    "rs": 0.20,
    "catalyst": 0.15,
    "smart_money": 0.10,
}


def compute_swing(bundle: dict[str, Any], spy_prices: dict | None = None) -> dict[str, Any]:
    """Compute all 5 swing factors from a (squeeze-style) bundle plus SPY prices."""
    s_st, sig_st = score_stage2(bundle.get("prices"))
    s_br, sig_br = score_breakout_volume(bundle.get("prices"))
    s_rs, sig_rs = score_relative_strength(bundle.get("prices"), spy_prices)
    s_cat, sig_cat = score_swing_catalyst(bundle.get("catalysts"), bundle.get("fundamentals"))
    s_sm, sig_sm = score_swing_smart_money(bundle.get("insiders"), bundle.get("inst_holders"))

    return {
        "stage2": {"score": round(s_st, 1), "signals": sig_st},
        "breakout": {"score": round(s_br, 1), "signals": sig_br},
        "rs": {"score": round(s_rs, 1), "signals": sig_rs},
        "catalyst": {"score": round(s_cat, 1), "signals": sig_cat},
        "smart_money": {"score": round(s_sm, 1), "signals": sig_sm},
    }


def composite_swing(factors: dict, weights: dict[str, float] | None = None) -> float:
    w = weights or SWING_WEIGHTS
    total = sum(factors[k]["score"] * w[k] for k in SWING_WEIGHTS)
    return round(total, 1)


def compute_price_only(prices: dict | None, spy_prices: dict | None = None) -> float:
    """Cheap price-only swing score for the large-universe prefilter.

    Uses only the three factors that need OHLCV alone (stage2, breakout, RS) —
    75% of the full composite weight — renormalized to 0-100. Lets us rank a
    ~500-name universe on one price fetch each before paying for the expensive
    catalyst/insider enrichment on the survivors.
    """
    s_st, _ = score_stage2(prices)
    s_br, _ = score_breakout_volume(prices)
    s_rs, _ = score_relative_strength(prices, spy_prices)
    w = SWING_WEIGHTS
    denom = w["stage2"] + w["breakout"] + w["rs"]
    return round((s_st * w["stage2"] + s_br * w["breakout"] + s_rs * w["rs"]) / denom, 1)


def collect_swing_flags(factors: dict) -> list[str]:
    flags = []
    for key in SWING_WEIGHTS:
        flag = factors[key]["signals"].get("flag")
        if flag:
            flags.append(f"{key}:{flag}")
    return flags
