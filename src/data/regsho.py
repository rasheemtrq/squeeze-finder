"""
Reg SHO threshold-list fetcher.

A security appears on the Reg SHO threshold list only after **5 consecutive
settlement days** of:
  - aggregate fails-to-deliver ≥ 10,000 shares AND
  - FTD ≥ 0.5% of shares outstanding.
Continued residence triggers mandatory close-out under Rule 204 — this is
*mechanical forced-cover pressure* that the broader market may not have
priced yet. GAO-09-483 documents the correlation between threshold-list
residency and subsequent price dislocations.

Source: Nasdaq Reg SHO daily threshold-list files at
  https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{YYYYMMDD}.txt
Pipe-delimited: Symbol|Security Name|Market Category|Reg SHO Flag|Rule 3210|Filler

Coverage: Nasdaq-listed securities only. NYSE/Cboe publish their own lists
without straightforward CSV endpoints (NYSE redirects to a UI flow);
defer that to a future iteration. Most squeeze-relevant small-caps in our
universe are Nasdaq-listed anyway.

We cache each daily file once on disk (TTL = 1 day), then per-ticker we
walk backward through the last `WINDOW_DAYS` of files to compute
`consecutive_days` ending at the most recent file we have.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import CACHE_DIR, CACHE_TTL
from src.data import _cache
from src.data.prices import DataUnavailable

URL = "https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{date}.txt"
RAW_DIR = CACHE_DIR / "regsho_raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_DAYS = 30  # look back at most this many calendar days


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _download_day(d: date) -> str | None:
    """Return the file contents for a date, or None on 404 (weekend/holiday)."""
    s = d.strftime("%Y%m%d")
    p = RAW_DIR / f"nasdaqth{s}.txt"
    if p.exists() and p.stat().st_size > 200:
        return p.read_text()
    r = httpx.get(URL.format(date=s), timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    p.write_text(r.text)
    return r.text


def _parse_tickers(text: str) -> set[str]:
    """Return the set of symbols present in the file.
    Skips header + the trailing timestamp footer line Nasdaq appends.
    """
    out: set[str] = set()
    for line in text.splitlines()[1:]:  # skip header
        parts = line.split("|", 1)
        if not parts or not parts[0]:
            continue
        sym = parts[0].strip().upper()
        # Nasdaq appends a 14-digit timestamp footer like "20260520230005"
        if not sym or sym.isdigit() or len(sym) > 8:
            continue
        out.add(sym)
    return out


def fetch(ticker: str, force_refresh: bool = False) -> dict:
    """
    Returns:
      on_threshold_list: bool      — present on the latest available file
      consecutive_days: int        — unbroken streak ending at most-recent file
      latest_date: str             — date of the most recent file we found
      days_scanned: int            — how many trading days we checked
    """
    ticker = ticker.upper()
    cache_key = ticker
    if not force_refresh:
        cached = _cache.get("regsho", cache_key, CACHE_TTL.get("earnings", 21600))
        if cached:
            return cached

    today = date.today()
    # Walk back collecting daily files. Stop after WINDOW_DAYS calendar days
    # or after we have 20 trading-day files (whichever first).
    daily_sets: list[tuple[str, set[str]]] = []
    d = today
    tried = 0
    while tried < WINDOW_DAYS and len(daily_sets) < 22:
        tried += 1
        try:
            text = _download_day(d)
        except Exception:
            text = None
        if text:
            daily_sets.append((d.strftime("%Y-%m-%d"), _parse_tickers(text)))
        d -= timedelta(days=1)

    if not daily_sets:
        raise DataUnavailable(f"no regsho files available in trailing {WINDOW_DAYS}d")

    # daily_sets[0] is most-recent; walk forward (newest → older) counting
    # consecutive presence.
    on_today = ticker in daily_sets[0][1]
    consecutive = 0
    if on_today:
        for _, tickers_on_day in daily_sets:
            if ticker in tickers_on_day:
                consecutive += 1
            else:
                break

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "on_threshold_list": on_today,
        "consecutive_days": consecutive,
        "latest_date": daily_sets[0][0],
        "days_scanned": len(daily_sets),
    }
    _cache.put("regsho", cache_key, result)
    return result
