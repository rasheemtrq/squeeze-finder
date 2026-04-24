from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from curl_cffi import requests as curl_requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import CACHE_TTL
from src.data import _cache
from src.data.prices import DataUnavailable

URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
MAX_PAGES = 3
MAX_LOOKBACK_HOURS = 24


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _get_page(ticker: str, max_id: int | None = None) -> dict:
    params: dict[str, Any] = {}
    if max_id:
        params["max"] = max_id
    r = curl_requests.get(
        URL.format(ticker=ticker),
        params=params,
        timeout=15,
        impersonate="chrome124",
    )
    r.raise_for_status()
    return r.json()


def _classify(msg: dict) -> str | None:
    ent = (msg.get("entities") or {}).get("sentiment") or {}
    basic = (ent.get("basic") or "").lower()
    if basic == "bullish":
        return "bullish"
    if basic == "bearish":
        return "bearish"
    return None


def fetch(ticker: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = _cache.get("stocktwits", ticker, CACHE_TTL["stocktwits"])
        if cached:
            return cached

    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_LOOKBACK_HOURS)

    try:
        seen_ids: set[int] = set()
        messages: list[dict] = []
        max_id: int | None = None
        pages_done = 0

        for page in range(MAX_PAGES):
            pages_done = page + 1
            data = _get_page(ticker, max_id=max_id)
            page_msgs = data.get("messages") or []
            if not page_msgs:
                break

            oldest_ts_this_page = None
            for m in page_msgs:
                mid = m.get("id")
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                ts_str = m.get("created_at")
                if not ts_str:
                    continue
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                oldest_ts_this_page = ts if oldest_ts_this_page is None else min(oldest_ts_this_page, ts)
                if ts < cutoff:
                    continue
                messages.append({"id": mid, "ts": ts, "cls": _classify(m)})

            cursor = data.get("cursor") or {}
            has_more = cursor.get("more")
            next_max = cursor.get("max")
            if not has_more or not next_max:
                break
            if oldest_ts_this_page and oldest_ts_this_page < cutoff:
                break
            max_id = next_max

    except Exception as e:
        raise DataUnavailable(f"stocktwits fetch failed for {ticker}: {e}") from e

    n = len(messages)
    bullish = sum(1 for m in messages if m["cls"] == "bullish")
    bearish = sum(1 for m in messages if m["cls"] == "bearish")
    classified = bullish + bearish
    bull_ratio = (bullish / classified) if classified > 0 else 0.5

    pages_fetched = pages_done

    lookback_hours = 0.0
    if messages:
        newest = max(m["ts"] for m in messages)
        oldest = min(m["ts"] for m in messages)
        lookback_hours = (newest - oldest).total_seconds() / 3600

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "messages_sampled": n,
        "bullish": bullish,
        "bearish": bearish,
        "unclassified": n - classified,
        "bull_ratio": round(bull_ratio, 3),
        "lookback_hours": round(lookback_hours, 1),
        "pages_fetched": pages_fetched,
    }
    _cache.put("stocktwits", ticker, result)
    return result
