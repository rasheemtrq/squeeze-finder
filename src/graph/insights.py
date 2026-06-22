"""
Read the graph: which signals (and signal combinations) actually have edge.

Everything here is sample-size gated by MIN_TRADES — a node's expectancy on a
handful of trades is noise, so we don't rank or act on it until it clears the
floor. Outcomes are in R (realized reward/risk).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graph.model import KnowledgeGraph

MIN_TRADES = 8  # below this, a node/edge's stats are noise


def _sig_row(n) -> dict:
    return {"signal": n.label, "n": n.n, "win_rate": round(n.win_rate, 3), "avg_r": round(n.avg_r, 3)}


def rank_signals(graph: KnowledgeGraph, min_trades: int = MIN_TRADES, top: int = 10) -> dict:
    sigs = sorted(
        (n for n in graph.nodes.values() if n.type == "signal" and n.n >= min_trades),
        key=lambda n: n.avg_r,
        reverse=True,
    )
    rows = [_sig_row(n) for n in sigs]
    return {"best": rows[:top], "worst": rows[-top:][::-1] if len(rows) > top else []}


def rank_combos(graph: KnowledgeGraph, min_trades: int = MIN_TRADES, top: int = 10) -> list[dict]:
    def is_sig(nid: str) -> bool:
        return nid.startswith("signal:")

    def lbl(nid: str) -> str:
        return graph.nodes[nid].label if nid in graph.nodes else nid

    edges = sorted(
        (e for e in graph.edges.values() if is_sig(e.source) and is_sig(e.target) and e.n >= min_trades),
        key=lambda e: e.avg_r,
        reverse=True,
    )
    return [
        {"combo": [lbl(e.source), lbl(e.target)], "n": e.n, "win_rate": round(e.win_rate, 3), "avg_r": round(e.avg_r, 3)}
        for e in edges[:top]
    ]


def summary(graph: KnowledgeGraph, min_trades: int = MIN_TRADES) -> dict:
    actionable = [n for n in graph.nodes.values() if n.type == "signal" and n.n >= min_trades]
    return {
        "n_trades": graph.n_trades,
        "n_nodes": len(graph.nodes),
        "n_edges": len(graph.edges),
        "signals_actionable": len(actionable),
        "min_trades": min_trades,
        "underpowered": graph.n_trades < min_trades * 3,
    }
