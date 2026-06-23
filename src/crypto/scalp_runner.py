"""
Intraday crypto scalp runner — DRY-RUN by default, PAPER ONLY on execute.

Designed to fire every ~60s (launchd). Each cycle: pull live 1-minute bars,
manage open scalp positions (gross move triggers TP/SL/time stop), then open new
scalps within the risk caps. No market-hours gate (crypto is 24/7).

Cost honesty: exits trigger on the GROSS price move, but the close is logged NET
of the round-trip fee + entry spread, so the knowledge graph learns fee-adjusted
expectancy. Scalp trades are tagged strategy "scalp_momentum" and never collide
with the swing "spot_momentum" bot — each manages only its own positions, and a
pair already held by either is skipped.

NOTE: a 60s cycle cannot enforce a 1% stop tick-by-tick — between cycles price
can overshoot the level, so realized stops/targets carry slippage. That's an
accepted limit of polling (vs streaming) and is exactly why this stays paper
until the measured net expectancy says otherwise.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.bot.runner import apply_risk_caps
from src.config import BOT_TRADES_LOG, SCALP_PARAMS
from src.crypto import scalp
from src.crypto.universe import to_pair

STRATEGY = "scalp_momentum"


def _log(event: dict) -> None:
    row = {"ts": datetime.now(UTC).isoformat(), **event}
    with BOT_TRADES_LOG.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _open_scalp_plans() -> dict[str, dict]:
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


def _held_minutes(open_ts: str | None) -> float:
    if not open_ts:
        return 0.0
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(open_ts)).total_seconds() / 60
    except (ValueError, TypeError):
        return 0.0


def _daily_pl_pct(account: dict) -> float:
    try:
        eq, last = float(account["equity"]), float(account["last_equity"])
        return (eq - last) / last * 100 if last else 0.0
    except (KeyError, ValueError, TypeError):
        return 0.0


def manage_exits(client, params: dict) -> list[dict]:
    """Close scalp positions on gross TP/SL/time; log P&L NET of cost."""
    open_map = _open_scalp_plans()
    closed: list[dict] = []
    for pos in client.crypto_positions():
        pair = to_pair(pos.get("symbol", ""))
        op = open_map.get(pair)
        if not op:
            continue  # only manage scalp positions this bot opened
        ep = (op.get("plan") or {}).get("exit") or {}
        try:
            gross = float(pos.get("unrealized_plpc") or 0) * 100
        except (ValueError, TypeError):
            gross = 0.0

        reason = None
        if ep.get("tp_pct") and gross >= ep["tp_pct"]:
            reason = "tp"
        elif ep.get("sl_pct") and gross <= -ep["sl_pct"]:
            reason = "sl"
        elif _held_minutes(op.get("ts")) >= ep.get("time_stop_minutes", params["time_stop_minutes"]):
            reason = "time_stop"
        if not reason:
            continue

        net = round(gross - (ep.get("cost_pct") or 0), 3)
        try:
            client.close_position(pair)
            _log({"event": "close", "symbol": pair, "ticker": pair, "reason": reason,
                  "plpc": net, "gross_pct": round(gross, 3), "cost_pct": ep.get("cost_pct")})
            closed.append({"symbol": pair, "reason": reason, "net_pct": net, "gross_pct": round(gross, 3)})
        except Exception as e:  # noqa: BLE001 - log + continue, never abort the loop
            _log({"event": "close_error", "symbol": pair, "error": str(e)})
    return closed


def _build_plans(client, equity: float, params: dict, skip_pairs: set[str]) -> list[dict]:
    from src.graph.build import build as build_graph
    from src.graph.feedback import learned_multiplier

    graph, _ = build_graph()
    signals = scalp.scan_scalp(client, params)
    ranked: list[tuple[float, dict]] = []
    for sig in signals:
        pair = sig["ticker"]
        if pair in skip_pairs:
            continue
        adj = sig["score"] * learned_multiplier(graph, sig["flags"])
        if adj < params["min_score"]:
            continue
        ranked.append((adj, sig))
    ranked.sort(key=lambda x: x[0], reverse=True)

    plans: list[dict] = []
    for adj, sig in ranked:
        p = scalp.build_scalp_plan(sig["ticker"], sig, sig["quote"], equity, params)
        if p:
            p["adj_score"] = round(adj, 1)
            plans.append(p)
    return plans


def run(execute: bool = False, params: dict | None = None) -> dict[str, Any]:
    params = params or SCALP_PARAMS
    from src.bot.alpaca import AlpacaClient

    client = AlpacaClient()  # paper-guarded; also our market-data client

    if not execute:
        equity = params["default_equity"]
        plans = _build_plans(client, equity, params, skip_pairs=set())
        kept, dropped, deployed = apply_risk_caps(plans, equity, params, 0)
        return {"mode": "dry_run", "equity": equity, "candidates": len(plans),
                "selected": kept, "dropped": dropped, "deployed_usd": deployed}

    account = client.account()
    equity = float(account.get("equity") or params["default_equity"])
    pl_pct = _daily_pl_pct(account)

    if pl_pct <= -params["max_daily_loss_pct"]:
        _log({"event": "kill_switch", "scope": "scalp", "daily_pl_pct": round(pl_pct, 2)})
        closed = manage_exits(client, params)
        return {"mode": "halted", "reason": "daily_loss_limit",
                "daily_pl_pct": round(pl_pct, 2), "closed": closed}

    closed = manage_exits(client, params)

    positions = client.crypto_positions()
    held_pairs = {to_pair(p["symbol"]) for p in positions}
    scalp_held = held_pairs & set(_open_scalp_plans().keys())
    if len(scalp_held) >= params["max_open_positions"]:
        return {"mode": "executed", "asset": "crypto_scalp", "equity": equity,
                "daily_pl_pct": round(pl_pct, 2), "closed": closed, "placed": [], "errors": [],
                "note": "max scalp positions held — managed exits only"}

    plans = _build_plans(client, equity, params, skip_pairs=held_pairs)
    kept, _dropped, _deployed = apply_risk_caps(plans, equity, params, len(scalp_held))

    placed: list[dict] = []
    errors: list[dict] = []
    for p in kept:
        try:
            order = client.submit_crypto(p["ticker"], p["notional"], side="buy")
            _log({"event": "open", "ticker": p["ticker"], "symbol": p["ticker"],
                  "notional": p["notional"], "order_id": order.get("id"), "plan": p})
            placed.append({"ticker": p["ticker"], "notional": p["notional"],
                           "score": p["setup_score"], "breakeven_wr": p["exit"]["breakeven_wr"]})
        except Exception as e:  # noqa: BLE001 - log + continue to the next plan
            _log({"event": "open_error", "ticker": p["ticker"], "error": str(e)})
            errors.append({"ticker": p["ticker"], "error": str(e)})

    return {"mode": "executed", "asset": "crypto_scalp", "equity": equity,
            "daily_pl_pct": round(pl_pct, 2), "closed": closed, "placed": placed, "errors": errors}
