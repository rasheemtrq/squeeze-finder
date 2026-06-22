"""
Close the loop: turn the graph's learned signal expectancy into a gentle score
multiplier the bot applies when picking setups.

Safety by construction:
- Only signals with >= MIN_TRADES count; thin/unknown signals contribute nothing.
- Returns exactly 1.0 when nothing has been learned yet — so on an empty or
  small graph the bot behaves identically to no feedback (no overfitting).
- The adjustment is gentle and clamped, so even a strong learned edge nudges
  rather than dominates the rank.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.graph.insights import MIN_TRADES

if TYPE_CHECKING:
    from src.graph.model import KnowledgeGraph

STRENGTH = 0.15  # +1R avg expectancy -> +15% score nudge
LO, HI = 0.6, 1.4


def learned_multiplier(
    graph: KnowledgeGraph | None,
    flags: list[str] | None,
    min_trades: int = MIN_TRADES,
) -> float:
    if not graph or not flags:
        return 1.0
    contribs = []
    for fl in flags:
        node = graph.nodes.get(f"signal:{fl}")
        if node and node.n >= min_trades:
            contribs.append(node.avg_r)
    if not contribs:
        return 1.0  # nothing learned for these signals yet — stay neutral
    mean_r = sum(contribs) / len(contribs)
    return max(LO, min(HI, 1.0 + STRENGTH * mean_r))
