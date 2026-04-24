from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf

from src.config import CACHE_TTL
from src.data import _cache
from src.data.prices import DataUnavailable


def fetch(ticker: str, max_expiries: int = 3, force_refresh: bool = False) -> dict:
    """
    Returns options-chain summary: call/put volume, OI, gamma concentration,
    nearest expiry and days-to-expiry.
    """
    if not force_refresh:
        cached = _cache.get("options", ticker, CACHE_TTL["options"])
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
        spot = tk.history(period="1d")["Close"].iloc[-1]
    except Exception as e:
        raise DataUnavailable(f"spot fetch failed for {ticker}: {e}") from e

    call_vol_total = 0
    put_vol_total = 0
    call_oi_total = 0
    put_oi_total = 0
    near_atm_call_oi = 0
    total_oi = 0
    nearest_expiry = expiries[0]

    for exp in expiries[:max_expiries]:
        try:
            chain = tk.option_chain(exp)
        except Exception:
            continue
        calls = chain.calls
        puts = chain.puts
        call_vol_total += int(calls["volume"].fillna(0).sum())
        put_vol_total += int(puts["volume"].fillna(0).sum())
        call_oi_total += int(calls["openInterest"].fillna(0).sum())
        put_oi_total += int(puts["openInterest"].fillna(0).sum())

        if exp == nearest_expiry:
            near_mask = (calls["strike"] >= spot * 0.95) & (calls["strike"] <= spot * 1.10)
            near_atm_call_oi = int(calls.loc[near_mask, "openInterest"].fillna(0).sum())
            total_oi = int(calls["openInterest"].fillna(0).sum() + puts["openInterest"].fillna(0).sum())

    exp_dt = datetime.strptime(nearest_expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    days_to_expiry = (exp_dt - datetime.now(timezone.utc)).days

    cpr = (call_vol_total / put_vol_total) if put_vol_total > 0 else 0
    gamma_conc = (near_atm_call_oi / total_oi) if total_oi > 0 else 0

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "spot": float(spot),
        "nearest_expiry": nearest_expiry,
        "days_to_expiry": days_to_expiry,
        "call_volume": call_vol_total,
        "put_volume": put_vol_total,
        "call_oi": call_oi_total,
        "put_oi": put_oi_total,
        "call_put_ratio": round(cpr, 2),
        "near_atm_call_oi": near_atm_call_oi,
        "gamma_concentration": round(gamma_conc, 3),
        "num_expiries_sampled": min(max_expiries, len(expiries)),
    }
    _cache.put("options", ticker, result)
    return result
