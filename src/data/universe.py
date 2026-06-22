"""
Dynamic universe layer. Combines the curated core watchlist with two free
"what's hot" sources so that emerging plays outside the static list get scored:

  1. Apewisdom WSB top N — squeeze-flavored retail attention
  2. StockTwits trending — broader retail attention spike

Returns the dedup'd union, capped at MAX_UNIVERSE so scan time stays bounded.
"""
from __future__ import annotations

from src.data import apewisdom, trending
from src.data.prices import DataUnavailable
from src.data.finnhub import is_valid_ticker, fetch_quote

MAX_UNIVERSE = 80
# Keep dynamic universe small for "right signals" quality.
# Large WSB/trending lists bring in too much noise and dead tickers.
# We now heavily gate dynamic names with Finnhub validity + liquidity.
WSB_TOP_N = 20
TRENDING_TOP_N = 12

# Tickers we never want to scan (ETFs that aren't squeeze candidates, indexes,
# common false-positive symbols from trending feeds).
EXCLUDED = {
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VXX", "UVXY", "SQQQ", "TQQQ",
    "TLT", "GLD", "SLV", "USO",
}


def _wsb_top(n: int) -> list[str]:
    try:
        full = apewisdom.fetch_all()
    except DataUnavailable:
        return []
    ranked = sorted(full["tickers"].items(), key=lambda kv: kv[1]["rank"])
    return [t for t, _ in ranked[:n]]


def _trending_top(n: int) -> list[str]:
    try:
        return trending.fetch()["tickers"][:n]
    except DataUnavailable:
        return []


def build(core: list[str]) -> dict:
    """Return {tickers, sources} for the scan. `core` is preserved in order."""
    seen: set[str] = set()
    final: list[str] = []
    sources: dict[str, list[str]] = {"core": [], "wsb": [], "trending": []}

    def _add(t: str, src: str) -> None:
        t = t.upper().strip()
        if not t or t in seen or t in EXCLUDED:
            return
        if len(final) >= MAX_UNIVERSE:
            return

        # Strong gate for dynamic sources: require Finnhub to see a real, liquid ticker
        if src in ("wsb", "trending"):
            if not is_valid_ticker(t):
                return
            q = fetch_quote(t) or {}
            # Require at least some meaningful recent volume/price
            if not q.get("current_price") or (q.get("current_price", 0) < 0.50):
                return

        seen.add(t)
        final.append(t)
        sources[src].append(t)

    for t in core:
        _add(t, "core")
    for t in _wsb_top(WSB_TOP_N):
        _add(t, "wsb")
    for t in _trending_top(TRENDING_TOP_N):
        _add(t, "trending")

    return {"tickers": final, "sources": sources}
