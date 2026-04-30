"""
0DTE option scorer — ranks same-day-expiry calls and puts by realistic 2-10x
payoff probability, using the IV implied by the chain itself as the underlying
distribution.

Method:
  1. Compute hours-until-close (T in years using a 6.5h * 252-day clock).
  2. For each contract, derive the lognormal terminal-spot distribution from
     spot and IV: ln(S_T / S_0) ~ N((-σ²/2) * T, σ² * T), risk-neutral drift = 0.
  3. Payoff at expiry = max(S_T - K, 0) for calls, max(K - S_T, 0) for puts.
  4. P(payoff ≥ k * mid) for k in {2, 5, 10}: solve for the spot threshold and
     evaluate via the lognormal CDF.
  5. Score = 1 * P(2x) + 2 * P(5x) + 3 * P(10x), so contracts with realistic
     2x odds dominate flyers with vanishing 10x odds. Also exposes each P
     individually for the UI.

Liquidity gates are stricter than the 14-45 DTE recommender — 0DTE bid/ask
quality matters more.
"""
from __future__ import annotations

import math
from typing import Any

from src.options.greeks import bs_call
from src.util.market_hours import hours_until_close, is_screener_window, now_et

# Liquidity floors — 0DTE specific
MIN_OI = 200
MIN_VOLUME = 500
MIN_MID = 0.05
MAX_SPREAD_PCT = 0.10
DELTA_LO = 0.05
DELTA_HI = 0.45

RISK_FREE_RATE = 0.045
TRADING_HOURS_PER_DAY = 6.5
TRADING_DAYS_PER_YEAR = 252
HOURS_PER_YEAR = TRADING_HOURS_PER_DAY * TRADING_DAYS_PER_YEAR

PAYOFF_MULTIPLES = (2.0, 5.0, 10.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def _prob_spot_above(S0: float, threshold: float, sigma: float, T: float) -> float:
    if threshold <= 0:
        return 1.0
    if sigma <= 0 or T <= 0 or S0 <= 0:
        return 0.0
    log_ratio = math.log(threshold / S0)
    drift = -0.5 * sigma * sigma * T
    z = (log_ratio - drift) / (sigma * math.sqrt(T))
    return 1.0 - _norm_cdf(z)


def _prob_spot_below(S0: float, threshold: float, sigma: float, T: float) -> float:
    return 1.0 - _prob_spot_above(S0, threshold, sigma, T)


def _put_delta(S: float, K: float, T: float, sigma: float, r: float = RISK_FREE_RATE) -> float | None:
    """Put delta via put-call parity: Δ_put = Δ_call - 1 (no dividend)."""
    g = bs_call(S=S, K=K, T=T, r=r, sigma=sigma)
    if not g:
        return None
    return g["delta"] - 1.0


def _score_contract(
    contract: dict[str, Any],
    spot: float,
    T_years: float,
) -> dict[str, Any] | None:
    """Return scored contract dict or None if filtered out by liquidity gates."""
    bid = contract["bid"]
    ask = contract["ask"]
    last = contract["last"]
    oi = contract["open_interest"]
    volume = contract["volume"]
    iv = contract["iv"]
    strike = contract["strike"]
    side = contract["side"]

    if oi < MIN_OI or volume < MIN_VOLUME:
        return None

    if bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid if mid > 0 else None
    elif last > 0:
        mid = last
        spread_pct = None
    else:
        return None

    if mid < MIN_MID:
        return None
    if spread_pct is not None and spread_pct > MAX_SPREAD_PCT:
        return None
    if iv < 0.05:
        return None

    if side == "call":
        greeks = bs_call(S=spot, K=strike, T=T_years, r=RISK_FREE_RATE, sigma=iv)
        if not greeks:
            return None
        delta = greeks["delta"]
    else:
        delta = _put_delta(spot, strike, T_years, iv)
        if delta is None:
            return None

    abs_delta = abs(delta)
    if abs_delta < DELTA_LO or abs_delta > DELTA_HI:
        return None

    # Payoff probabilities — for each multiplier, find the threshold spot that
    # would deliver that payoff at expiry, then ask the lognormal what the
    # probability of being past that threshold is.
    probs: dict[str, float] = {}
    for mult in PAYOFF_MULTIPLES:
        target_payoff = mult * mid
        if side == "call":
            threshold = strike + target_payoff
            p = _prob_spot_above(spot, threshold, iv, T_years)
        else:
            threshold = strike - target_payoff
            p = _prob_spot_below(spot, threshold, iv, T_years)
        probs[f"p_{int(mult)}x"] = round(p, 4)

    score = (
        1.0 * probs["p_2x"] + 2.0 * probs["p_5x"] + 3.0 * probs["p_10x"]
    )

    expected_move_dollars = spot * iv * math.sqrt(T_years)

    return {
        "ticker": contract.get("ticker"),
        "side": side,
        "strike": strike,
        "expiry": contract.get("expiry"),
        "bid": bid,
        "ask": ask,
        "mid": round(mid, 3),
        "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
        "volume": volume,
        "open_interest": oi,
        "iv": round(iv, 3),
        "delta": round(delta, 3),
        "cost_per_contract": round(mid * 100, 2),
        "breakeven": round(strike + mid if side == "call" else strike - mid, 2),
        "pct_otm": round((strike / spot - 1) if side == "call" else (1 - strike / spot), 4),
        "expected_move_dollars": round(expected_move_dollars, 2),
        "expected_move_pct": round(expected_move_dollars / spot, 4) if spot > 0 else None,
        **probs,
        "score": round(score * 100, 2),
    }


def rank(chain: dict[str, Any], top_per_side: int = 3) -> dict[str, Any]:
    """Rank a single ticker's 0DTE chain into top calls and top puts."""
    spot = chain["spot"]
    hours_left = hours_until_close()
    T_years = max(hours_left, 0.25) / HOURS_PER_YEAR

    scored: list[dict] = []
    for raw in chain["contracts"]:
        annotated = {**raw, "ticker": chain["ticker"], "expiry": chain["expiry"]}
        result = _score_contract(annotated, spot=spot, T_years=T_years)
        if result:
            scored.append(result)

    calls = sorted([c for c in scored if c["side"] == "call"], key=lambda c: c["score"], reverse=True)
    puts = sorted([c for c in scored if c["side"] == "put"], key=lambda c: c["score"], reverse=True)

    return {
        "ticker": chain["ticker"],
        "spot": spot,
        "expiry": chain["expiry"],
        "as_of": chain["as_of"],
        "chain_stale": chain.get("chain_stale", False),
        "hours_until_close": round(hours_left, 2),
        "calls": calls[:top_per_side],
        "puts": puts[:top_per_side],
        "candidates_scored": len(scored),
    }


def screen_universe(top_per_side: int = 3, force_refresh: bool = False) -> dict[str, Any]:
    """End-to-end: gate on market hours, fetch all 0DTE chains, rank each."""
    from src.data.zero_dte import ZERO_DTE_UNIVERSE, fetch_universe

    allowed, reason = is_screener_window()
    now = now_et()

    if not allowed:
        return {
            "as_of": now.isoformat(),
            "ok": False,
            "blocked_reason": reason,
            "universe": ZERO_DTE_UNIVERSE,
            "results": [],
        }

    bundle = fetch_universe(force_refresh=force_refresh)
    results: list[dict] = []
    for chain in bundle["chains"].values():
        ranked = rank(chain, top_per_side=top_per_side)
        if ranked["calls"] or ranked["puts"]:
            results.append(ranked)

    # Sort tickers by best contract score across calls+puts
    def _best(r):
        scores = [c["score"] for c in r["calls"] + r["puts"]]
        return max(scores) if scores else 0
    results.sort(key=_best, reverse=True)

    return {
        "as_of": now.isoformat(),
        "ok": True,
        "blocked_reason": None,
        "expiry": bundle["expiry"],
        "universe": ZERO_DTE_UNIVERSE,
        "errors": bundle.get("errors", {}),
        "filters": {
            "min_open_interest": MIN_OI,
            "min_volume": MIN_VOLUME,
            "min_mid": MIN_MID,
            "max_spread_pct": MAX_SPREAD_PCT,
            "abs_delta_range": [DELTA_LO, DELTA_HI],
        },
        "results": results,
    }
