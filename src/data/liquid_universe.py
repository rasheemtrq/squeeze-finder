"""
Dynamic liquid-leaders universe for the SWING scanner.

A swing leader you don't scan is a swing leader you can't catch. This builds a
broad, liquid candidate pool and lets the scanner's RS/Stage-2 factors surface
the actual leaders — rather than betting on a hand-picked list that goes stale.

Composition:
  • S&P 500 constituents (datahub CSV — self-maintaining, zero extra deps)
  • a small supplement of liquid, high-volume momentum/growth names that the
    index lags on (recent IPOs, crypto-equities) — these are prime swing
    vehicles often added to the index only after the move.

The list is cached weekly. If the fetch fails and no cache exists, we fall back
to the supplement + core so a scan never hard-fails on a network blip.
"""
from __future__ import annotations

import csv
from io import StringIO

import httpx

from src.config import DEFAULT_UNIVERSE
from src.data import _cache

_SP500_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
_CACHE_NS = "universe_lists"
_CACHE_KEY = "liquid_swing"
_CACHE_TTL = 7 * 86400  # refresh weekly

# Liquid, high-$-volume momentum/growth names that are prime swing vehicles but
# frequently outside (or late additions to) the S&P 500. Dedup handles overlap
# with the index, so listing one already in the S&P is harmless.
LIQUID_SUPPLEMENT = [
    "RKLB", "ASTS", "IONQ", "RGTI", "QBTS", "SOFI", "AFRM", "HIMS", "DUOL",
    "RDDT", "CART", "ARM", "CRWV", "MSTR", "MARA", "RIOT", "CLSK", "IREN",
    "CVNA", "HOOD", "COIN", "SMCI", "PLTR", "NBIS", "APP", "TTD", "U",
    "RBLB", "OKLO", "SMR", "VST", "TLN", "CELH", "ELF", "ONON", "TOST",
]

# Index/leveraged ETFs and common non-equity symbols we never scan.
EXCLUDED = {
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VXX", "UVXY", "SQQQ", "TQQQ",
    "TLT", "GLD", "SLV", "USO", "GBTC", "IBIT",
}


def _normalize(sym: str) -> str:
    # yfinance uses '-' for class shares (BRK.B -> BRK-B, BF.B -> BF-B).
    return sym.upper().strip().replace(".", "-")


def _fetch_sp500() -> list[str]:
    r = httpx.get(_SP500_CSV, headers={"User-Agent": "Mozilla/5.0"}, timeout=20, follow_redirects=True)
    r.raise_for_status()
    rows = list(csv.DictReader(StringIO(r.text)))
    if not rows:
        raise ValueError("S&P 500 CSV returned no rows")
    col = next((c for c in ("Symbol", "symbol") if c in rows[0]), None)
    if not col:
        raise ValueError(f"no Symbol column in S&P 500 CSV: {list(rows[0].keys())}")
    return [_normalize(row[col]) for row in rows if row.get(col)]


def _assemble(sp500: list[str]) -> dict:
    seen: set[str] = set()
    tickers: list[str] = []
    sources: dict[str, list[str]] = {"sp500": [], "supplement": [], "core": []}

    def _add(sym: str, src: str) -> None:
        sym = _normalize(sym)
        if not sym or sym in seen or sym in EXCLUDED:
            return
        seen.add(sym)
        tickers.append(sym)
        sources[src].append(sym)

    for s in sp500:
        _add(s, "sp500")
    for s in LIQUID_SUPPLEMENT:
        _add(s, "supplement")
    for s in DEFAULT_UNIVERSE:  # keep the squeeze core in the pool too
        _add(s, "core")

    return {"tickers": tickers, "sources": sources}


def build(force_refresh: bool = False) -> dict:
    """Return {tickers, sources} for the liquid swing universe (cached weekly)."""
    if not force_refresh:
        cached = _cache.get(_CACHE_NS, _CACHE_KEY, _CACHE_TTL)
        if cached:
            cached["cached"] = True
            return cached

    try:
        sp500 = _fetch_sp500()
        result = _assemble(sp500)
        result["cached"] = False
        _cache.put(_CACHE_NS, _CACHE_KEY, result)
        return result
    except Exception as e:
        # Last-resort: stale cache if any, else supplement + core so we never crash.
        stale = _cache.get(_CACHE_NS, _CACHE_KEY, ttl_seconds=10**9)
        if stale:
            stale["cached"] = True
            stale["fallback"] = f"fetch_failed: {e}"
            return stale
        fallback = _assemble([])
        fallback["cached"] = False
        fallback["fallback"] = f"fetch_failed_no_cache: {e}"
        return fallback
