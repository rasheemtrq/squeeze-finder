"""
Per-factor scoring functions. Each returns (score_0_100, signals_dict).
Signals dict contains the raw inputs + interpretation flags used to populate
the UI factor breakdown and the `ticker-deepdive` output.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


def _clip(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


def _score_stocktwits(st: dict) -> tuple[float, dict]:
    n = st["messages_sampled"]
    bull = st["bull_ratio"]
    classified = st["bullish"] + st["bearish"]
    lookback = st.get("lookback_hours", 0)
    velocity = st.get("msg_velocity")
    bull_baseline = st.get("bull_ratio_baseline")

    base = {
        "st_n": n,
        "st_bull_ratio": bull,
        "st_bullish": st["bullish"],
        "st_bearish": st["bearish"],
        "st_lookback_hours": lookback,
        "st_msg_velocity": velocity,
        "st_bull_baseline": bull_baseline,
    }

    if n < 20 or classified < 10:
        return _clip(30 + (bull - 0.5) * 20, 0, 50), {**base, "st_flag": "low_sample"}

    volume_score = _clip(math.log2(max(n, 1) / 10) * 12, 0, 40)
    ratio_score = (bull - 0.5) * 80
    activity_bonus = 20 if n >= 100 else (10 if n >= 50 else 0)

    # Velocity bonus mirrors WSB: 2x baseline → +15, 3x → +25, capped 25.
    # Penalize a clear fade (≤0.5x baseline) by –10. Bullish drift (current bull
    # ratio meaningfully above its 7d baseline) adds another small bump.
    velocity_bonus = 0
    if velocity is not None:
        if velocity > 1:
            velocity_bonus = min(25, (velocity - 1) * 12)
        elif velocity < 0.5:
            velocity_bonus = -10
    bull_drift_bonus = 0
    if bull_baseline is not None and bull - bull_baseline >= 0.10 and n >= 30:
        bull_drift_bonus = 8

    score = _clip(
        volume_score + ratio_score + activity_bonus + velocity_bonus + bull_drift_bonus + 20,
        0,
        100,
    )

    st_flag = None
    if velocity is not None and velocity >= 2 and bull >= 0.60:
        st_flag = "velocity_surge"
    elif n >= 50 and bull >= 0.70:
        st_flag = "hot"
    elif bull <= 0.35:
        st_flag = "bearish_crowd"
    elif lookback and lookback < 4 and n >= 50:
        st_flag = "velocity_spike"

    return score, {**base, "st_flag": st_flag}


def _score_wsb(wsb: dict) -> tuple[float, dict]:
    """Apewisdom WSB rank + mention velocity."""
    rank = wsb["rank"]
    mentions = wsb["mentions"]
    velocity = wsb.get("velocity")
    rank_prior = wsb.get("rank_24h_ago")

    rank_component = 100 * (101 - min(rank, 100)) / 100  # rank 1 → 100, 100 → 1
    velocity_component = 0
    if velocity is not None and velocity > 1:
        velocity_component = min(30, (velocity - 1) * 30)
    elif velocity is not None and velocity < 1:
        velocity_component = max(-15, (velocity - 1) * 30)

    rank_momentum = 0
    if rank_prior:
        rank_delta = rank_prior - rank  # positive = rank improved
        rank_momentum = max(-10, min(15, rank_delta * 0.5))

    score = _clip(rank_component * 0.7 + velocity_component + rank_momentum + 10)

    wsb_flag = None
    if rank <= 10 and velocity and velocity >= 2:
        wsb_flag = "wsb_surge"
    elif rank <= 20:
        wsb_flag = "wsb_top20"
    elif velocity and velocity >= 2:
        wsb_flag = "wsb_accelerating"
    elif velocity and velocity < 0.5:
        wsb_flag = "wsb_fading"

    return score, {
        "wsb_rank": rank,
        "wsb_mentions": mentions,
        "wsb_upvotes": wsb.get("upvotes"),
        "wsb_rank_24h_ago": rank_prior,
        "wsb_velocity": velocity,
        "wsb_flag": wsb_flag,
    }


def score_sentiment(st: dict | None, wsb: dict | None = None) -> tuple[float, dict]:
    """Blends StockTwits (broad retail) + Apewisdom WSB (squeeze-specific)."""
    if not st and not wsb:
        return 0.0, {"reason": "no_data"}

    st_score = None
    st_signals: dict = {}
    if st:
        st_score, st_signals = _score_stocktwits(st)

    wsb_score = None
    wsb_signals: dict = {"wsb_in_top100": False}
    if wsb:
        wsb_score, wsb_signals = _score_wsb(wsb)
        wsb_signals["wsb_in_top100"] = True

    if st_score is not None and wsb_score is not None:
        score = 0.5 * st_score + 0.5 * wsb_score
    elif wsb_score is not None:
        score = wsb_score * 0.85
    else:
        score = st_score or 0

    flag = None
    st_flag = st_signals.get("st_flag")
    wsb_flag = wsb_signals.get("wsb_flag")
    if st_flag in ("hot", "velocity_surge") and wsb_flag in ("wsb_surge", "wsb_top20", "wsb_accelerating"):
        flag = "convergent_bullish"
    elif st_flag == "velocity_surge":
        flag = "velocity_surge"
    elif wsb_flag == "wsb_surge":
        flag = "wsb_surge"
    elif st_flag == "hot":
        flag = "hot"
    elif st_flag == "bearish_crowd" or wsb_flag == "wsb_fading":
        flag = st_flag or wsb_flag

    return score, {**st_signals, **wsb_signals, "flag": flag}


def _realized_vol_annualized(prices: dict | None, lookback: int = 20) -> float | None:
    """Annualized 20d realized vol from daily log-returns. Returns None if insufficient bars."""
    if not prices:
        return None
    bars = prices.get("bars") or []
    if len(bars) < lookback + 1:
        return None
    closes = [b["close"] for b in bars[-(lookback + 1):]]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < lookback // 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def score_options(opt: dict | None, prices: dict | None = None) -> tuple[float, dict]:
    if not opt:
        return 0.0, {"reason": "no_data"}

    cpr = opt["call_put_ratio"] or 0
    gamma = opt["gamma_concentration"] or 0
    dte = opt["days_to_expiry"] or 99
    call_oi = opt["call_oi"]
    put_oi = opt["put_oi"]
    total_oi = (call_oi or 0) + (put_oi or 0)
    iv_skew = opt.get("iv_skew_ratio")
    atm_iv = opt.get("atm_iv_avg")

    # Six components: CPR 25, gamma 25, DTE 15, IV-skew 15, IV/HV 10,
    # unusual-volume 10. Total raw cap 100.
    cpr_component = _clip(12 * math.log2(max(cpr, 0.25)) + 12, 0, 25) if cpr > 0 else 0
    gamma_component = _clip(gamma * 65, 0, 25)
    dte_component = 15 if dte <= 14 else (8 if dte <= 30 else 0)

    # IV skew — calls bid up vs puts is bullish positioning. Ratio of 1.0 is
    # neutral; >1.05 begins to score, peaks at +1.20.
    iv_skew_component = 0.0
    if iv_skew and iv_skew > 1.0:
        iv_skew_component = _clip((iv_skew - 1.0) / 0.20 * 15, 0, 15)

    # IV/HV — when implied vastly exceeds realized, market is pricing a move
    # (positioning ahead of catalyst). Ratio 1.5 begins to score, peaks at 3.0+.
    hv = _realized_vol_annualized(prices)
    iv_hv_ratio: float | None = None
    iv_hv_component = 0.0
    if hv and hv > 0 and atm_iv:
        iv_hv_ratio = atm_iv / hv
        if iv_hv_ratio > 1.5:
            iv_hv_component = _clip((iv_hv_ratio - 1.5) / 1.5 * 10, 0, 10)

    # Unusual options volume — strikes where today's volume >= 2x OI on
    # near-money strikes, indicating new positions opened. Net call vs put
    # premium tells direction; we score the bullish side (call premium > put).
    unusual_call_n = opt.get("unusual_call_strikes_n") or 0
    unusual_put_n = opt.get("unusual_put_strikes_n") or 0
    unusual_call_prem = opt.get("unusual_call_premium_usd") or 0
    unusual_put_prem = opt.get("unusual_put_premium_usd") or 0
    net_unusual_premium = unusual_call_prem - unusual_put_prem
    unusual_component = 0.0
    if unusual_call_n >= 1 and net_unusual_premium > 0:
        # Scale: $100k net call premium = 4 pts, $1M = 8 pts, $5M+ = full 10.
        unusual_component = _clip(
            math.log10(max(net_unusual_premium / 100_000, 1)) * 5 + 2,
            0,
            10,
        )

    raw = _clip(
        cpr_component + gamma_component + dte_component
        + iv_skew_component + iv_hv_component + unusual_component
    )

    # Liquidity scaling — chains with thin OI shouldn't be able to fully carry
    # the factor. Linear ramp: at 0 OI score is 0; at 5000+ OI it's unaffected.
    liquidity_mult = min(1.0, total_oi / 5000) if total_oi > 0 else 0.0
    score = _clip(raw * liquidity_mult)

    flag = None
    if total_oi < 500:
        flag = "untradable_chain"
    elif unusual_call_n >= 3 and net_unusual_premium >= 1_000_000:
        flag = "smart_call_flow"
    elif iv_skew and iv_skew >= 1.10 and gamma >= 0.3:
        flag = "call_skew"
    elif iv_hv_ratio and iv_hv_ratio >= 2.0 and dte <= 30:
        flag = "iv_rich"
    elif gamma >= 0.4 and dte <= 14:
        flag = "gamma_setup"
    elif cpr >= 3:
        flag = "call_heavy"
    elif iv_hv_ratio and iv_hv_ratio < 0.8:
        flag = "iv_cheap"
    elif total_oi < 1000:
        flag = "thin_options"

    return score, {
        "call_put_ratio": cpr,
        "gamma_concentration": gamma,
        "days_to_expiry": dte,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "total_oi": total_oi,
        "atm_call_iv": opt.get("atm_call_iv"),
        "atm_put_iv": opt.get("atm_put_iv"),
        "iv_skew_ratio": iv_skew,
        "atm_iv_avg": atm_iv,
        "hv_20d": round(hv, 4) if hv else None,
        "iv_hv_ratio": round(iv_hv_ratio, 3) if iv_hv_ratio else None,
        "unusual_call_n": unusual_call_n,
        "unusual_put_n": unusual_put_n,
        "unusual_call_premium_usd": unusual_call_prem,
        "unusual_put_premium_usd": unusual_put_prem,
        "net_unusual_premium_usd": round(net_unusual_premium, 2),
        "liquidity_mult": round(liquidity_mult, 3),
        "flag": flag,
    }


def score_si(
    fund: dict | None,
    finra: dict | None = None,
    insiders: dict | None = None,
    inst_holders: dict | None = None,
) -> tuple[float, dict]:
    """
    Combines structural SI (yf: % float, DTC) with FINRA daily short-volume
    momentum (trend + latest ratio), an insider-buying contrarian bonus from
    SEC Form 4, and a 13D/13G institutional-holder lift. Insider open-market
    purchases by directors / officers / 10%-owners on a heavily-shorted name
    is the textbook squeeze precondition; a fresh 13D filing (5%+ activist)
    is the institutional-scale version of the same signal.
    """
    if not fund:
        return 0.0, {"reason": "no_data"}

    si_pct = fund.get("short_percent_of_float") or 0
    dtc = fund.get("short_ratio") or 0
    si_date = fund.get("shares_short_date")
    sector = fund.get("sector")

    # Sector-adjusted SI: a 20% SI biotech is base-rate; a 20% SI mega-cap
    # tech is extraordinary. si_pct_normalized maps raw SI%float onto a
    # 0..1 percentile within the ticker's sector. Multiply by 35 for the
    # pct_component magnitude (unchanged from previous absolute design).
    from src.score.sectors import si_pct_normalized
    pct_component = 35 * si_pct_normalized(si_pct, sector) if si_pct else 0
    dtc_component = 25 * min(dtc / 10, 1) if dtc else 0

    finra_component = 0
    finra_info: dict = {}
    if finra and finra.get("latest_short_ratio") is not None:
        latest = finra["latest_short_ratio"]
        avg = finra["avg_short_ratio"]
        trend = finra.get("trend")
        finra_info = {
            "finra_latest_short_ratio": latest,
            "finra_avg_short_ratio": avg,
            "finra_trend": trend,
            "finra_latest_date": finra.get("latest_date"),
        }
        # high short-vol ratio (>40% of daily volume sold short) = active pressure
        finra_component = 25 * min(max(latest - 0.30, 0) / 0.30, 1)
        if trend == "rising":
            finra_component += 4
        elif trend == "falling":
            finra_component -= 4
        # "Shorts piling in" is the most reliable historical pre-squeeze
        # signal in the harness (4 of 12 cases fired before the squeeze).
        # Lift the FINRA component when both gates are hit. Cap stays at 25
        # *5 = up to 30 once this is added so the structural-only component
        # can't pin the factor on its own.
        if latest >= 0.50 and trend == "rising":
            finra_component += 8
        finra_component = max(0, min(33, finra_component))

    # Insider open-market buying — contrarian bullish, scaled by total $ value
    # and amplified for cluster buying (3+ insiders within 14d). Insider
    # SELLING is a separate red flag handled below: it doesn't reduce the buy
    # component (we keep both signals distinct) but emits a dumping demote
    # when the sell side dominates.
    insider_component = 0.0
    insider_info: dict = {}
    insider_dump_demote = 0.0
    if insiders:
        total_value = insiders.get("total_buy_value_usd") or 0
        distinct = insiders.get("distinct_insiders") or 0
        cluster = bool(insiders.get("cluster_buying"))
        sell_value = insiders.get("total_sell_value_usd") or 0
        sell_distinct = insiders.get("distinct_sellers") or 0
        sell_cluster = bool(insiders.get("cluster_selling"))
        insider_info = {
            "insider_buy_value_usd": total_value,
            "insider_distinct_buyers": distinct,
            "insider_cluster": cluster,
            "insider_sell_value_usd": sell_value,
            "insider_distinct_sellers": sell_distinct,
            "insider_cluster_selling": sell_cluster,
        }
        # $250k = 5 pts, $1M = 10 pts, $5M+ = full 15.
        if total_value >= 250_000:
            insider_component = _clip(
                5 + math.log10(max(total_value / 250_000, 1)) * 7,
                0,
                15,
            )
        if cluster:
            insider_component = max(insider_component, 12)
        # Without high SI, insider buying alone shouldn't carry the factor —
        # scale by the structural SI signal so it amplifies rather than substitutes.
        # Use the sector's median SI as the "1.0x" floor: SI at sector median
        # gets full amplifier, below that scales down.
        from src.score.sectors import sector_reference as _sref
        sector_median, _, _ = _sref(sector)
        si_amplifier = min(1.0, max(si_pct, 0) / max(sector_median, 0.01)) if si_pct else 0.3
        insider_component *= si_amplifier

        # Insider-dumping demote (Reddit-corpus signal: insiders cashing out
        # into a squeeze is a recurring end-of-move pattern). Triggers on
        # cluster-selling OR $5M+ in net sales (sells > 2x buys), gated on
        # an actual SI signal so we don't penalize routine post-vest sales
        # at non-shorted names.
        net_sells = sell_value - total_value
        if (
            (sell_cluster or net_sells >= 5_000_000)
            and sell_distinct >= 2
            and (si_pct or 0) >= 0.10
        ):
            # Bigger demote for the cluster pattern; smaller for raw $ size.
            insider_dump_demote = 15 if sell_cluster else 8

    # Float-aware multiplier — empirically validated by the historical-squeeze
    # backtest: every name we missed in the partial replay (KOSS, SPRT, HKD,
    # MMAT, IRNT) had a float under ~10M. Same SI% on a 5M-float name is
    # structurally a much bigger squeeze than on a 500M-float name because each
    # forced buy moves the price more. Tier:
    #   <5M float    -> 1.40x   (sub-microcap, extreme squeeze fuel)
    #   <20M float   -> 1.20x   (microcap)
    #   <50M float   -> 1.10x   (small)
    #   <200M float  -> 1.00x   (normal)
    #   >=200M float -> 1.00x   (large, no boost)
    # Only applies when there's a real SI signal to amplify (avoids inflating
    # randomly-thin floats that aren't being shorted).
    # Institutional 13D/13G — a fresh activist 5%+ stake on a heavily-shorted
    # name puts shorts on the clock. Reddit-corpus pattern: Pentwater 13D on
    # AVIS preceded the squeeze by 27 days. 13D (active) is materially
    # stronger than 13G (passive); we weight accordingly. Recency-decay so a
    # 90-day-old filing carries less weight than a 7-day-old one.
    inst_component = 0.0
    inst_info: dict = {}
    if inst_holders:
        n_active = inst_holders.get("n_active") or 0
        n_passive = inst_holders.get("n_passive") or 0
        days_since = inst_holders.get("days_since_most_recent")
        inst_info = {
            "inst_active_filings": n_active,
            "inst_passive_filings": n_passive,
            "inst_most_recent": inst_holders.get("most_recent"),
            "inst_days_since": days_since,
        }
        if n_active or n_passive:
            base = 8.0 * min(n_active, 2) + 3.0 * min(n_passive, 2)  # max 22
            recency_mult = 1.0
            if days_since is not None:
                # 0-7d: 1.0x, 8-30d: 0.7x, 31-60d: 0.4x, 61-90d: 0.2x
                if days_since <= 7:
                    recency_mult = 1.0
                elif days_since <= 30:
                    recency_mult = 0.7
                elif days_since <= 60:
                    recency_mult = 0.4
                else:
                    recency_mult = 0.2
            inst_component = min(15.0, base * recency_mult)

    raw_si_score = (
        pct_component + dtc_component + finra_component + insider_component + inst_component
    )
    float_shares = fund.get("float_shares") or 0
    float_mult = 1.0
    if float_shares > 0 and raw_si_score >= 30:
        if float_shares < 5_000_000:
            float_mult = 1.40
        elif float_shares < 20_000_000:
            float_mult = 1.20
        elif float_shares < 50_000_000:
            float_mult = 1.10
    score = _clip(raw_si_score * float_mult - insider_dump_demote)

    stale = False
    si_age_days: int | None = None
    if si_date:
        try:
            dt = datetime.fromtimestamp(si_date, tz=UTC) if isinstance(si_date, (int, float)) else None
            if dt:
                si_age_days = (datetime.now(UTC) - dt).days
                if si_age_days > 20:
                    stale = True
                    if not finra_info:
                        score = min(score, 50)
                # Hard zero past 30d with no FINRA backstop: the structural number
                # is too old to act on and we have no daily-volume signal to
                # corroborate. Better to drop the factor than mislead the rank.
                if si_age_days > 30 and not finra_info:
                    score = 0.0
        except Exception:
            pass

    flag = None
    if si_pct and si_pct >= 0.20 and dtc and dtc >= 5:
        flag = "squeeze_setup"
    elif si_pct and si_pct >= 0.30:
        flag = "extreme_si"
    if finra_info and finra_info.get("finra_latest_short_ratio", 0) >= 0.50 and finra_info.get("finra_trend") == "rising":
        flag = "shorts_piling_in"
    # Insider cluster buying on a high-SI name is the strongest standalone
    # signal here — promote the flag.
    if insider_info.get("insider_cluster") and si_pct and si_pct >= 0.15:
        flag = "insider_cluster_buying"
    elif (insider_info.get("insider_buy_value_usd") or 0) >= 1_000_000 and si_pct and si_pct >= 0.15:
        flag = "insider_buying"
    # Activist 13D filing recently + meaningful SI = institutional-scale
    # version of insider buying. Promote over generic flags; the Reddit
    # corpus highlighted this as the highest-conviction setup.
    if (
        (inst_info.get("inst_active_filings") or 0) >= 1
        and (inst_info.get("inst_days_since") or 999) <= 30
        and si_pct and si_pct >= 0.10
    ):
        flag = "activist_filed"
    # Insider dumping overrides everything bullish — Reddit-corpus signal
    # that the squeeze window is closing.
    if insider_dump_demote >= 8:
        flag = "insiders_dumping"
    # Tiny float on a real SI signal — the textbook small-float squeeze setup.
    # Promote over the structural-only flags since float dominates squeeze
    # mechanics on this scale.
    if float_mult >= 1.20 and (
        (si_pct and si_pct >= 0.15)
        or (finra_info.get("finra_latest_short_ratio", 0) >= 0.40)
    ):
        flag = "tiny_float_squeeze"
    if si_age_days is not None and si_age_days > 30 and not finra_info:
        flag = "si_stale"
    elif stale and not finra_info:
        flag = f"{flag or ''}_STALE".lstrip("_")

    from src.score.sectors import sector_reference as _sref_final
    _s_med, _s_p75, _s_p90 = _sref_final(sector)
    return score, {
        "si_pct": si_pct,
        "dtc": dtc,
        "si_as_of_epoch": si_date,
        "stale_yf": stale,
        "float_shares": float_shares,
        "float_mult": round(float_mult, 2),
        "sector": sector,
        "sector_si_median": _s_med,
        "sector_si_p90": _s_p90,
        **finra_info,
        **insider_info,
        **inst_info,
        "flag": flag,
    }


def score_ta(prices: dict | None) -> tuple[float, dict]:
    if not prices or not prices.get("bars"):
        return 0.0, {"reason": "no_data"}

    bars = prices["bars"]
    if len(bars) < 60:
        return 0.0, {"reason": "insufficient_history"}

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    volumes = [b["volume"] for b in bars]

    last_close = closes[-1]
    prior_close = closes[-2]
    prior_high_60 = max(highs[-61:-1])
    # Require close above the prior 60d high AND a green day. Filters out
    # intraday wicks that round-trip below the breakout level.
    breakout = 1 if (last_close > prior_high_60 and last_close > prior_close) else 0

    vol_20_avg = sum(volumes[-21:-1]) / 20
    rvol = volumes[-1] / vol_20_avg if vol_20_avg > 0 else 0

    # RSI14
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-14:]]
    losses = [-d if d < 0 else 0 for d in deltas[-14:]]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - (100 / (1 + rs))

    breakout_score = 40 * breakout
    if breakout and rvol < 1.5:
        breakout_score /= 2

    rvol_score = 30 * min(rvol / 3, 1)

    if rsi > 80:
        rsi_score = 0
    else:
        rsi_score = 30 * max(0, (rsi - 50) / 20)

    score = _clip(breakout_score + rvol_score + rsi_score)

    flag = None
    if breakout and rvol >= 2:
        flag = "breakout_highvol"
    elif breakout:
        flag = "breakout_lowvol"
    elif rsi > 80:
        flag = "overextended"
    elif rvol >= 3:
        flag = "volume_spike"

    return score, {
        "last_close": last_close,
        "prior_high_60": prior_high_60,
        "breakout": bool(breakout),
        "rvol": round(rvol, 2),
        "rsi14": round(rsi, 1),
        "flag": flag,
    }


def score_catalyst(cat: dict | None) -> tuple[float, dict]:
    if not cat:
        return 0.0, {"reason": "no_data"}

    dte = cat.get("days_to_event")
    if dte is None:
        return 0.0, {"reason": "no_event"}

    next_event = cat.get("next_event") or {}
    kind = (next_event.get("kind") or "earnings").lower()

    # Event-type-aware scoring. Linear decay was too generic — a binary FDA
    # PDUFA date doesn't lose value the same way a quarterly print does.
    if kind in ("fda_pdufa", "fda"):
        # Binary event (drug approval / rejection). Full score plateau
        # within 30 days; the squeeze potential is the same whether it's
        # in 5 or 25 days because the outcome is the actual catalyst.
        score = 100.0 if dte <= 30 else 0.0
    elif kind in ("m&a", "ma", "merger", "acquisition"):
        # Pending merger/acquisition — strong baseline at any reasonable DTE
        # because shorts are typically squeezed by the announcement premium.
        score = 90.0 if dte <= 60 else 50.0 if dte <= 120 else 0.0
    elif kind in ("regulatory", "ruling"):
        score = max(0.0, 80.0 - dte * 2.0)
    else:
        # Earnings (default). Linear decay 0-30d, with two refinements:
        #  - small boost (×1.1) for very-near events (≤3d) where gamma
        #    chase accelerates into the print
        #  - small boost (+5) for AMC (after-market-close) earnings since
        #    the overnight gap is typically wider than BMO
        score = 100.0 * max(0.0, 1.0 - dte / 30.0)
        if dte <= 3 and score > 0:
            score *= 1.1
        if next_event.get("hour", "").lower() == "amc":
            score = min(100.0, score + 5.0)

    flag = None
    if dte <= 7:
        flag = f"{kind}_imminent" if kind != "earnings" else "imminent"
    elif dte <= 14:
        flag = f"{kind}_near" if kind != "earnings" else "near"

    return _clip(score), {
        "next_event": next_event,
        "days_to_event": dte,
        "kind": kind,
        "flag": flag,
    }


def compute_all(bundle: dict[str, Any]) -> dict[str, Any]:
    """
    bundle = {stocktwits, options, fundamentals, prices, catalysts}
    Returns factor scores and signal dicts.
    """
    s_sent, sig_sent = score_sentiment(bundle.get("stocktwits"), bundle.get("apewisdom"))
    s_opt, sig_opt = score_options(bundle.get("options"), bundle.get("prices"))
    s_si, sig_si = score_si(
        bundle.get("fundamentals"),
        bundle.get("finra"),
        bundle.get("insiders"),
        bundle.get("inst_holders"),
    )
    s_ta, sig_ta = score_ta(bundle.get("prices"))
    s_cat, sig_cat = score_catalyst(bundle.get("catalysts"))

    return {
        "sentiment": {"score": round(s_sent, 1), "signals": sig_sent},
        "options": {"score": round(s_opt, 1), "signals": sig_opt},
        "si": {"score": round(s_si, 1), "signals": sig_si},
        "ta": {"score": round(s_ta, 1), "signals": sig_ta},
        "catalyst": {"score": round(s_cat, 1), "signals": sig_cat},
    }
