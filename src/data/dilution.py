"""
Dilution-risk detector — recent SEC filings that telegraph share issuance.

The classic squeeze killer: a name has high SI and is up-trending, then
overnight files a prospectus supplement (424B) or shelf takedown, raising
capital at-the-market. Shorts cover into the offering, the squeeze
unwinds, retail holders get diluted. Detect this BEFORE recommending the
name as a squeeze candidate.

Forms we look for in a trailing 30-day window:
  S-1     - registration statement for new common shares (most dilutive)
  S-3     - shelf registration enabling future at-the-market issuance
  424B*   - prospectus supplement, often signals an actual offering being
            priced (the "we're selling now" filing)
  S-3ASR  - automatic shelf for WKSI issuers (less indicative on its own)

Severity tiers:
  CRITICAL: 424B* in last 7d (offering is live)
  HIGH:     S-1 or 424B* in last 30d (recent issuance)
  MODERATE: S-3 in last 30d (capacity to issue exists)
  LOW:      none of the above

Free, official, immutable. Cached 24h since filings are near-real-time
but rarely change once filed.
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
LOOKBACK_DAYS = 30
CRITICAL_WINDOW_DAYS = 7

# Forms we treat as dilution-relevant. Order matters for severity (first match wins).
DILUTION_FORMS = ("S-1", "S-1/A", "424B1", "424B2", "424B3", "424B4", "424B5", "S-3", "S-3/A")
PROSPECTUS_PREFIXES = ("424B",)
REGISTRATION_NEW = ("S-1", "S-1/A")
REGISTRATION_SHELF = ("S-3", "S-3/A", "S-3ASR")


def _headers() -> dict[str, str]:
    return {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _http_get(url: str, timeout: int = 15) -> httpx.Response:
    r = httpx.get(url, headers=_headers(), timeout=timeout)
    r.raise_for_status()
    return r


def _ticker_to_cik(ticker: str) -> str | None:
    """Reuse the cached map from the insiders module if available, else fetch fresh."""
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
    """Return None if not dilution-relevant, else 'prospectus' / 'new' / 'shelf'."""
    f = form.upper()
    if any(f.startswith(p) for p in PROSPECTUS_PREFIXES):
        return "prospectus"
    if f in REGISTRATION_NEW:
        return "new_registration"
    if f in REGISTRATION_SHELF:
        return "shelf"
    return None


def fetch(ticker: str, lookback_days: int = LOOKBACK_DAYS, force_refresh: bool = False) -> dict[str, Any]:
    """Return dilution-risk summary for `ticker`. Soft-fails to LOW severity if EDGAR is down.

    Output:
      severity: "low" | "moderate" | "high" | "critical"
      filings:  [{date, form, kind, accno}, ...]  newest first
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_{lookback_days}"
    if not force_refresh:
        cached = _cache.get("dilution", cache_key, CACHE_TTL)
        if cached:
            return cached

    cik = _ticker_to_cik(ticker)
    if not cik:
        # No CIK lookup -> can't tell, assume low risk (don't penalize unknown)
        result = {
            "ticker": ticker,
            "as_of": datetime.now(UTC).isoformat(),
            "severity": "low",
            "reason": "no_cik",
            "filings": [],
        }
        _cache.put("dilution", cache_key, result)
        return result

    try:
        data = _http_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    except Exception as e:
        raise DataUnavailable(f"EDGAR submissions fetch failed for {ticker}: {e}") from e

    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accnos = recent.get("accessionNumber") or []

    today = date.today()
    cutoff = today - timedelta(days=lookback_days)
    critical_cutoff = today - timedelta(days=CRITICAL_WINDOW_DAYS)

    filings: list[dict] = []
    has_recent_prospectus = False
    has_recent_critical = False
    has_recent_new = False
    has_recent_shelf = False

    for form, fd, accno in zip(forms, dates, accnos, strict=False):
        try:
            d = date.fromisoformat(fd)
        except ValueError:
            continue
        if d > today:
            continue
        if d < cutoff:
            break  # filings are newest-first
        kind = _classify(form)
        if not kind:
            continue
        filings.append({"date": fd, "form": form, "kind": kind, "accno": accno})
        if kind == "prospectus":
            has_recent_prospectus = True
            if d >= critical_cutoff:
                has_recent_critical = True
        elif kind == "new_registration":
            has_recent_new = True
        elif kind == "shelf":
            has_recent_shelf = True

    if has_recent_critical:
        severity = "critical"
    elif has_recent_prospectus or has_recent_new:
        severity = "high"
    elif has_recent_shelf:
        severity = "moderate"
    else:
        severity = "low"

    result = {
        "ticker": ticker,
        "cik": cik,
        "as_of": datetime.now(UTC).isoformat(),
        "lookback_days": lookback_days,
        "severity": severity,
        "filings": filings[:10],
        "n_filings": len(filings),
    }
    _cache.put("dilution", cache_key, result)
    return result
