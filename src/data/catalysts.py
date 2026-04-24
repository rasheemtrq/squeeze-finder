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

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "next_event": next_event,
        "days_to_event": days_to_event,
    }
    _cache.put("catalysts", ticker, result)
    return result
