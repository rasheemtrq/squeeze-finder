from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import CACHE_TTL, FINNHUB_API_KEY
from src.data import _cache
from src.data.prices import DataUnavailable


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _finnhub_earnings(ticker: str, start: date, end: date) -> dict:
    if not FINNHUB_API_KEY:
        raise DataUnavailable("FINNHUB_API_KEY not set")
    r = httpx.get(
        "https://finnhub.io/api/v1/calendar/earnings",
        params={"from": start.isoformat(), "to": end.isoformat(), "symbol": ticker, "token": FINNHUB_API_KEY},
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()


def fetch(ticker: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = _cache.get("catalysts", ticker, CACHE_TTL["earnings"])
        if cached:
            return cached

    today = date.today()
    end = today + timedelta(days=60)
    try:
        data = _finnhub_earnings(ticker, today, end)
    except Exception as e:
        raise DataUnavailable(f"catalysts fetch failed for {ticker}: {e}") from e

    earnings = data.get("earningsCalendar") or []
    next_event = None
    days_to_event = None
    if earnings:
        earnings_sorted = sorted(earnings, key=lambda x: x.get("date", "9999-99-99"))
        nxt = earnings_sorted[0]
        event_date = datetime.strptime(nxt["date"], "%Y-%m-%d").date()
        next_event = {
            "kind": "earnings",
            "date": nxt["date"],
            "eps_estimate": nxt.get("epsEstimate"),
            "revenue_estimate": nxt.get("revenueEstimate"),
            "hour": nxt.get("hour"),
        }
        days_to_event = (event_date - today).days

    # Also pull clinical catalysts from ClinicalTrials.gov (free, high-signal for biotech squeezes)
    clinical_event = _fetch_clinical_catalyst(ticker)

    # Choose the most relevant near-term catalyst (prefer non-earnings binary events when available)
    chosen_event = next_event
    chosen_kind = "earnings"
    chosen_dte = days_to_event

    if clinical_event:
        c_dte = clinical_event.get("days_to_event")
        if c_dte is not None and (chosen_dte is None or c_dte < chosen_dte):
            chosen_event = clinical_event
            chosen_kind = clinical_event.get("kind", "clinical")
            chosen_dte = c_dte

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "next_event": chosen_event,
        "days_to_event": chosen_dte,
        "kind": chosen_kind,
    }
    _cache.put("catalysts", ticker, result)
    return result


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
def _fetch_clinical_catalyst(ticker: str) -> dict | None:
    """Query ClinicalTrials.gov v2 API for upcoming or recent catalysts for this ticker."""
    # ClinicalTrials.gov public API - free, no key needed for modest use
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.term": ticker,
        "size": 5,
        "sort": "lastUpdatePostDate:desc",
        "fields": "protocolSection.identificationModule,protocolSection.statusModule,protocolSection.designModule",
    }

    try:
        r = httpx.get(url, params=params, timeout=12, headers={"User-Agent": "squeeze-finder research"})
        if r.status_code != 200:
            return None
        data = r.json()
        studies = data.get("studies", [])
        if not studies:
            return None

        today = date.today()
        best = None
        best_dte = 999

        for study in studies:
            proto = study.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            status = proto.get("statusModule", {})

            completion = status.get("primaryCompletionDate") or status.get("completionDate")
            if not completion:
                continue

            try:
                comp_date = datetime.strptime(completion.get("date", ""), "%Y-%m-%d").date()
            except Exception:
                continue

            dte = (comp_date - today).days
            if dte < -30:  # too old
                continue

            title = ident.get("briefTitle", "")
            phase = proto.get("designModule", {}).get("phases", [""])[0] if proto.get("designModule") else ""

            kind = "clinical_readout"
            if "PDUFA" in title.upper() or "fda" in title.lower():
                kind = "fda_pdufa"

            if dte < best_dte:
                best_dte = dte
                best = {
                    "kind": kind,
                    "date": completion.get("date"),
                    "title": title[:120],
                    "phase": phase,
                    "days_to_event": dte if dte >= 0 else 0,
                }

        return best
    except Exception:
        return None
