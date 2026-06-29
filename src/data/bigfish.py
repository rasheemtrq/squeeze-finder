"""
"Big fish" — market-wide volume leaders.

Follows where the money is by pulling Alpaca's most-active-stocks screener (full
consolidated volume, real-time) and enriching with price and % change. The
default ranking is **dollar volume** (shares × price), which surfaces the real
big fish (megacaps + index ETFs) rather than low-price share churn or leveraged
ETFs that top the raw-share list.

Cached briefly so repeated views during a session don't re-hit the API.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.data import _cache

CACHE_TTL = 120  # seconds — volume leaders shift slowly intraday
POOL = 50        # pull a wider pool so dollar-volume re-ranking has candidates

_SORTS = {
    "dollar_volume": lambda r: r["dollar_volume"],
    "volume": lambda r: r["volume"],
    "trades": lambda r: r["trade_count"],
    "change": lambda r: abs(r["change_pct"]),
}


def get_big_fish(top: int = 25, sort_by: str = "dollar_volume") -> dict[str, Any]:
    """Volume leaders enriched with price, % change, and dollar volume."""
    if sort_by not in _SORTS:
        sort_by = "dollar_volume"
    ckey = f"{sort_by}:{top}"
    cached = _cache.get("bigfish", ckey, CACHE_TTL)
    if cached:
        return {**cached, "cached": True}

    from src.bot.alpaca import AlpacaClient

    client = AlpacaClient()
    actives = client.most_active_stocks(top=max(POOL, top), by="volume")
    syms = [a["symbol"] for a in actives]
    vol = {a["symbol"]: a["volume"] for a in actives}
    trades = {a["symbol"]: a["trade_count"] for a in actives}
    snaps = client.stock_snapshots(syms) if syms else {}

    rows: list[dict] = []
    for s in syms:
        snap = snaps.get(s) or {}
        db = snap.get("dailyBar") or {}
        pdb = snap.get("prevDailyBar") or {}
        lt = snap.get("latestTrade") or {}
        price = lt.get("p") or db.get("c") or 0.0
        ref = db.get("vw") or db.get("c") or price  # VWAP is steadier than a single print
        prev_c = pdb.get("c")
        change_pct = (db.get("c", 0) / prev_c - 1) * 100 if prev_c else 0.0
        rows.append({
            "symbol": s,
            "volume": vol.get(s, 0),
            "trade_count": trades.get(s, 0),
            "price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "dollar_volume": round(vol.get(s, 0) * ref, 0),
        })

    rows.sort(key=_SORTS[sort_by], reverse=True)
    out = {
        "as_of": datetime.now(UTC).isoformat(),
        "sort_by": sort_by,
        "count": len(rows),
        "rows": rows[:top],
    }
    _cache.put("bigfish", ckey, out)
    return out
