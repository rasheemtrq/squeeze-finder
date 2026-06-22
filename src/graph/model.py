"""
Trade knowledge graph — nodes/edges with outcome rollups.

Each completed trade contributes a set of *attribute* nodes (the signals/flags
that fired, the ticker, the strategy, DTE/delta buckets) and an *outcome*
(win, realized R, P&L %). Every attribute node accumulates the outcomes of the
trades it appeared in, so a node's expectancy = "how trades with this attribute
have actually done." Co-occurrence edges accumulate the joint outcome of two
attributes together — that's how the graph surfaces winning/losing *combinations*,
not just single signals.

Persisted as plain JSON (data/graph.json) so it's inspectable and viz-ready
(nodes + edges). Stats are descriptive; the bot only acts on a node once it has
enough trades to be meaningful (see insights/feedback) — small samples are noise.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Node:
    id: str            # e.g. "signal:si:high_settlement_pressure"
    type: str          # signal | ticker | strategy | dte_bucket | delta_bucket
    label: str
    n: int = 0         # trades touching this node
    wins: int = 0
    sum_r: float = 0.0     # sum of realized R
    sum_plpc: float = 0.0  # sum of P&L %

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0

    @property
    def avg_r(self) -> float:
        return self.sum_r / self.n if self.n else 0.0

    @property
    def avg_plpc(self) -> float:
        return self.sum_plpc / self.n if self.n else 0.0


@dataclass
class Edge:
    source: str
    target: str
    type: str = "co_occurs"
    n: int = 0
    wins: int = 0
    sum_r: float = 0.0

    @property
    def avg_r(self) -> float:
        return self.sum_r / self.n if self.n else 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0


@dataclass
class KnowledgeGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)  # key "src|tgt"
    n_trades: int = 0

    def _node(self, node_id: str, ntype: str, label: str) -> Node:
        if node_id not in self.nodes:
            self.nodes[node_id] = Node(id=node_id, type=ntype, label=label)
        return self.nodes[node_id]

    def _edge(self, a: str, b: str) -> Edge:
        src, tgt = sorted((a, b))  # undirected co-occurrence
        key = f"{src}|{tgt}"
        if key not in self.edges:
            self.edges[key] = Edge(source=src, target=tgt)
        return self.edges[key]

    def add_trade(self, attributes: list[tuple[str, str, str]], won: bool, r: float, plpc: float) -> None:
        """attributes = list of (node_id, type, label). Outcome applied to each + every pair."""
        self.n_trades += 1
        ids: list[str] = []
        for node_id, ntype, label in attributes:
            node = self._node(node_id, ntype, label)
            node.n += 1
            node.wins += 1 if won else 0
            node.sum_r += r
            node.sum_plpc += plpc
            ids.append(node_id)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                e = self._edge(ids[i], ids[j])
                e.n += 1
                e.wins += 1 if won else 0
                e.sum_r += r

    # ---- persistence
    def to_dict(self) -> dict[str, Any]:
        return {
            "n_trades": self.n_trades,
            "nodes": [
                {**asdict(n), "win_rate": round(n.win_rate, 3), "avg_r": round(n.avg_r, 3),
                 "avg_plpc": round(n.avg_plpc, 2)}
                for n in self.nodes.values()
            ],
            "edges": [
                {**asdict(e), "avg_r": round(e.avg_r, 3), "win_rate": round(e.win_rate, 3)}
                for e in self.edges.values()
            ],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> KnowledgeGraph:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        g = cls(n_trades=data.get("n_trades", 0))
        for nd in data.get("nodes", []):
            g.nodes[nd["id"]] = Node(
                id=nd["id"], type=nd["type"], label=nd["label"], n=nd.get("n", 0),
                wins=nd.get("wins", 0), sum_r=nd.get("sum_r", 0.0), sum_plpc=nd.get("sum_plpc", 0.0),
            )
        for ed in data.get("edges", []):
            key = f"{ed['source']}|{ed['target']}"
            g.edges[key] = Edge(
                source=ed["source"], target=ed["target"], type=ed.get("type", "co_occurs"),
                n=ed.get("n", 0), wins=ed.get("wins", 0), sum_r=ed.get("sum_r", 0.0),
            )
        return g
