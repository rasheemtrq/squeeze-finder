from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from curl_cffi import requests as curl_requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import CACHE_DIR, CACHE_TTL
from src.data import _cache
from src.data.prices import DataUnavailable

URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
MAX_PAGES = 3
MAX_LOOKBACK_HOURS = 24
HISTORY_DIR = CACHE_DIR / "stocktwits_history"
HISTORY_RETAIN_DAYS = 14
HISTORY_BASELINE_DAYS = 7


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

    velocity, bull_baseline = _update_history(
        ticker, n_now=n, bull_now=bull_ratio
    )

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
        "msg_velocity": velocity,
        "bull_ratio_baseline": bull_baseline,
    }
    _cache.put("stocktwits", ticker, result)
    return result


def _update_history(ticker: str, n_now: int, bull_now: float) -> tuple[float | None, float | None]:
    """Append current sample to the per-ticker history log and compute velocity.

    velocity = current messages_sampled / mean of prior 7d samples; None if no
    prior history. bull_ratio_baseline is the prior 7d mean.
    Trims rows older than HISTORY_RETAIN_DAYS to keep files small.
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path: Path = HISTORY_DIR / f"{ticker.upper()}.jsonl"

    now = datetime.now(timezone.utc)
    cutoff_retain = now - timedelta(days=HISTORY_RETAIN_DAYS)
    cutoff_baseline = now - timedelta(days=HISTORY_BASELINE_DAYS)

    rows: list[dict] = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
                ts = datetime.fromisoformat(row["ts"])
                if ts >= cutoff_retain:
                    rows.append({"ts": ts, "n": row["n"], "bull": row["bull"]})
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    # Use rows from the prior baseline window as denominator (excludes today)
    prior = [r for r in rows if r["ts"] >= cutoff_baseline]
    velocity: float | None = None
    bull_baseline: float | None = None
    if prior:
        avg_n = sum(r["n"] for r in prior) / len(prior)
        if avg_n > 0:
            velocity = round(n_now / avg_n, 3)
        bull_baseline = round(sum(r["bull"] for r in prior) / len(prior), 3)

    rows.append({"ts": now, "n": n_now, "bull": bull_now})
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps({"ts": r["ts"].isoformat(), "n": r["n"], "bull": r["bull"]}) + "\n")

    return velocity, bull_baseline
