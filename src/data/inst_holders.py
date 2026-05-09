"""
SEC EDGAR Schedule 13D / 13G institutional position disclosures.

Filed by anyone (institution or individual) crossing 5% ownership of a
public company. Filing deadline is 10 days from crossing, so much more
timely than 13F (quarterly + 45-day lag).

Two flavors:
  - SC 13D  : ACTIVE — filer intends to influence management. Strongest
              squeeze precondition: an activist taking 5%+ on a heavily-
              shorted name is the textbook "Pentwater/AVIS, squeeze 27d
              later" pattern from the Reddit corpus.
  - SC 13G  : PASSIVE — filer holds for investment only (no influence).
              Still meaningful as a "smart money committed capital" signal
              but materially weaker than 13D.

Forms we track (via EDGAR submissions JSON):
  SC 13D, SC 13D/A, SC 13G, SC 13G/A

Cache 24h since filings are filed-once-then-immutable and amendments
are infrequent. Free, official, no auth required.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import SEC_USER_AGENT
from src.data import _cache
from src.data.prices import DataUnavailable

CACHE_TTL = 86400  # 24h
LOOKBACK_DAYS_DEFAULT = 90
ACTIVE_FORMS = ("SC 13D", "SC 13D/A")
PASSIVE_FORMS = ("SC 13G", "SC 13G/A")
ALL_FORMS = ACTIVE_FORMS + PASSIVE_FORMS


def _headers() -> dict[str, str]:
    return {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _http_get(url: str, timeout: int = 15) -> httpx.Response:
    r = httpx.get(url, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r


def _lookup_cik(ticker: str) -> str | None:
    """Reuse the cached map from the insiders module if available."""
    cached = _cache.get("sec_tickers", "all", 7 * 86400)
    if cached:
        return cached.get(ticker.upper())
    data = _http_get("https://www.sec.gov/files/company_tickers.json").json()
    out: dict[str, str] = {}
    for entry in data.values():
        try:
            out[str(entry["ticker"]).upper()] = f"{int(entry['cik_str']):010d}"
        except (KeyError, TypeError, ValueError):
            continue
    _cache.put("sec_tickers", "all", out)
    return out.get(ticker.upper())


def _classify(form: str) -> str | None:
    f = form.upper().strip()
    if f in (s.upper() for s in ACTIVE_FORMS):
        return "active"
    if f in (s.upper() for s in PASSIVE_FORMS):
        return "passive"
    return None


def fetch(ticker: str, lookback_days: int = LOOKBACK_DAYS_DEFAULT, force_refresh: bool = False) -> dict[str, Any]:
    """Return institutional 13D/G disclosures filed against `ticker` in window.

    Output:
      n_active:   count of 13D/13D-A filings (activist signal)
      n_passive:  count of 13G/13G-A filings (passive 5%+ holders)
      most_recent: ISO date of newest filing in the window, or None
      filings:   newest-first, capped at 15
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_{lookback_days}"
    if not force_refresh:
        cached = _cache.get("inst_holders", cache_key, CACHE_TTL)
        if cached:
            return cached

    cik = _lookup_cik(ticker)
    if not cik:
        result = {
            "ticker": ticker,
            "as_of": datetime.now(UTC).isoformat(),
            "reason": "no_cik",
            "n_active": 0,
            "n_passive": 0,
            "most_recent": None,
            "filings": [],
        }
        _cache.put("inst_holders", cache_key, result)
        return result

    try:
        sub = _http_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    except Exception as e:
        raise DataUnavailable(f"EDGAR submissions fetch failed for {ticker}: {e}") from e

    recent = (sub.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accnos = recent.get("accessionNumber") or []

    today = date.today()
    cutoff = today - timedelta(days=lookback_days)

    filings: list[dict] = []
    n_active = 0
    n_passive = 0
    for form, fd, accno in zip(forms, dates, accnos, strict=False):
        try:
            d = date.fromisoformat(fd)
        except ValueError:
            continue
        if d > today:
            continue
        if d < cutoff:
            break  # newest-first
        kind = _classify(form)
        if not kind:
            continue
        filings.append({"date": fd, "form": form, "kind": kind, "accno": accno})
        if kind == "active":
            n_active += 1
        else:
            n_passive += 1

    most_recent = filings[0]["date"] if filings else None
    days_since = (today - date.fromisoformat(most_recent)).days if most_recent else None

    result = {
        "ticker": ticker,
        "cik": cik,
        "as_of": datetime.now(UTC).isoformat(),
        "lookback_days": lookback_days,
        "n_active": n_active,
        "n_passive": n_passive,
        "most_recent": most_recent,
        "days_since_most_recent": days_since,
        "filings": filings[:15],
    }
    _cache.put("inst_holders", cache_key, result)
    return result
