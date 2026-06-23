"""
Swing-share bot runner — DRY-RUN by default, PAPER ONLY on execute.

`run(execute=False)` builds the swing plan and returns it without ordering.
`run(execute=True)` gates on the Alpaca market clock (equities trade regular
hours only), manages exits on open swing positions, then buys shares for the
plan within the hard risk caps + daily-loss kill switch.

Trades are tagged strategy "swing_shares" and logged to data/bot_trades.jsonl so
the knowledge graph learns from them. Manages only its own positions (by logged
strategy); names already held are skipped. Holds run weeks — exits on the first
R-target, the ATR/structural stop, or a holding-time cap.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.bot.runner import apply_risk_caps
from src.config import BOT_TRADES_LOG, SWING_BOT_PARAMS
from src.swing import strategy

STRATEGY = "swing_shares"


def _log(event: dict) -> None:
    row = {"ts": datetime.now(UTC).isoformat(), **event}
    with BOT_TRADES_LOG.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _open_swing_plans() -> dict[str, dict]:
    if not BOT_TRADES_LOG.exists():
        return {}
    opens: dict[str, dict] = {}
    for line in BOT_TRADES_LOG.read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        plan = ev.get("plan") or {}
        if ev.get("event") == "open" and plan.get("strategy") == STRATEGY:
            opens[ev.get("symbol")] = ev
        elif ev.get("event") == "close" and ev.get("symbol") in opens:
            opens.pop(ev.get("symbol"), None)
    return opens


def _held_days(open_ts: str | None) -> int:
    if not open_ts:
        return 0
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(open_ts)).days
    except (ValueError, TypeError):
        return 0


def _daily_pl_pct(account: dict) -> float:
    try:
        eq, last = float(account["equity"]), float(account["last_equity"])
        return (eq - last) / last * 100 if last else 0.0
    except (KeyError, ValueError, TypeError):
        return 0.0


def manage_exits(client, params: dict) -> list[dict]:
    """Close share positions on the R-target, the stop, or the holding-time cap."""
    open_map = _open_swing_plans()
    closed: list[dict] = []
    for pos in client.equity_positions():
        sym = (pos.get("symbol") or "").upper()
        op = open_map.get(sym)
        if not op:
            continue  # only manage swing positions this bot opened
        ep = (op.get("plan") or {}).get("exit") or {}
        try:
            plpc = float(pos.get("unrealized_plpc") or 0) * 100
        except (ValueError, TypeError):
            plpc = 0.0
        reason = None
        if ep.get("tp_pct") and plpc >= ep["tp_pct"]:
            reason = "tp"
        elif ep.get("sl_pct") and plpc <= -ep["sl_pct"]:
            reason = "sl"
        elif _held_days(op.get("ts")) >= ep.get("time_stop_days", params["time_stop_days"]):
            reason = "time_stop"
        if not reason:
            continue
        try:
            client.close_position(sym)
            _log({"event": "close", "symbol": sym, "ticker": sym, "reason": reason,
                  "plpc": round(plpc, 2)})
            closed.append({"symbol": sym, "reason": reason, "plpc": round(plpc, 2)})
        except Exception as e:  # noqa: BLE001 - log + continue, never abort the loop
            _log({"event": "close_error", "symbol": sym, "error": str(e)})
    return closed


def build_daily_plan(
    equity: float | None = None,
    params: dict | None = None,
    skip_tickers: set[str] | None = None,
    open_count: int = 0,
) -> dict[str, Any]:
    params = params or SWING_BOT_PARAMS
    equity = equity if equity is not None else params["default_equity"]

    from src.swing_scanner import swing_scan

    result = swing_scan(min_score=0, limit=params["scan_limit"])
    setups = result.get("results") or []

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


def run(execute: bool = False, params: dict | None = None) -> dict[str, Any]:
    params = params or SWING_BOT_PARAMS

    if not execute:
        plan = build_daily_plan(params=params)
        plan["mode"] = "dry_run"
        return plan

    from src.bot.alpaca import AlpacaClient

    client = AlpacaClient()  # paper-guarded; raises if pointed at live or no keys

    # Equities trade regular hours only — gate on the Alpaca clock.
    if not client.is_market_open():
        _log({"event": "skip", "scope": "swing", "reason": "market_closed"})
        return {"mode": "market_closed", "note": "market closed — no orders placed"}

    account = client.account()
    equity = float(account.get("equity") or params["default_equity"])
    pl_pct = _daily_pl_pct(account)

    if pl_pct <= -params["max_daily_loss_pct"]:
        _log({"event": "kill_switch", "scope": "swing", "daily_pl_pct": round(pl_pct, 2)})
        closed = manage_exits(client, params)
        return {"mode": "halted", "reason": "daily_loss_limit",
                "daily_pl_pct": round(pl_pct, 2), "closed": closed}

    closed = manage_exits(client, params)

    positions = client.equity_positions()
    held = {(p.get("symbol") or "").upper() for p in positions}
    swing_held = held & set(_open_swing_plans().keys())
    if len(swing_held) >= params["max_open_positions"]:
        return {"mode": "executed", "asset": "swing_shares", "equity": equity,
                "daily_pl_pct": round(pl_pct, 2), "closed": closed, "placed": [], "errors": [],
                "note": "max swing positions held — managed exits only"}

    plan = build_daily_plan(
        equity=equity, params=params, skip_tickers=held, open_count=len(swing_held)
    )

    placed: list[dict] = []
    errors: list[dict] = []
    for p in plan["selected"]:
        try:
            order = client.submit_equity(p["ticker"], p["notional"], side="buy")
            _log({"event": "open", "ticker": p["ticker"], "symbol": p["ticker"].upper(),
                  "notional": p["notional"], "order_id": order.get("id"), "plan": p})
            placed.append({"ticker": p["ticker"], "notional": p["notional"]})
        except Exception as e:  # noqa: BLE001 - log + continue to the next plan
            _log({"event": "open_error", "ticker": p["ticker"], "error": str(e)})
            errors.append({"ticker": p["ticker"], "error": str(e)})

    return {"mode": "executed", "asset": "swing_shares", "equity": equity,
            "daily_pl_pct": round(pl_pct, 2), "closed": closed, "placed": placed,
            "errors": errors, "deployed_usd": plan["deployed_usd"]}
