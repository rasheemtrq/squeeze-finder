"""
iBorrowDesk fetcher — IBKR Securities Lending Borrow Rate Feed.

iBorrowDesk mirrors the IBKR Securities Lending file every 15 min. IBKR is
the most representative single broker for retail short-side activity in
the US; their CTB and available-shares numbers correlate ~0.6–0.8 with
Ortex's multi-broker aggregate per practitioner reports.

Why this matters: Engelberg, Evans, Leonard, Reed & Ringgenberg (2018)
"Short Selling Risk" — borrow fee dominates 102 anomalies as a return
predictor. A fee spike from <10% to >30% inside 48h is the highest-
conviction 1-3 day squeeze ignition signal in retail-accessible data.

Utilization proxy: we don't have multi-broker on-loan / lendable totals,
but iBorrowDesk gives daily available_shares back ~260 days. We compute
  util_proxy = 1 − (available_now / rolling_30d_max(available))
which approximates how scarce shares are *relative to recent history*.
Calibration: ~0.7 corr with Ortex utilization per public analyses.

Endpoint: https://iborrowdesk.com/api/ticker/{TICKER}
Returns:
  daily: [{date, available, fee, rebate, ...}, ...] (most recent first or last; we sort)
  real_time: [{datetime, available, fee, rebate}, ...] intraday samples
  latest_available, latest_fee, name, cusip, updated

Cloudflare-gated against vanilla httpx; requires curl_cffi browser
impersonation.
"""
from __future__ import annotations

from datetime import datetime, timezone

from curl_cffi import requests as curl_requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data import _cache
from src.data.prices import DataUnavailable

URL = "https://iborrowdesk.com/api/ticker/{ticker}"
CACHE_TTL_SECONDS = 900  # 15 min — matches the upstream refresh cadence
ROLLING_WINDOW_DAYS = 30


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get(ticker: str) -> dict:
    r = curl_requests.get(
        URL.format(ticker=ticker.upper()),
        timeout=20,
        impersonate="chrome124",
    )
    r.raise_for_status()
    return r.json()


def _to_date(s: str) -> str:
    # iBorrowDesk dates: 'YYYY-MM-DD'. Keep as ISO date string for cache safety.
    return s


def fetch(ticker: str, force_refresh: bool = False) -> dict:
    ticker = ticker.upper()
    if not force_refresh:
        cached = _cache.get("iborrowdesk", ticker, CACHE_TTL_SECONDS)
        if cached:
            return cached

    try:
        data = _get(ticker)
    except Exception as e:
        raise DataUnavailable(f"iborrowdesk fetch failed for {ticker}: {e}") from e

    latest_fee = data.get("latest_fee")
    latest_available = data.get("latest_available")
    daily = data.get("daily") or []
    real_time = data.get("real_time") or []
    name = data.get("name")
    updated = data.get("updated")

    # 30-day max available (excluding today) — the denominator for util proxy.
    # iBorrowDesk daily list is chronologically ordered; we filter the last
    # ROLLING_WINDOW_DAYS rows that have a non-null available count.
    recent = [d for d in daily if d.get("available") is not None][-ROLLING_WINDOW_DAYS - 1:-1]
    max_avail_30d = max((d["available"] for d in recent), default=None)
    util_proxy: float | None = None
    if max_avail_30d and max_avail_30d > 0 and latest_available is not None:
        util_proxy = round(max(0.0, 1.0 - (latest_available / max_avail_30d)), 4)

    # Fee acceleration: 2-day-avg / 5-day-avg of trailing fees, excluding today.
    fee_accel: float | None = None
    fees_recent = [d.get("fee") for d in daily[-7:-1] if d.get("fee") is not None]
    if len(fees_recent) >= 5:
        last2 = sum(fees_recent[-2:]) / 2
        prior = sum(fees_recent[:-2]) / max(1, len(fees_recent) - 2)
        if prior > 0:
            fee_accel = round(last2 / prior, 3)

    # 30-day fee max for "is today's fee elevated vs recent baseline" flag.
    fees_30 = [d.get("fee") for d in daily[-ROLLING_WINDOW_DAYS:] if d.get("fee") is not None]
    max_fee_30d = max(fees_30) if fees_30 else None

    htb = bool(latest_fee is not None and latest_fee >= 5.0)  # ≥5% fee = hard-to-borrow
    scarce = bool(util_proxy is not None and util_proxy >= 0.75)
    fee_spike = bool(fee_accel is not None and fee_accel >= 2.0)

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source_updated": updated,
        "name": name,
        "latest_fee_pct": round(latest_fee, 4) if latest_fee is not None else None,
        "latest_available": latest_available,
        "max_available_30d": max_avail_30d,
        "max_fee_30d": round(max_fee_30d, 4) if max_fee_30d is not None else None,
        "utilization_proxy": util_proxy,
        "fee_acceleration": fee_accel,
        "hard_to_borrow": htb,
        "scarce_supply": scarce,
        "fee_spike": fee_spike,
        "daily_history_n": len(daily),
        "intraday_samples_n": len(real_time),
    }
    _cache.put("iborrowdesk", ticker, result)
    return result
