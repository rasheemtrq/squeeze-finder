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
    atm_call_iv: float | None = None
    atm_put_iv: float | None = None

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

            # Detect stale chain (pre/post-market): yfinance returns bid=ask=0
            # on every strike AND a constant sentinel IV (~6%). If we extract
            # ATM IV from this, skew always reads 1.0 and IV/HV always reads
            # tiny — both meaningless. Skip IV extraction entirely.
            calls_bidask_zero = ((calls["bid"].fillna(0) + calls["ask"].fillna(0)) == 0).all()
            puts_bidask_zero = ((puts["bid"].fillna(0) + puts["ask"].fillna(0)) == 0).all()
            if calls_bidask_zero and puts_bidask_zero:
                continue

            # ATM IV per side — strike closest to spot among strikes that are
            # quoting (bid+ask > 0), within ±10% of spot, and IV in a
            # plausible range. Pre-market chains often surface only a few
            # far-OTM strikes with $0.01 quotes that produce 1800% IVs;
            # the spot-proximity gate filters those out.
            for side_df, side_name in ((calls, "call"), (puts, "put")):
                if side_df is None or side_df.empty:
                    continue
                quoting = (side_df["bid"].fillna(0) + side_df["ask"].fillna(0)) > 0
                near = (side_df["strike"] >= spot * 0.90) & (side_df["strike"] <= spot * 1.10)
                iv_real = (side_df["impliedVolatility"].fillna(0) >= 0.05) & (
                    side_df["impliedVolatility"].fillna(0) <= 5.0
                )
                liq = side_df.loc[quoting & near & iv_real].copy()
                if liq.empty:
                    continue
                liq["abs_dist"] = (liq["strike"] - spot).abs()
                row = liq.loc[liq["abs_dist"].idxmin()]
                iv = float(row["impliedVolatility"])
                if side_name == "call":
                    atm_call_iv = iv
                else:
                    atm_put_iv = iv

    exp_dt = datetime.strptime(nearest_expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    days_to_expiry = (exp_dt - datetime.now(timezone.utc)).days

    cpr = (call_vol_total / put_vol_total) if put_vol_total > 0 else 0
    gamma_conc = (near_atm_call_oi / total_oi) if total_oi > 0 else 0

    iv_skew_ratio: float | None = None
    if atm_call_iv and atm_put_iv:
        iv_skew_ratio = atm_call_iv / atm_put_iv
    atm_iv_avg: float | None = None
    if atm_call_iv and atm_put_iv:
        atm_iv_avg = (atm_call_iv + atm_put_iv) / 2
    elif atm_call_iv:
        atm_iv_avg = atm_call_iv
    elif atm_put_iv:
        atm_iv_avg = atm_put_iv

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
        "atm_call_iv": round(atm_call_iv, 4) if atm_call_iv else None,
        "atm_put_iv": round(atm_put_iv, 4) if atm_put_iv else None,
        "iv_skew_ratio": round(iv_skew_ratio, 3) if iv_skew_ratio else None,
        "atm_iv_avg": round(atm_iv_avg, 4) if atm_iv_avg else None,
        "num_expiries_sampled": min(max_expiries, len(expiries)),
    }
    _cache.put("options", ticker, result)
    return result
