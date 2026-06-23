"""
Crypto bot runner — DRY-RUN by default, PAPER ONLY on execute.

`run(execute=False)` builds the momentum plan and returns it without ordering.
`run(execute=True)` manages exits on open crypto positions, then places new PAPER
spot orders for the plan — subject to the same hard risk caps + daily-loss kill
switch as the options bot. Unlike equities there is **no market-hours gate**:
crypto trades 24/7.

Open/close events are appended to data/bot_trades.jsonl with strategy
"spot_momentum", so the knowledge graph ingests crypto trades alongside options
trades (R = realized% / planned-stop%). Exits are managed from those logged
plans: each open records its stop%, target% and time stop.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.bot.runner import apply_risk_caps  # shared slots + deploy-cap trimming
from src.config import BOT_TRADES_LOG, CRYPTO_BOT_PARAMS
from src.crypto import strategy
from src.crypto.scanner import scan_crypto
from src.crypto.universe import to_pair

STRATEGY = "spot_momentum"


def _log(event: dict) -> None:
    row = {"ts": datetime.now(UTC).isoformat(), **event}
    with BOT_TRADES_LOG.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _open_crypto_plans() -> dict[str, dict]:
    """Replay the trade log → still-open crypto trades keyed by canonical pair.

    Only spot_momentum opens are considered, so option trades never collide.
    Each value is the full open event (carries the plan + open ts).
    """
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


def manage_exits(client, params: dict | None = None) -> list[dict]:
    """Close spot crypto positions that hit their target / stop / time stop.

    Thresholds come from the logged open plan (per-coin ATR levels). Positions
    with no matching open plan (e.g. opened by hand) are left untouched.
    """
    params = params or CRYPTO_BOT_PARAMS
    open_map = _open_crypto_plans()
    closed: list[dict] = []
    for pos in client.crypto_positions():
        pair = to_pair(pos.get("symbol", ""))
        op = open_map.get(pair)
        if not op:
            continue  # only manage what this bot opened
        exit_plan = (op.get("plan") or {}).get("exit") or {}
        try:
            plpc = float(pos.get("unrealized_plpc") or 0) * 100
        except (ValueError, TypeError):
            plpc = 0.0
        sl_pct = exit_plan.get("sl_pct")
        tp_pct = exit_plan.get("tp_pct")
        time_stop = exit_plan.get("time_stop_days", params["time_stop_days"])

        reason = None
        if tp_pct and plpc >= tp_pct:
            reason = "tp"
        elif sl_pct and plpc <= -sl_pct:
            reason = "sl"
        elif _held_days(op.get("ts")) >= time_stop:
            reason = "time_stop"
        if not reason:
            continue
        try:
            client.close_position(pair)
            _log({"event": "close", "symbol": pair, "ticker": pair, "reason": reason,
                  "plpc": round(plpc, 2)})
            closed.append({"symbol": pair, "reason": reason, "plpc": round(plpc, 2)})
        except Exception as e:  # noqa: BLE001 - log + continue, never abort the loop
            _log({"event": "close_error", "symbol": pair, "error": str(e)})
    return closed


def build_daily_plan(
    limit: int = 15,
    equity: float | None = None,
    params: dict | None = None,
    skip_pairs: set[str] | None = None,
    open_count: int = 0,
) -> dict[str, Any]:
    params = params or CRYPTO_BOT_PARAMS
    equity = equity if equity is not None else params["default_equity"]
    result = scan_crypto(limit=limit)
    setups = result.get("results") or []

    from src.graph.build import build as build_graph

    graph, _ = build_graph()
    plans = strategy.build_plans(setups, equity, params, skip_pairs=skip_pairs, graph=graph)
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


def run(execute: bool = False, limit: int = 15, params: dict | None = None) -> dict[str, Any]:
    params = params or CRYPTO_BOT_PARAMS

    if not execute:
        plan = build_daily_plan(limit=limit, params=params)
        plan["mode"] = "dry_run"
        return plan

    from src.bot.alpaca import AlpacaClient

    client = AlpacaClient()  # paper-guarded; raises if pointed at live or no keys

    # No market-hours gate — crypto trades 24/7.
    account = client.account()
    equity = float(account.get("equity") or params["default_equity"])
    pl_pct = _daily_pl_pct(account)

    # Kill switch: at/under the daily loss limit, cut losers but open nothing new.
    if pl_pct <= -params["max_daily_loss_pct"]:
        _log({"event": "kill_switch", "scope": "crypto", "daily_pl_pct": round(pl_pct, 2)})
        closed = manage_exits(client, params)
        return {"mode": "halted", "reason": "daily_loss_limit",
                "daily_pl_pct": round(pl_pct, 2), "closed": closed}

    closed = manage_exits(client, params)
    open_positions = client.crypto_positions()
    if len(open_positions) >= params["max_open_positions"]:
        return {
            "mode": "executed", "asset": "crypto", "equity": equity,
            "daily_pl_pct": round(pl_pct, 2), "closed": closed, "placed": [], "errors": [],
            "note": "max positions held — managed exits only",
        }
    held = {to_pair(p["symbol"]) for p in open_positions}

    plan = build_daily_plan(
        limit=limit, equity=equity, params=params,
        skip_pairs=held, open_count=len(open_positions),
    )

    placed: list[dict] = []
    errors: list[dict] = []
    for p in plan["selected"]:
        try:
            order = client.submit_crypto(p["ticker"], p["notional"], side="buy")
            _log({"event": "open", "ticker": p["ticker"], "symbol": p["ticker"],
                  "notional": p["notional"], "order_id": order.get("id"), "plan": p})
            placed.append({"ticker": p["ticker"], "notional": p["notional"]})
        except Exception as e:  # noqa: BLE001 - log + continue to the next plan
            _log({"event": "open_error", "ticker": p["ticker"], "error": str(e)})
            errors.append({"ticker": p["ticker"], "error": str(e)})

    return {
        "mode": "executed",
        "asset": "crypto",
        "equity": equity,
        "daily_pl_pct": round(pl_pct, 2),
        "closed": closed,
        "placed": placed,
        "errors": errors,
        "deployed_usd": plan["deployed_usd"],
    }
