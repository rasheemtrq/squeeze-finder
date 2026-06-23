"""
Minimal Alpaca client — PAPER ONLY in this build.

The constructor refuses to run against the live endpoint (raises unless paper).
Covers what the bot needs: account, positions, find a tradable option contract,
submit an option order, close a position. Real orders only ever hit the paper
sandbox (https://paper-api.alpaca.markets).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from src.config import ALPACA_API_KEY, ALPACA_PAPER, ALPACA_SECRET_KEY

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"  # market data (crypto data is free; no separate sub)


class AlpacaError(Exception):
    pass


class AlpacaClient:
    def __init__(self, paper: bool | None = None) -> None:
        self.paper = ALPACA_PAPER if paper is None else paper
        if not self.paper:
            raise AlpacaError("live trading is disabled in this build — paper only")
        if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
            raise AlpacaError(
                "ALPACA_API_KEY / ALPACA_SECRET_KEY not set — add paper keys to .env"
            )
        self.base = PAPER_URL
        self._h = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        }

    # ---- low-level
    def _get(self, path: str, params: dict | None = None) -> Any:
        r = httpx.get(self.base + path, headers=self._h, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> Any:
        r = httpx.post(self.base + path, headers=self._h, json=body, timeout=20)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> Any:
        r = httpx.delete(self.base + path, headers=self._h, timeout=20)
        r.raise_for_status()
        return r.json() if r.text.strip() else {}

    # ---- market clock
    def clock(self) -> dict:
        return self._get("/v2/clock")

    def is_market_open(self) -> bool:
        try:
            return bool(self.clock().get("is_open"))
        except Exception:
            return False

    # ---- account / positions
    def account(self) -> dict:
        return self._get("/v2/account")

    def positions(self) -> list[dict]:
        return self._get("/v2/positions")

    def orders(self, status: str = "open") -> list[dict]:
        return self._get("/v2/orders", {"status": status, "limit": 100})

    # ---- options
    def find_option_contract(
        self, underlying: str, expiry: str, opt_type: str, strike: float
    ) -> str | None:
        """Return Alpaca's tradable contract symbol for the exact strike/expiry, or None."""
        data = self._get(
            "/v2/options/contracts",
            {
                "underlying_symbols": underlying.upper(),
                "expiration_date": expiry,
                "type": opt_type.lower(),
                "strike_price_gte": strike - 0.01,
                "strike_price_lte": strike + 0.01,
                "limit": 5,
            },
        )
        contracts = data.get("option_contracts") or []
        return contracts[0]["symbol"] if contracts else None

    def submit_option(self, symbol: str, qty: int, side: str = "buy", tif: str = "day") -> dict:
        return self._post(
            "/v2/orders",
            {
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": "market",
                "time_in_force": tif,
                "order_class": "simple",
            },
        )

    def close_position(self, symbol: str) -> dict:
        # Alpaca's positions endpoint keys crypto by the FLAT symbol ('BTCUSD'),
        # not the slashed order form ('BTC/USD') — strip the slash. No-op for
        # alphanumeric OCC option symbols.
        return self._delete(f"/v2/positions/{symbol.replace('/', '')}")

    # ---- spot crypto (same paper account; 24/7)
    def crypto_assets(self) -> list[dict]:
        """Active, tradable crypto assets on the account."""
        return self._get("/v2/assets", {"asset_class": "crypto", "status": "active"})

    def crypto_positions(self) -> list[dict]:
        return [p for p in self.positions() if p.get("asset_class") == "crypto"]

    def _data_get(self, path: str, params: dict | None = None) -> Any:
        r = httpx.get(DATA_URL + path, headers=self._h, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def crypto_bars(
        self, symbols: list[str], timeframe: str = "1Min", limit: int = 60
    ) -> dict[str, list[dict]]:
        """Recent OHLCV bars per symbol (last `limit` bars each), normalized.

        Alpaca's `limit` is a TOTAL cap across all symbols and the response
        paginates, so a single capped call starves most symbols. We bound by a
        recent `start` window and follow next_page_token, then trim each symbol
        to its most recent `limit` bars. Crypto data is real-time and free."""
        # generous window: minutes may have no trades, so over-request bars.
        start = (datetime.now(UTC) - timedelta(minutes=limit * 5 + 60)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        out: dict[str, list[dict]] = {}
        page_token: str | None = None
        for _ in range(15):  # page cap — backstop against runaway pagination
            params: dict[str, Any] = {
                "symbols": ",".join(symbols), "timeframe": timeframe,
                "start": start, "limit": 10000,
            }
            if page_token:
                params["page_token"] = page_token
            data = self._data_get("/v1beta3/crypto/us/bars", params)
            for sym, raw in (data.get("bars") or {}).items():
                out.setdefault(sym, []).extend(
                    {
                        "date": b.get("t"),
                        "open": float(b["o"]),
                        "high": float(b["h"]),
                        "low": float(b["l"]),
                        "close": float(b["c"]),
                        "volume": float(b.get("v") or 0),
                    }
                    for b in raw
                )
            page_token = data.get("next_page_token")
            if not page_token:
                break
        return {sym: bars[-limit:] for sym, bars in out.items()}

    def crypto_latest_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Latest bid/ask per symbol with spread % (for cost modeling/entry)."""
        data = self._data_get(
            "/v1beta3/crypto/us/latest/quotes", {"symbols": ",".join(symbols)}
        )
        out: dict[str, dict] = {}
        for sym, q in (data.get("quotes") or {}).items():
            bid, ask = q.get("bp"), q.get("ap")
            spread_pct = (ask - bid) / ask * 100 if bid and ask and ask > 0 else None
            out[sym] = {"bid": bid, "ask": ask, "spread_pct": spread_pct}
        return out

    def submit_crypto(
        self, symbol: str, notional: float, side: str = "buy", tif: str = "gtc"
    ) -> dict:
        """Market order for a dollar `notional` of spot crypto. Crypto requires a
        GTC/IOC time-in-force (not 'day'); notional orders buy fractional size."""
        return self._post(
            "/v2/orders",
            {
                "symbol": symbol,
                "notional": str(round(notional, 2)),
                "side": side,
                "type": "market",
                "time_in_force": tif,
            },
        )
