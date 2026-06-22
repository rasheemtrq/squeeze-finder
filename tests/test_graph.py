"""Trade knowledge graph: rollups, trade pairing, gated insights + feedback."""
import json

from src.graph import build as build_mod
from src.graph.feedback import learned_multiplier
from src.graph.insights import rank_signals
from src.graph.model import KnowledgeGraph


def test_add_trade_rollups():
    g = KnowledgeGraph()
    g.add_trade([("signal:hot", "signal", "hot"), ("ticker:AAA", "ticker", "AAA")], won=True, r=2.0, plpc=100)
    g.add_trade([("signal:hot", "signal", "hot"), ("ticker:BBB", "ticker", "BBB")], won=False, r=-1.0, plpc=-50)
    n = g.nodes["signal:hot"]
    assert n.n == 2 and n.wins == 1
    assert abs(n.avg_r - 0.5) < 1e-9 and abs(n.win_rate - 0.5) < 1e-9
    assert g.n_trades == 2


def test_co_occurrence_edge():
    g = KnowledgeGraph()
    g.add_trade([("signal:a", "signal", "a"), ("signal:b", "signal", "b")], won=True, r=3.0, plpc=150)
    assert g.edges["signal:a|signal:b"].n == 1
    assert abs(g.edges["signal:a|signal:b"].avg_r - 3.0) < 1e-9


def test_build_pairs_open_close(tmp_path):
    log = tmp_path / "bot_trades.jsonl"
    rows = [
        {"event": "open", "symbol": "AAA250101C00100000", "ticker": "AAA",
         "plan": {"ticker": "AAA", "strategy": "long_call", "flags": ["si:high_settlement_pressure"],
                  "contract": {"dte": 24, "delta": 0.34}, "exit": {"sl_pct": 50}}},
        {"event": "close", "symbol": "AAA250101C00100000", "plpc": 100, "reason": "tp"},
        {"event": "open", "symbol": "BBB250101C00050000", "ticker": "BBB",
         "plan": {"ticker": "BBB", "strategy": "long_call", "flags": ["si:high_settlement_pressure"],
                  "contract": {"dte": 30, "delta": 0.4}, "exit": {"sl_pct": 50}}},
        {"event": "close", "symbol": "BBB250101C00050000", "plpc": -50, "reason": "sl"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows))
    g, counts = build_mod.build(trades_path=log)
    assert counts["bot_trades"] == 2 and g.n_trades == 2
    sig = g.nodes["signal:si:high_settlement_pressure"]
    assert sig.n == 2 and sig.wins == 1
    assert abs(sig.avg_r - 0.5) < 1e-9  # (+2R, −1R) / 2


def test_build_ignores_unpaired_open(tmp_path):
    log = tmp_path / "t.jsonl"
    log.write_text(json.dumps({"event": "open", "symbol": "X", "ticker": "X", "plan": {"flags": ["a"]}}))
    g, _ = build_mod.build(trades_path=log)
    assert g.n_trades == 0  # still open, no outcome


def test_insights_sample_size_gating():
    g = KnowledgeGraph()
    for _ in range(10):
        g.add_trade([("signal:good", "signal", "good")], won=True, r=2.0, plpc=100)
    for _ in range(3):
        g.add_trade([("signal:thin", "signal", "thin")], won=True, r=5.0, plpc=200)
    labels = [r["signal"] for r in rank_signals(g, min_trades=8)["best"]]
    assert "good" in labels      # 10 trades → actionable
    assert "thin" not in labels  # 3 trades → gated out as noise


def test_feedback_neutral_then_biases():
    g = KnowledgeGraph()
    assert learned_multiplier(g, ["unknown"]) == 1.0
    assert learned_multiplier(None, ["x"]) == 1.0
    for _ in range(3):
        g.add_trade([("signal:thin", "signal", "thin")], won=True, r=2.0, plpc=100)
    assert learned_multiplier(g, ["thin"]) == 1.0  # thin → still neutral
    for _ in range(10):
        g.add_trade([("signal:win", "signal", "win")], won=True, r=2.0, plpc=100)
    assert 1.0 < learned_multiplier(g, ["win"]) <= 1.4  # learned winner → gentle boost
    for _ in range(10):
        g.add_trade([("signal:lose", "signal", "lose")], won=False, r=-1.0, plpc=-50)
    assert learned_multiplier(g, ["lose"]) < 1.0       # learned loser → demote


def test_save_load_roundtrip(tmp_path):
    g = KnowledgeGraph()
    g.add_trade([("signal:a", "signal", "a"), ("signal:b", "signal", "b")], won=True, r=2.0, plpc=100)
    p = tmp_path / "g.json"
    g.save(p)
    g2 = KnowledgeGraph.load(p)
    assert g2.n_trades == 1 and g2.nodes["signal:a"].n == 1 and "signal:a|signal:b" in g2.edges
