"""
Crypto symbol helpers + the tradable universe.

Three symbol conventions are in play and must be kept straight:
  - **pair**  "BTC/USD"  — Alpaca order/asset symbol (canonical here)
  - **yf**    "BTC-USD"  — yfinance ticker for OHLCV
  - **flat**  "BTCUSD"   — how Alpaca sometimes returns crypto *position* symbols

`to_pair` normalizes any of the three back to the canonical pair form so trade
logging and position→plan matching stay consistent.

`tradable_pairs()` intersects the configured candidate universe with Alpaca's
live tradable crypto set (cached), so we never plan a coin the account can't buy.
"""
from __future__ import annotations

from src.config import CRYPTO_UNIVERSE
from src.data import _cache

ASSETS_TTL = 86400  # Alpaca's tradable crypto list changes rarely


def to_yf(pair: str) -> str:
    """'BTC/USD' -> 'BTC-USD' (yfinance)."""
    return pair.replace("/", "-")


def to_pair(symbol: str) -> str:
    """Normalize any crypto symbol form to canonical 'BASE/USD'.

    Handles 'BTC/USD', 'BTC-USD', and the flat 'BTCUSD' that Alpaca returns for
    some crypto positions. Only USD-quoted pairs are supported (our universe).
    """
    s = symbol.upper().strip()
    if "/" in s:
        return s
    if "-" in s:
        return s.replace("-", "/")
    for quote in ("USDT", "USDC", "USD"):
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}/{quote}"
    return s


def base_of(pair: str) -> str:
    """'BTC/USD' -> 'BTC'."""
    return to_pair(pair).split("/")[0]


def tradable_pairs() -> list[str]:
    """Configured universe ∩ Alpaca's live tradable crypto set.

    Falls back to the full configured universe if the Alpaca asset list can't be
    fetched (e.g. no keys) — the scanner then drops any coin yfinance can't load,
    so an un-tradable name can at worst produce a plan that the order rejects.
    """
    live = _live_tradable()
    if not live:
        return list(CRYPTO_UNIVERSE)
    return [p for p in CRYPTO_UNIVERSE if to_pair(p) in live]


def _live_tradable() -> set[str]:
    cached = _cache.get("alpaca_crypto_assets", "tradable", ASSETS_TTL)
    if cached is not None:
        return set(cached)
    try:
        from src.bot.alpaca import AlpacaClient

        client = AlpacaClient()
        assets = client.crypto_assets()
    except Exception:
        return set()
    pairs = {to_pair(a["symbol"]) for a in assets if a.get("tradable")}
    _cache.put("alpaca_crypto_assets", "tradable", sorted(pairs))
    return pairs
