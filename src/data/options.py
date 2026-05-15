from __future__ import annotations

from datetime import UTC, datetime

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

    # Use minute bars during RTH so spot tracks live quotes; daily-bar Close
    # can lag intraday, producing ITM strikes with mid<intrinsic in the
    # downstream chain summary.
    try:
        intraday = tk.history(period="1d", interval="1m")
        if intraday.empty:
            intraday = tk.history(period="2d", interval="1m")
        spot = float(intraday["Close"].iloc[-1]) if not intraday.empty else float(tk.history(period="1d")["Close"].iloc[-1])
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
    unusual_call_strikes: list[dict] = []
    unusual_put_strikes: list[dict] = []
    # strike-level data for the squeeze-pressure model: near-money calls
    # (spot..spot+15%) within 21 DTE. Collected once here so pressure.py
    # doesn't need a second yfinance call per ticker.
    gamma_strikes: list[dict] = []

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

        exp_dt_now = datetime.strptime(exp, "%Y-%m-%d").replace(tzinfo=UTC)
        exp_dte = (exp_dt_now - datetime.now(UTC)).days
        if exp_dte <= 21:
            pressure_mask = (calls["strike"] >= spot) & (calls["strike"] <= spot * 1.15)
            sub = calls.loc[pressure_mask].copy()
            if not sub.empty:
                sub["openInterest"] = sub["openInterest"].fillna(0)
                sub["impliedVolatility"] = sub["impliedVolatility"].fillna(0)
                for _, prow in sub.iterrows():
                    p_oi = int(prow["openInterest"])
                    if p_oi <= 0:
                        continue
                    gamma_strikes.append({
                        "expiry": exp,
                        "dte": exp_dte,
                        "strike": float(prow["strike"]),
                        "oi": p_oi,
                        "iv": float(prow["impliedVolatility"]),
                    })

        if exp == nearest_expiry:
            near_mask = (calls["strike"] >= spot * 0.95) & (calls["strike"] <= spot * 1.10)
            near_atm_call_oi = int(calls.loc[near_mask, "openInterest"].fillna(0).sum())
            total_oi = int(calls["openInterest"].fillna(0).sum() + puts["openInterest"].fillna(0).sum())

            # Unusual volume per strike — "smart-money flow" signature.
            # A strike where today's volume >= 2x prior OI AND >= 500 contracts
            # is a strong tell that someone is opening (not closing) a
            # meaningful position. Restrict to strikes within ±25% of spot —
            # far-OTM lottery tickets with vol/OI > 2 happen all day on
            # liquid names and aren't informative.
            for side_df, bucket in ((calls, unusual_call_strikes), (puts, unusual_put_strikes)):
                if side_df is None or side_df.empty:
                    continue
                v = side_df["volume"].fillna(0)
                oi = side_df["openInterest"].fillna(0)
                strike = side_df["strike"]
                price = side_df["lastPrice"].fillna(0)
                near_money = (strike >= spot * 0.75) & (strike <= spot * 1.25)
                unusual = (v >= 500) & (v >= 2 * oi.clip(lower=1)) & near_money
                for _, row in side_df.loc[unusual].iterrows():
                    bucket.append({
                        "strike": float(row["strike"]),
                        "volume": int(row["volume"] or 0),
                        "open_interest": int(row["openInterest"] or 0),
                        "last_price": float(row["lastPrice"] or 0),
                        "premium_usd": round(float(row["volume"] or 0) * float(price.loc[row.name]) * 100, 2),
                        "vol_oi_ratio": round(float(row["volume"] or 0) / max(float(row["openInterest"] or 1), 1), 2),
                    })

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

    exp_dt = datetime.strptime(nearest_expiry, "%Y-%m-%d").replace(tzinfo=UTC)
    days_to_expiry = (exp_dt - datetime.now(UTC)).days

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

    unusual_call_strikes.sort(key=lambda c: c["premium_usd"], reverse=True)
    unusual_put_strikes.sort(key=lambda c: c["premium_usd"], reverse=True)
    unusual_call_premium = round(sum(c["premium_usd"] for c in unusual_call_strikes), 2)
    unusual_put_premium = round(sum(c["premium_usd"] for c in unusual_put_strikes), 2)

    result = {
        "ticker": ticker,
        "as_of": datetime.now(UTC).isoformat(),
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
        "unusual_call_strikes_n": len(unusual_call_strikes),
        "unusual_put_strikes_n": len(unusual_put_strikes),
        "unusual_call_premium_usd": unusual_call_premium,
        "unusual_put_premium_usd": unusual_put_premium,
        "unusual_call_top": unusual_call_strikes[:5],
        "unusual_put_top": unusual_put_strikes[:5],
        "num_expiries_sampled": min(max_expiries, len(expiries)),
        "gamma_strikes": gamma_strikes,
    }
    _cache.put("options", ticker, result)
    return result
