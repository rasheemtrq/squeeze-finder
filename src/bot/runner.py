"""
Bot runner — DRY-RUN by default.

`run(execute=False)` builds the day's options plan and returns it WITHOUT
placing any order. `run(execute=True)` (paper keys required) first manages exits
on open positions, then places new PAPER orders for the plan — subject to hard
risk caps and a daily-loss kill switch. Every action is appended to
data/bot_trades.jsonl so the paper run's expectancy can be measured.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any

from src.bot import strategy
from src.config import BOT_PARAMS, BOT_TRADES_LOG
from src.scanner import scan


def _log(event: dict) -> None:
    row = {"ts": datetime.now(UTC).isoformat(), **event}
    with BOT_TRADES_LOG.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _dte_from_occ(symbol: str) -> int | None:
    m = re.search(r"(\d{6})[CP]\d{8}$", symbol)
    if not m:
        return None
    ymd = m.group(1)
    try:
        exp = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
        return (exp - date.today()).days
    except ValueError:
        return None


def _underlying_of(symbol: str) -> str:
    return symbol[:-15] if len(symbol) > 15 else symbol


def apply_risk_caps(
    plans: list[dict], equity: float, params: dict, open_count: int
) -> tuple[list[dict], list[dict], float]:
    """Trim plans to satisfy max_open_positions and the total deploy cap."""
    slots = max(0, params["max_open_positions"] - open_count)
    deploy_cap = equity * params["max_deploy_pct"] / 100.0
    kept: list[dict] = []
    dropped: list[dict] = []
    deployed = 0.0
    for p in plans:
        if len(kept) >= slots:
            dropped.append({"ticker": p["ticker"], "reason": "max_positions"})
            continue
        if deployed + p["est_cost"] > deploy_cap:
            dropped.append({"ticker": p["ticker"], "reason": "deploy_cap"})
            continue
        kept.append(p)
        deployed += p["est_cost"]
    return kept, dropped, round(deployed, 2)


def build_daily_plan(
    limit: int = 15,
    equity: float | None = None,
    params: dict | None = None,
    skip_tickers: set[str] | None = None,
    open_count: int = 0,
) -> dict[str, Any]:
    params = params or BOT_PARAMS
    equity = equity if equity is not None else params["default_equity"]
    result = scan(limit=limit, sort_by="composite")
    setups = result.get("results") or []

    # Learned feedback: rebuild the trade knowledge graph and let it nudge the
    # ranking. Gated — neutral until signals have enough trades, so this is a
    # no-op early on and gradually biases toward what's actually worked.
    from src.graph.build import build as build_graph

    graph, _ = build_graph()
    plans = strategy.build_plans(setups, equity, params, skip_tickers=skip_tickers, graph=graph)
    kept, dropped, deployed = apply_risk_caps(plans, equity, params, open_count)
    return {
        "as_of": datetime.now(UTC).isoformat(),
        "equity": equity,
        "scanned": len(setups),
        "graph_trades": graph.n_trades,
        "candidates": len(plans),
        "selected": kept,
        "dropped": dropped,
        "deployed_usd": deployed,
        "deploy_cap_usd": round(equity * params["max_deploy_pct"] / 100, 2),
    }


def _daily_pl_pct(account: dict) -> float:
    try:
        eq, last = float(account["equity"]), float(account["last_equity"])
        return (eq - last) / last * 100 if last else 0.0
    except (KeyError, ValueError, TypeError):
        return 0.0


def manage_exits(client, params: dict | None = None) -> list[dict]:
    """Close option positions that hit TP / SL / the DTE time stop."""
    params = params or BOT_PARAMS
    closed: list[dict] = []
    for pos in client.positions():
        sym = pos.get("symbol", "")
        dte = _dte_from_occ(sym)
        if dte is None:
            continue  # not an option position we manage
        try:
            plpc = float(pos.get("unrealized_plpc") or 0) * 100
        except (ValueError, TypeError):
            plpc = 0.0
        reason = None
        if plpc >= params["option_tp_pct"]:
            reason = "tp"
        elif plpc <= -params["option_sl_pct"]:
            reason = "sl"
        elif dte <= params["time_stop_dte"]:
            reason = "time_stop"
        if not reason:
            continue
        try:
            client.close_position(sym)
            _log({"event": "close", "symbol": sym, "reason": reason, "plpc": round(plpc, 1), "dte": dte})
            closed.append({"symbol": sym, "reason": reason, "plpc": round(plpc, 1)})
        except Exception as e:  # noqa: BLE001 - log + continue, never abort the loop
            _log({"event": "close_error", "symbol": sym, "error": str(e)})
    return closed


def run(execute: bool = False, limit: int = 15, params: dict | None = None) -> dict[str, Any]:
    params = params or BOT_PARAMS

    if not execute:
        plan = build_daily_plan(limit=limit, params=params)
        plan["mode"] = "dry_run"
        return plan

    from src.bot.alpaca import AlpacaClient

    client = AlpacaClient()  # paper-guarded; raises if pointed at live or no keys
    account = client.account()
    equity = float(account.get("equity") or params["default_equity"])
    pl_pct = _daily_pl_pct(account)

    # Kill switch: at/under the daily loss limit, cut losers but open nothing new.
    if pl_pct <= -params["max_daily_loss_pct"]:
        _log({"event": "kill_switch", "daily_pl_pct": round(pl_pct, 2)})
        closed = manage_exits(client, params)
        return {
            "mode": "halted",
            "reason": "daily_loss_limit",
            "daily_pl_pct": round(pl_pct, 2),
            "closed": closed,
        }

    closed = manage_exits(client, params)
    open_positions = client.positions()
    held_underlyings = {_underlying_of(p["symbol"]) for p in open_positions}

    plan = build_daily_plan(
        limit=limit, equity=equity, params=params,
        skip_tickers=held_underlyings, open_count=len(open_positions),
    )

    placed: list[dict] = []
    errors: list[dict] = []
    for p in plan["selected"]:
        c = p["contract"]
        try:
            sym = client.find_option_contract(p["ticker"], c["expiry"], "call", c["strike"]) or c["occ_symbol"]
            order = client.submit_option(sym, p["qty"], side="buy")
            _log({"event": "open", "ticker": p["ticker"], "symbol": sym, "qty": p["qty"],
                  "est_cost": p["est_cost"], "order_id": order.get("id"), "plan": p})
            placed.append({"ticker": p["ticker"], "symbol": sym, "qty": p["qty"], "est_cost": p["est_cost"]})
        except Exception as e:  # noqa: BLE001 - log + continue to the next plan
            _log({"event": "open_error", "ticker": p["ticker"], "error": str(e)})
            errors.append({"ticker": p["ticker"], "error": str(e)})

    return {
        "mode": "executed",
        "equity": equity,
        "daily_pl_pct": round(pl_pct, 2),
        "closed": closed,
        "placed": placed,
        "errors": errors,
        "deployed_usd": plan["deployed_usd"],
    }
