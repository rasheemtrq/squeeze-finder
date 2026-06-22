"""
Build the trade knowledge graph from logged outcomes.

Primary source: the bot's own trade log (data/bot_trades.jsonl) — each "open"
event carries the plan (flags, contract, strategy); the matching "close" carries
the realized P&L. We pair them into completed trades. Outcome is expressed in R
(R = plpc / planned-stop%, so −50% = −1R, +100% = +2R) for consistency.

Optional seed: the accrual snapshots (data/screens/swing_*.jsonl) replayed
through the swing backtest — virtual trades (signals → realized R) that give the
graph data before the bot has logged many real trades. Off by default (it walks
prices per snapshot); enable with seed_snapshots=True.

Both sources are empty until outcomes have *aged* — that's expected; the graph
fills in as trades accrue.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.config import BOT_TRADES_LOG
from src.graph.model import KnowledgeGraph

if TYPE_CHECKING:
    from pathlib import Path


def _dte_bucket(dte: int | None) -> str | None:
    if dte is None:
        return None
    if dte <= 7:
        return "0-7d"
    if dte <= 21:
        return "8-21d"
    if dte <= 45:
        return "22-45d"
    return "46d+"


def _delta_bucket(delta: float | None) -> str | None:
    if delta is None:
        return None
    d = abs(delta)
    if d < 0.30:
        return "Δ0.1-0.3"
    if d < 0.50:
        return "Δ0.3-0.5"
    return "Δ0.5+"


def _attributes(flags, ticker, strategy=None, dte=None, delta=None):
    attrs: list[tuple[str, str, str]] = []
    if ticker:
        attrs.append((f"ticker:{ticker}", "ticker", ticker))
    for fl in flags or []:
        attrs.append((f"signal:{fl}", "signal", fl))
    if strategy:
        attrs.append((f"strategy:{strategy}", "strategy", strategy))
    b = _dte_bucket(dte)
    if b:
        attrs.append((f"dte:{b}", "dte_bucket", b))
    b = _delta_bucket(delta)
    if b:
        attrs.append((f"delta:{b}", "delta_bucket", b))
    return attrs


def _ingest_trades(g: KnowledgeGraph, path: Path) -> int:
    if not path.exists():
        return 0
    opens: dict[str, dict] = {}
    n = 0
    for line in path.read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") == "open":
            opens[ev.get("symbol")] = ev
        elif ev.get("event") == "close":
            op = opens.pop(ev.get("symbol"), None)
            if not op:
                continue
            plan = op.get("plan") or {}
            plpc = float(ev.get("plpc") or 0)
            sl_pct = (plan.get("exit") or {}).get("sl_pct") or 50
            r = plpc / sl_pct if sl_pct else 0.0
            c = plan.get("contract") or {}
            attrs = _attributes(
                plan.get("flags"), op.get("ticker") or plan.get("ticker"),
                strategy=plan.get("strategy"), dte=c.get("dte"), delta=c.get("delta"),
            )
            g.add_trade(attrs, won=plpc > 0, r=r, plpc=plpc)
            n += 1
    return n


def _ingest_snapshots(g: KnowledgeGraph, window_days: int = 14) -> int:
    from datetime import date

    from src.score.swing_backtest import _forward_path, _iter_snapshots, simulate_trade

    n = 0
    for snap in _iter_snapshots(min_age_days=window_days):
        try:
            scan_d = date.fromisoformat(snap["scan_date"])
            fp = _forward_path(snap["ticker"], scan_d, window_days)
        except Exception:
            fp = None
        if not fp:
            continue
        sim = simulate_trade(fp["entry_close"], snap.get("trade_plan"), fp["forward"])
        final = sim["final_return_pct"]
        r = sim["realized_r"] if sim.get("realized_r") is not None else final / 10.0
        attrs = _attributes(snap.get("flags"), snap["ticker"], strategy="swing_underlying")
        g.add_trade(attrs, won=final > 0, r=r, plpc=final)
        n += 1
    return n


def build(
    trades_path: Path = BOT_TRADES_LOG,
    seed_snapshots: bool = False,
    window_days: int = 14,
) -> tuple[KnowledgeGraph, dict]:
    """Build the graph; returns (graph, source_counts)."""
    g = KnowledgeGraph()
    n_trades = _ingest_trades(g, trades_path)
    n_snap = _ingest_snapshots(g, window_days) if seed_snapshots else 0
    return g, {"bot_trades": n_trades, "snapshot_trades": n_snap}


def demo_graph() -> KnowledgeGraph:
    """Synthetic graph for previewing the brain UI before real trades accrue.

    Clearly-labeled sample data (not real trades) so the visualization has
    something to render and the shape of "what the bot learns" is legible.
    """
    g = KnowledgeGraph()
    # (signal combo, list of realized-R outcomes) — hand-picked to show edge
    plays = [
        (["si:high_settlement_pressure", "sentiment:convergent_bullish"],
         [2.1, 1.4, -1, 1.8, 0.6, 2.4, -1, 1.2, 0.9, -1, 1.6, 2.0]),
        (["sentiment:wsb_surge", "si:shorts_piling_in"],
         [2.6, -1, 1.9, 3.0, -1, 1.2, 2.2, -1, 1.5, 2.8]),
        (["ta:breakout_highvol"], [1.2, -1, 0.8, 1.5, -1, 2.0, 0.4, 1.1, -1]),
        (["ta:breakout_lowvol"], [-1, -1, 0.4, -1, 0.6, -1, -1, 0.2, -1]),
        (["options:untradable_chain"], [-1, -0.6, -1, -1, 0.3, -1, -1, -1]),
        (["si:institutional_lockup", "sentiment:hot"],
         [1.8, 2.2, -1, 1.4, 1.0, -1, 2.6, 0.8, 1.6, -1, 1.2]),
        (["si:insiders_dumping"], [-1, -1, 0.2, -1, -1, -1, -0.8, -1]),
    ]
    tickers = ["NBIS", "ASTS", "GME", "BBAI", "HIMS", "QS", "MU", "IREN"]
    ti = 0
    for flags, outcomes in plays:
        for r in outcomes:
            attrs = _attributes(flags, tickers[ti % len(tickers)], strategy="long_call", dte=24, delta=0.34)
            g.add_trade(attrs, won=r > 0, r=r, plpc=r * 50)
            ti += 1
    return g
