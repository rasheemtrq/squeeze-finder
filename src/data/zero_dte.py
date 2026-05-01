"""
Same-day-expiry options chain fetcher for the 0DTE screener.

Restricted to a fixed universe of names that actually have daily expirations
(major-index ETFs + the most-liquid mega-caps). yfinance returns the chain
under the standard option_chain interface; we filter to dte == 0 and surface
the full strike grid (calls + puts) with the columns the scorer needs.

Cache TTL is short (60s during RTH, 600s otherwise) because 0DTE quotes move
fast and stale prices ruin the payoff simulation.
"""
from __future__ import annotations

import concurrent.futures
from datetime import UTC, date, datetime
from typing import Any

import yfinance as yf

from src.data import _cache
from src.data.prices import DataUnavailable
from src.util.market_hours import is_market_open

ZERO_DTE_UNIVERSE: list[str] = [
    "SPY", "QQQ", "IWM", "DIA",
    "TSLA", "NVDA", "AAPL", "AMZN", "MSFT", "META",
    "GOOGL", "AMD", "NFLX", "COIN", "MSTR",
]


def _ttl_seconds() -> int:
    return 60 if is_market_open() else 600


def _today_iso() -> str:
    return date.today().isoformat()


def fetch(ticker: str, force_refresh: bool = False) -> dict[str, Any]:
    """Return today's expiry chain for `ticker`, or raise DataUnavailable."""
    if not force_refresh:
        cached = _cache.get("zero_dte", ticker, _ttl_seconds())
        if cached:
            return cached

    tk = yf.Ticker(ticker)
    try:
        expiries = tk.options
    except Exception as e:
        raise DataUnavailable(f"options list failed for {ticker}: {e}") from e
    if not expiries:
        raise DataUnavailable(f"no options for {ticker}")

    today_iso = _today_iso()
    if expiries[0] != today_iso:
        raise DataUnavailable(f"{ticker} has no 0DTE chain (next expiry {expiries[0]})")

    # Spot must be live for 0DTE — period="1d" returns an aggregated daily
    # bar whose Close lags the live tape (we observed ITM strikes with
    # bid < intrinsic during RTH, the classic sign of stale-spot vs
    # fresh-quote mismatch). 1-minute bars give the live tape.
    try:
        intraday = tk.history(period="1d", interval="1m")
        if intraday.empty:
            intraday = tk.history(period="2d", interval="1m")
        spot = float(intraday["Close"].iloc[-1])
    except Exception as e:
        raise DataUnavailable(f"spot fetch failed for {ticker}: {e}") from e

    try:
        chain = tk.option_chain(today_iso)
    except Exception as e:
        raise DataUnavailable(f"chain fetch failed for {ticker}: {e}") from e

    def _rows(df, side: str) -> list[dict]:
        if df is None or df.empty:
            return []
        out: list[dict] = []
        for col in ("bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility"):
            if col in df.columns:
                df[col] = df[col].fillna(0)
        for _, row in df.iterrows():
            out.append({
                "side": side,
                "strike": float(row["strike"]),
                "bid": float(row["bid"]),
                "ask": float(row["ask"]),
                "last": float(row["lastPrice"]),
                "volume": int(row["volume"]),
                "open_interest": int(row["openInterest"]),
                "iv": float(row["impliedVolatility"]),
            })
        return out

    chain_stale = False
    contracts = _rows(chain.calls, "call") + _rows(chain.puts, "put")
    if contracts:
        chain_stale = all(c["bid"] == 0 and c["ask"] == 0 for c in contracts)

    result = {
        "ticker": ticker,
        "as_of": datetime.now(UTC).isoformat(),
        "spot": spot,
        "expiry": today_iso,
        "chain_stale": chain_stale,
        "contracts": contracts,
    }
    _cache.put("zero_dte", ticker, result)
    return result


def fetch_universe(force_refresh: bool = False) -> dict[str, Any]:
    """Fetch all 0DTE-eligible tickers in parallel; soft-fail per ticker."""
    chains: dict[str, dict] = {}
    errors: dict[str, str] = {}

    def _one(t: str) -> tuple[str, dict | None, str | None]:
        try:
            return t, fetch(t, force_refresh=force_refresh), None
        except DataUnavailable as e:
            return t, None, str(e)
        except Exception as e:
            return t, None, f"unexpected: {e}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for t, data, err in pool.map(_one, ZERO_DTE_UNIVERSE):
            if data:
                chains[t] = data
            elif err:
                errors[t] = err

    return {
        "as_of": datetime.now(UTC).isoformat(),
        "expiry": _today_iso(),
        "chains": chains,
        "errors": errors,
    }
