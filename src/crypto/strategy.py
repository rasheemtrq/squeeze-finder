"""
Crypto strategy selector — momentum setup → concrete spot trade plan.

Spot crypto is plain long exposure, so the play is a **risk-normalized spot
buy**: size the dollar notional so that if price falls to the ATR/volume stop,
the loss equals `risk_pct_per_trade` of equity. Position size therefore scales
inversely with stop distance — a tight-stop setup earns more notional for the
same dollar risk — capped per-name by `max_position_pct`. Exits are the level's
take-profit / stop (price-based) plus a holding-time stop.

Pure orchestration over the scanner + chart levels — never places an order.
The runner is the only thing that talks to a broker.
"""
from __future__ import annotations

from typing import Any


def size_notional(
    equity: float, risk_pct_per_trade: float, stop_pct: float, max_position_pct: float
) -> float:
    """Dollar notional whose loss-at-stop equals risk_pct_per_trade of equity.

    notional = risk_budget / stop_fraction, capped at the per-name limit. Returns
    0 when the stop distance is non-positive (degenerate levels) — skip the trade.
    """
    if stop_pct <= 0 or equity <= 0:
        return 0.0
    risk_budget = equity * risk_pct_per_trade / 100.0
    notional = risk_budget / (stop_pct / 100.0)
    cap = equity * max_position_pct / 100.0
    return round(min(notional, cap), 2)


def plan_for_setup(
    setup: dict[str, Any], equity: float, params: dict[str, Any]
) -> dict[str, Any] | None:
    """Spot-long plan for one scanned coin, or None if it can't be sized."""
    levels = setup.get("levels") or {}
    stop_pct = levels.get("risk_pct") or 0
    notional = size_notional(
        equity, params["risk_pct_per_trade"], stop_pct, params["max_position_pct"]
    )
    if notional < params["min_notional"]:
        return None

    entry = levels.get("entry") or setup.get("price")
    return {
        "ticker": setup["ticker"],                 # 'BTC/USD'
        "yf_symbol": setup.get("yf_symbol"),
        "setup_score": setup.get("score"),
        "flags": setup.get("flags") or [],
        "strategy": "spot_momentum",
        "notional": notional,
        "est_cost": notional,                      # spot: full notional is deployed
        "risk_usd": round(notional * stop_pct / 100.0, 2),  # $ lost if stop hits
        "underlying": {
            "entry": entry,
            "stop": levels.get("stop"),
            "tp": levels.get("tp"),
            "rr": levels.get("rr"),
        },
        "exit": {
            # sl_pct is the stop distance % — the graph reads this to express
            # outcomes in R (R = realized% / sl_pct). tp_pct is the target's %.
            "sl_pct": round(stop_pct, 2),
            "tp_pct": levels.get("tp_pct"),
            "time_stop_days": params["time_stop_days"],
        },
        "factors": setup.get("factors"),
    }


def build_plans(
    setups: list[dict],
    equity: float,
    params: dict[str, Any],
    skip_pairs: set[str] | None = None,
    graph: Any = None,
) -> list[dict[str, Any]]:
    """Plans for every setup at/above the score floor, skipping coins already held.

    Like the options bot, a supplied knowledge `graph` nudges each setup's score
    by its learned signal expectancy (gated — neutral until signals have enough
    trades) and re-ranks, so the bot leans toward patterns that have worked.
    """
    from src.graph.feedback import learned_multiplier

    skip = skip_pairs or set()
    ranked: list[tuple[float, float, dict]] = []
    for s in setups:
        t = s.get("ticker")
        if not t or t in skip:
            continue
        base = s.get("score") or 0
        mult = learned_multiplier(graph, s.get("flags"))
        adj = base * mult
        if adj < params["min_setup_score"]:
            continue
        ranked.append((adj, mult, s))

    ranked.sort(key=lambda x: x[0], reverse=True)

    plans: list[dict[str, Any]] = []
    for adj, mult, s in ranked:
        try:
            p = plan_for_setup(s, equity, params)
        except Exception:
            p = None
        if p:
            p["learned_multiplier"] = round(mult, 3)
            p["adj_score"] = round(adj, 1)
            plans.append(p)
    return plans
