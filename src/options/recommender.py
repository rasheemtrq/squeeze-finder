"""
Squeeze-play options recommender.

Ranks long-call contracts for an asymmetric squeeze bet:
- 14–45 DTE sweet spot (avoid 0DTE chaos and >60d theta drag)
- Delta 0.20–0.45 for asymmetry (cheap exposure with meaningful participation)
- Slightly OTM preferred (strike within +0–25% of spot)
- Liquidity filter: OI ≥ 50, bid+ask > 0, spread ≤ 25% of mid
- Near gamma concentration strike gets a bonus

Pricing: mid = (bid + ask) / 2 when both > 0, else lastPrice.
Greeks: computed via Black-Scholes from the chain's impliedVolatility.
"""
from __future__ import annotations

import concurrent.futures
import math
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from src.config import CACHE_TTL
from src.data import _cache
from src.data.fundamentals import fetch as fundamentals_fetch
from src.data.prices import DataUnavailable
from src.options.greeks import bs_call

DTE_MIN = 14
DTE_MAX = 45
STRIKE_OTM_MAX = 0.25
MIN_OI = 50
MIN_VOLUME_FALLBACK = 200  # used as liquidity proxy when chain is stale (pre/post market)
MAX_SPREAD_PCT = 0.25
RISK_FREE_RATE = 0.045
IV_STALE_THRESHOLD = 0.05  # below this, IV is yfinance garbage from zero quotes
IV_FALLBACK = 0.6  # typical for squeeze candidates; used only when IV looks broken


def _dte(expiry_ymd: str) -> int:
    exp = datetime.strptime(expiry_ymd, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (exp - datetime.now(timezone.utc)).days


def _score(contract: dict) -> float:
    dte = contract["dte"]
    delta = contract.get("delta")
    oi = contract["open_interest"] or 0
    volume = contract["volume"] or 0
    mid = contract["mid"]
    spread_pct = contract["spread_pct"]
    gamma_bonus = contract.get("near_max_gamma", False)

    if delta is None or mid <= 0:
        return 0.0

    # DTE sweet spot — peak at 28
    dte_score = max(0, 30 - abs(dte - 28) * 0.75) if DTE_MIN <= dte <= DTE_MAX else 0

    # Delta target 0.30 — asymmetric yet meaningful
    delta_score = max(0, 25 - abs(delta - 0.32) * 100)

    # Liquidity from OI
    liq_score = min(20, 5 + math.log10(max(oi, 1) / 50) * 8) if oi >= MIN_OI else 0

    # Spread tightness
    spread_score = 20 * max(0, 1 - spread_pct / MAX_SPREAD_PCT) if spread_pct is not None else 0

    # Volume as secondary liquidity signal
    vol_score = min(10, math.log10(max(volume, 1) + 1) * 3)

    total = dte_score + delta_score + liq_score + spread_score + vol_score
    if gamma_bonus:
        total += 8

    return round(total, 1)


def _rationale(contract: dict, spot: float) -> str:
    parts = []
    pct_otm = (contract["strike"] / spot - 1) * 100
    if pct_otm < 0:
        parts.append(f"{abs(pct_otm):.0f}% ITM")
    elif pct_otm < 3:
        parts.append("ATM")
    else:
        parts.append(f"{pct_otm:.0f}% OTM")

    parts.append(f"{contract['dte']}d")

    d = contract.get("delta")
    if d is not None:
        parts.append(f"Δ{d:.2f}")

    if contract.get("near_max_gamma"):
        parts.append("gamma-anchor")

    if contract["open_interest"] >= 1000:
        parts.append(f"OI {contract['open_interest']:,}")

    return " · ".join(parts)


def recommend(ticker: str, top_n: int = 8, force_refresh: bool = False) -> dict[str, Any]:
    cache_key = f"{ticker}_{top_n}"
    if not force_refresh:
        cached = _cache.get("options_rec", cache_key, CACHE_TTL["options"])
        if cached:
            return cached

    tk = yf.Ticker(ticker)
    try:
        expiries = tk.options
    except Exception as e:
        raise DataUnavailable(f"options list failed for {ticker}: {e}") from e
    if not expiries:
        raise DataUnavailable(f"no options for {ticker}")

    try:
        hist = tk.history(period="1d")
        spot = float(hist["Close"].iloc[-1])
    except Exception as e:
        raise DataUnavailable(f"spot fetch failed for {ticker}: {e}") from e

    try:
        fund = fundamentals_fetch(ticker)
        q = (fund.get("dividendYield") or 0) / 100.0
    except Exception:
        q = 0.0

    # Identify max-gamma strike on nearest expiry for the anchor bonus
    max_gamma_strike = None
    try:
        chain0 = tk.option_chain(expiries[0])
        near_mask = (chain0.calls["strike"] >= spot * 0.95) & (chain0.calls["strike"] <= spot * 1.20)
        if near_mask.any():
            calls0 = chain0.calls[near_mask].copy()
            if len(calls0):
                max_gamma_strike = float(calls0.loc[calls0["openInterest"].idxmax(), "strike"])
    except Exception:
        pass

    candidates: list[dict] = []
    expiries_in_range = [e for e in expiries if DTE_MIN <= _dte(e) <= DTE_MAX]
    expiries_scanned: list[str] = list(expiries_in_range)
    any_chain_stale = False

    def _fetch_chain(exp: str):
        try:
            return exp, tk.option_chain(exp)
        except Exception:
            return exp, None

    chains: dict[str, Any] = {}
    if expiries_in_range:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(expiries_in_range), 5)
        ) as pool:
            for exp, chain in pool.map(_fetch_chain, expiries_in_range):
                chains[exp] = chain

    for exp in expiries_in_range:
        chain = chains.get(exp)
        if chain is None:
            continue
        dte = _dte(exp)
        calls = chain.calls
        if calls is None or calls.empty:
            continue

        # Filter to relevant strike range
        mask = (calls["strike"] >= spot * 0.98) & (calls["strike"] <= spot * (1 + STRIKE_OTM_MAX))
        calls = calls.loc[mask].copy()
        if calls.empty:
            continue

        # Coerce NaN to 0 at the boundary — yfinance returns NaN for illiquid
        # strikes, and `NaN or 0` is NaN in Python (NaN is truthy), which
        # then crashes int(NaN).
        for col in ("bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility"):
            if col in calls.columns:
                calls[col] = calls[col].fillna(0)

        # Detect stale chain: all bid+ask zero = market closed / pre-market.
        # In this state, OI is also typically 0 from yfinance, IV is garbage,
        # but lastPrice + volume reflect last trading session and are usable.
        chain_stale = bool(((calls["bid"] == 0) & (calls["ask"] == 0)).all())
        if chain_stale:
            any_chain_stale = True

        T = max(dte, 0.5) / 365.0

        for _, row in calls.iterrows():
            strike = float(row["strike"])
            bid = float(row["bid"])
            ask = float(row["ask"])
            last = float(row["lastPrice"])
            volume = int(row["volume"])
            oi = int(row["openInterest"])
            iv = float(row["impliedVolatility"])

            # Liquidity gate: prefer OI, but fall back to volume when chain is stale
            if oi < MIN_OI:
                if not (chain_stale and volume >= MIN_VOLUME_FALLBACK):
                    continue

            # Pricing: prefer mid, fall back to last when bid/ask zero
            if bid > 0 and ask > 0 and ask >= bid:
                mid = (bid + ask) / 2
                spread_pct = (ask - bid) / mid if mid > 0 else None
            elif last > 0:
                mid = last
                spread_pct = None  # spread unknown when stale
            else:
                continue

            if mid <= 0.05 or (spread_pct is not None and spread_pct > MAX_SPREAD_PCT):
                continue

            # Greeks: when IV is garbage from zero-quote chain, use a sensible
            # fallback so the greeks aren't wildly wrong. Flag the contract.
            iv_is_stale = iv < IV_STALE_THRESHOLD
            iv_for_greeks = IV_FALLBACK if iv_is_stale else iv
            greeks = bs_call(S=spot, K=strike, T=T, r=RISK_FREE_RATE, sigma=iv_for_greeks, q=q)
            delta = greeks["delta"] if greeks else None
            gamma = greeks["gamma"] if greeks else None
            theta = greeks["theta"] if greeks else None

            if delta is None or delta < 0.10 or delta > 0.60:
                continue

            near_max_gamma = (
                max_gamma_strike is not None
                and abs(strike - max_gamma_strike) / max(spot, 1) < 0.03
            )

            contract = {
                "ticker": ticker,
                "expiry": exp,
                "dte": dte,
                "strike": strike,
                "bid": bid,
                "ask": ask,
                "last": last,
                "mid": round(mid, 2),
                "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
                "volume": volume,
                "open_interest": oi,
                "iv": round(iv, 3),
                "iv_stale": iv_is_stale,
                "delta": round(delta, 3),
                "gamma": round(gamma, 4) if gamma else None,
                "theta": round(theta, 3) if theta else None,
                "breakeven": round(strike + mid, 2),
                "breakeven_pct_from_spot": round((strike + mid) / spot - 1, 3),
                "cost_per_contract": round(mid * 100, 2),
                "pct_otm": round(strike / spot - 1, 3),
                "near_max_gamma": near_max_gamma,
                "chain_stale": chain_stale,
            }
            contract["score"] = _score(contract)
            contract["rationale"] = _rationale(contract, spot)
            candidates.append(contract)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    top = candidates[:top_n]

    result = {
        "ticker": ticker,
        "spot": round(spot, 2),
        "as_of": datetime.now(timezone.utc).isoformat(),
        "risk_free_rate": RISK_FREE_RATE,
        "max_gamma_strike": max_gamma_strike,
        "expiries_scanned": expiries_scanned,
        "candidates_total": len(candidates),
        "recommendations": top,
        "stale_quotes": any_chain_stale,
        "filters": {
            "dte_min": DTE_MIN,
            "dte_max": DTE_MAX,
            "strike_otm_max": STRIKE_OTM_MAX,
            "min_open_interest": MIN_OI,
            "max_spread_pct": MAX_SPREAD_PCT,
            "delta_min": 0.10,
            "delta_max": 0.60,
        },
    }
    _cache.put("options_rec", cache_key, result)
    return result
