"""
Bot strategy selector — scanner setup → concrete options trade plan.

Reuses the existing options recommender (already delta/OI/DTE-filtered and
ranked) and the ATR/volume chart levels. No new strategy math. For a bullish
squeeze/momentum setup the play is a defined-risk LONG CALL: max loss is the
premium, so we size the premium risked to at most `risk_pct_per_trade` of
equity. Exits are +TP% / −SL% on the option premium plus a DTE time stop to
dodge the theta cliff.

Pure orchestration over recommend() / compute_chart_levels() — never places an
order. The runner is the only thing that talks to a broker.
"""
from __future__ import annotations

from typing import Any

from src.data import prices as prices_data
from src.options.recommender import recommend
from src.score.levels import compute_chart_levels


def occ_symbol(ticker: str, expiry: str, opt_type: str, strike: float) -> str:
    """OCC option symbol for display, e.g. AAPL250620C00200000."""
    y, m, d = expiry.split("-")
    cp = "C" if opt_type.lower().startswith("c") else "P"
    return f"{ticker.upper()}{y[2:]}{m}{d}{cp}{int(round(strike * 1000)):08d}"


def size_contracts(cost_per_contract: float, equity: float, risk_pct: float) -> int:
    """Defined-risk sizing: premium per contract is the max loss, so the number
    of contracts is the risk budget // premium. 0 means a single contract costs
    more than the budget allows — skip the trade."""
    if cost_per_contract <= 0 or equity <= 0:
        return 0
    risk_budget = equity * risk_pct / 100.0
    return int(risk_budget // cost_per_contract)


def plan_for_ticker(
    ticker: str,
    equity: float,
    params: dict[str, Any],
    score: float | None = None,
    pressure: float | None = None,
    flags: list[str] | None = None,
) -> dict[str, Any] | None:
    """Long-call options plan for one ticker, or None if no tradable contract fits."""
    recs = recommend(ticker, top_n=5)
    contracts = recs.get("recommendations") or []
    if not contracts:
        return None
    c = contracts[0]  # top-ranked by the recommender
    mid = c.get("mid") or 0
    cost = c.get("cost_per_contract") or mid * 100
    if cost <= 0:
        return None

    qty = size_contracts(cost, equity, params["risk_pct_per_trade"])
    if qty < 1:
        return None  # one contract exceeds the risk budget

    levels = None
    try:
        levels = compute_chart_levels(prices_data.fetch(ticker, period="3mo")["bars"])
    except Exception:
        levels = None

    tp_pct = params["option_tp_pct"]
    sl_pct = params["option_sl_pct"]
    return {
        "ticker": ticker,
        "setup_score": score,
        "pressure": pressure,
        "flags": flags or [],
        "strategy": "long_call",
        "contract": {
            "occ_symbol": occ_symbol(ticker, c["expiry"], "call", c["strike"]),
            "strike": c["strike"],
            "expiry": c["expiry"],
            "dte": c.get("dte"),
            "mid": mid,
            "delta": c.get("delta"),
            "iv": c.get("iv"),
            "open_interest": c.get("open_interest"),
            "cost_per_contract": round(cost, 2),
            "breakeven": c.get("breakeven"),
        },
        "qty": qty,
        "est_cost": round(qty * cost, 2),
        "risk_usd": round(qty * cost, 2),  # defined risk = total premium paid
        "underlying": {
            "entry": (levels or {}).get("entry") or recs.get("spot"),
            "stop": (levels or {}).get("stop"),
            "tp": (levels or {}).get("tp"),
            "rr": (levels or {}).get("rr"),
        },
        "exit": {
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "tp_price": round(mid * (1 + tp_pct / 100), 2),
            "sl_price": round(mid * (1 - sl_pct / 100), 2),
            "time_stop_dte": params["time_stop_dte"],
        },
        "rationale": c.get("rationale"),
    }


def build_plans(
    setups: list[dict],
    equity: float,
    params: dict[str, Any],
    skip_tickers: set[str] | None = None,
    graph: Any = None,
) -> list[dict[str, Any]]:
    """Plans for every setup at/above the score floor, skipping names already held.

    When a knowledge `graph` is supplied, each setup's score is nudged by the
    graph's learned signal expectancy (gated — neutral until signals have enough
    trades) and the list is re-ranked by the adjusted score, so the bot leans
    toward signal patterns that have actually worked.
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
            p = plan_for_ticker(
                s["ticker"], equity, params,
                score=s.get("score"),
                pressure=(s.get("pressure_score") or {}).get("score"),
                flags=s.get("flags"),
            )
        except Exception:
            p = None
        if p:
            p["learned_multiplier"] = round(mult, 3)
            p["adj_score"] = round(adj, 1)
            plans.append(p)
    return plans
