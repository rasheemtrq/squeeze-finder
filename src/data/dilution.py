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
FRESH_8K_HOURS = 48  # 8-K Item 3.02 etc. within this window = freshest signal possible

# Forms we treat as dilution-relevant. Order matters for severity (first match wins).
DILUTION_FORMS = ("S-1", "S-1/A", "424B1", "424B2", "424B3", "424B4", "424B5", "S-3", "S-3/A")
PROSPECTUS_PREFIXES = ("424B",)
REGISTRATION_NEW = ("S-1", "S-1/A")
REGISTRATION_SHELF = ("S-3", "S-3/A", "S-3ASR")

# 8-K item codes that materially affect a squeeze thesis. 3.02 is the
# canonical at-the-market issuance trigger that kills most squeezes.
# 1.03 (bankruptcy), 4.02 (restatement), 5.07 (vote — sometimes share-
# authorization increases). We surface them so a fresh filing acts as a
# kill-the-idea signal.
DILUTIVE_8K_ITEMS = {
    "1.03": "bankruptcy",
    "3.02": "unregistered_equity_sale",  # the big one
    "3.03": "material_modification_rights",
    "4.02": "restatement",
    "5.07": "shareholder_vote",
}


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
    items_field = recent.get("items") or []
    accepted_field = recent.get("acceptanceDateTime") or []

    today = date.today()
    now = datetime.now(UTC)
    cutoff = today - timedelta(days=lookback_days)
    critical_cutoff = today - timedelta(days=CRITICAL_WINDOW_DAYS)
    fresh_cutoff = now - timedelta(hours=FRESH_8K_HOURS)

    filings: list[dict] = []
    fresh_8k_events: list[dict] = []
    has_recent_prospectus = False
    has_recent_critical = False
    has_recent_new = False
    has_recent_shelf = False
    has_fresh_8k_dilutive = False  # 3.02 or 3.03 in last 48h — kill-the-idea trigger
    has_fresh_8k_other = False     # 1.03, 4.02 — bad but different mechanism

    for i, (form, fd, accno) in enumerate(zip(forms, dates, accnos, strict=False)):
        try:
            d = date.fromisoformat(fd)
        except ValueError:
            continue
        if d > today:
            continue
        if d < cutoff:
            break  # filings are newest-first

        # 8-K item inspection (kept separate from the prospectus/shelf path).
        if form.upper() == "8-K":
            items_raw = items_field[i] if i < len(items_field) else ""
            if not items_raw:
                continue
            # SEC items field is e.g. "1.01,7.01,9.01" or sometimes "1.01\t7.01"
            tokens = [t.strip() for t in items_raw.replace("\t", ",").split(",") if t.strip()]
            matched = [(t, DILUTIVE_8K_ITEMS[t]) for t in tokens if t in DILUTIVE_8K_ITEMS]
            if not matched:
                continue
            # When was it ACCEPTED (not just filing date)? Acceptance is the
            # timestamp that matters for "filed in the last 48h."
            accepted_str = accepted_field[i] if i < len(accepted_field) else ""
            accepted_dt: datetime | None = None
            if accepted_str:
                try:
                    accepted_dt = datetime.fromisoformat(accepted_str.replace("Z", "+00:00"))
                    if accepted_dt.tzinfo is None:
                        accepted_dt = accepted_dt.replace(tzinfo=UTC)
                except ValueError:
                    accepted_dt = None
            is_fresh = accepted_dt is not None and accepted_dt >= fresh_cutoff
            event = {
                "date": fd,
                "form": "8-K",
                "kind": "8k_event",
                "accno": accno,
                "items": [t for t, _ in matched],
                "item_kinds": [k for _, k in matched],
                "accepted": accepted_str,
                "fresh": is_fresh,
            }
            filings.append(event)
            if is_fresh:
                fresh_8k_events.append(event)
                if any(t in ("3.02", "3.03") for t, _ in matched):
                    has_fresh_8k_dilutive = True
                else:
                    has_fresh_8k_other = True
            continue

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

    if has_fresh_8k_dilutive:
        severity = "critical"  # fresh 3.02 trumps everything — the thesis is dead
    elif has_recent_critical:
        severity = "critical"
    elif has_recent_prospectus or has_recent_new or has_fresh_8k_other:
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
        "fresh_8k_events": fresh_8k_events,
        "fresh_8k_dilutive": has_fresh_8k_dilutive,
    }
    _cache.put("dilution", cache_key, result)
    return result
