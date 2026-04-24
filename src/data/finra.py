"""
FINRA daily short-sale volume — the consolidated NMS file (CNMS).
Distinct from short interest (bi-monthly). This is a *daily momentum* signal:
what % of each day's volume was sold short on FINRA ATS + OTC venues.

File format (pipe-delimited):
  Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import CACHE_DIR, CACHE_TTL
from src.data import _cache
from src.data.prices import DataUnavailable

FINRA_CNMS_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
RAW_DIR = CACHE_DIR / "finra_raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _download_day(d: date) -> str | None:
    s = d.strftime("%Y%m%d")
    p = RAW_DIR / f"CNMSshvol{s}.txt"
    if p.exists() and p.stat().st_size > 1000:
        return p.read_text()
    r = httpx.get(FINRA_CNMS_URL.format(date=s), timeout=20)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    p.write_text(r.text)
    return r.text


def _parse_day_for_ticker(text: str, ticker: str) -> dict | None:
    """Scan the pipe-delimited file for a single ticker line."""
    needle = f"|{ticker}|"
    for line in text.splitlines():
        if needle in line:
            parts = line.split("|")
            if len(parts) >= 5:
                try:
                    return {
                        "date": parts[0],
                        "short_volume": float(parts[2]),
                        "short_exempt_volume": float(parts[3]) if parts[3] else 0,
                        "total_volume": float(parts[4]),
                    }
                except ValueError:
                    return None
    return None


def fetch(ticker: str, lookback_days: int = 7, force_refresh: bool = False) -> dict:
    """
    Returns per-ticker short-volume series for trailing N trading days.
    Skips weekends/holidays by trying successive days and tolerating 404s.
    Per-ticker result is cached separately from the raw daily files so
    re-parsing 3MB of pipe-delimited CSV doesn't happen on every call.
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_{lookback_days}"

    if not force_refresh:
        cached = _cache.get("finra", cache_key, CACHE_TTL["finra"])
        if cached:
            return cached

    today = date.today()
    series: list[dict] = []
    tried = 0
    max_tries = lookback_days * 2  # buffer for weekends/holidays

    d = today - timedelta(days=1)
    while tried < max_tries and len(series) < lookback_days:
        tried += 1
        try:
            text = _download_day(d)
        except Exception:
            text = None
        if text:
            row = _parse_day_for_ticker(text, ticker)
            if row and row["total_volume"] > 0:
                row["short_ratio"] = round(row["short_volume"] / row["total_volume"], 4)
                series.append(row)
        d = d - timedelta(days=1)

    if not series:
        raise DataUnavailable(f"no FINRA daily data for {ticker} in trailing {lookback_days} days")

    ratios = [r["short_ratio"] for r in series]
    avg_ratio = sum(ratios) / len(ratios)
    latest_ratio = ratios[0]
    trend = None
    if len(ratios) >= 3:
        recent3 = sum(ratios[:3]) / 3
        prior = sum(ratios[3:]) / max(1, len(ratios) - 3)
        if prior > 0:
            delta = (recent3 - prior) / prior
            if delta > 0.10:
                trend = "rising"
            elif delta < -0.10:
                trend = "falling"
            else:
                trend = "flat"

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "days_available": len(series),
        "latest_date": series[0]["date"],
        "latest_short_ratio": latest_ratio,
        "avg_short_ratio": round(avg_ratio, 4),
        "trend": trend,
        "series": series,
    }
    _cache.put("finra", cache_key, result)
    return result
