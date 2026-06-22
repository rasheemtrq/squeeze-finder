"""
Minimal Alpaca client — PAPER ONLY in this build.

The constructor refuses to run against the live endpoint (raises unless paper).
Covers what the bot needs: account, positions, find a tradable option contract,
submit an option order, close a position. Real orders only ever hit the paper
sandbox (https://paper-api.alpaca.markets).
"""
from __future__ import annotations

from typing import Any

import httpx

from src.config import ALPACA_API_KEY, ALPACA_PAPER, ALPACA_SECRET_KEY

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"


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
        return self._delete(f"/v2/positions/{symbol}")
