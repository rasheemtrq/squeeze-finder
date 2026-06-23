"""
Swing-share strategy — swing-scan setup → concrete share trade plan.

The swing scanner already attaches a full `trade_plan` to each setup (entry,
ATR/structural stop, 2R/3R targets, risk-normalized position size). This turns
that into a spot-share order plan: buy a dollar notional sized so a hit to the
stop loses `risk_pct_per_trade` of equity, take profit at the first (2R) target,
hard stop at the plan stop, and a holding-time cap. Shares are plain long
exposure, so risk is defined (max loss = stop distance × notional).

Pure orchestration over the scanner output — never places an order.
"""
from __future__ import annotations

from typing import Any


def plan_for_setup(
    setup: dict[str, Any], equity: float, params: dict[str, Any]
) -> dict[str, Any] | None:
    """Share plan for one swing setup, or None if it has no usable trade plan."""
    tp = setup.get("trade_plan")
    if not tp:
        return None
    entry = tp.get("entry")
    stop_pct = tp.get("risk_pct") or 0
    if not entry or entry <= 0 or stop_pct <= 0:
        return None

    targets = tp.get("targets") or []
    target = targets[0] if targets else round(entry * (1 + 2 * stop_pct / 100), 4)
    tp_pct = (target / entry - 1) * 100

    # trade_plan.position_pct is already risk-normalized at its account_risk_pct
    # (default 1%). Scale to our configured risk and cap per-name.
    base_risk = tp.get("account_risk_pct") or 1.0
    pos_pct = (tp.get("position_pct") or (1.0 / (stop_pct / 100))) * (
        params["risk_pct_per_trade"] / base_risk
    )
    notional = round(min(equity * pos_pct / 100, equity * params["max_position_pct"] / 100), 2)
    if notional < params["min_notional"]:
        return None

    return {
        "ticker": setup["ticker"],
        "setup_score": setup.get("score"),
        "flags": setup.get("flags") or [],
        "strategy": "swing_shares",
        "notional": notional,
        "est_cost": notional,
        "risk_usd": round(notional * stop_pct / 100, 2),
        "underlying": {
            "entry": entry,
            "stop": tp.get("stop"),
            "tp": target,
            "rr": round(tp_pct / stop_pct, 2) if stop_pct else None,
        },
        "exit": {
            "sl_pct": round(stop_pct, 2),     # graph reads this for R
            "tp_pct": round(tp_pct, 2),
            "time_stop_days": params["time_stop_days"],
        },
        "trade_plan": tp,
    }


def build_plans(
    setups: list[dict],
    equity: float,
    params: dict[str, Any],
    skip_tickers: set[str] | None = None,
    graph: Any = None,
) -> list[dict[str, Any]]:
    """Plans for setups at/above the score floor, skipping names already held.

    A supplied knowledge `graph` nudges each setup's score by its learned signal
    expectancy (gated — neutral until signals have enough trades) and re-ranks.
    """
    from src.graph.feedback import learned_multiplier

    skip = skip_tickers or set()
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
