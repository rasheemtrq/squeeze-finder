"""Unit tests for swing forward-return + expectancy simulation."""
import json
from datetime import UTC, datetime, timedelta

from src.score import swing_backtest as sb

PLAN = {
    "entry": 100.0,
    "stop": 95.0,                 # risk_frac = 5%
    "targets": [110.0, 115.0],    # 2R, 3R
    "target_r_multiples": [2.0, 3.0],
    "risk_pct": 5.0,
    "grade": "ok",
}


def _bar(d: str, o: float, h: float, lo: float, c: float) -> dict:
    return {"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": 1}


def test_simulate_stop_first():
    fwd = [_bar("2025-02-03", 100, 101, 94, 96)]  # low 94 ≤ 95
    sim = sb.simulate_trade(100.0, PLAN, fwd)
    assert sim["outcome"] == "stop"
    assert sim["realized_r"] == -1.0
    assert sim["exit_return_pct"] == -5.0


def test_simulate_target_first():
    fwd = [_bar("2025-02-03", 100, 108, 99, 107), _bar("2025-02-04", 107, 111, 106, 110)]
    sim = sb.simulate_trade(100.0, PLAN, fwd)
    assert sim["outcome"] == "target"
    assert sim["realized_r"] == 2.0


def test_simulate_mark_to_market_when_neither_hit():
    fwd = [_bar("2025-02-03", 100, 104, 98, 103)]  # never 95, never 110
    sim = sb.simulate_trade(100.0, PLAN, fwd)
    assert sim["outcome"] == "open"
    # R = (103/100 − 1) / 0.05 = 0.6
    assert abs(sim["realized_r"] - 0.6) < 1e-9


def test_simulate_same_bar_prefers_stop():
    fwd = [_bar("2025-02-03", 100, 111, 94, 100)]  # straddles both → conservative stop
    sim = sb.simulate_trade(100.0, PLAN, fwd)
    assert sim["outcome"] == "stop"


def test_simulate_split_adjusted_levels():
    # entry_adj=200 (post 2:1). stop→190, target1→220. Levels track the entry.
    fwd = [_bar("2025-02-03", 200, 222, 205, 221)]
    sim = sb.simulate_trade(200.0, PLAN, fwd)
    assert sim["outcome"] == "target"


def test_simulate_no_plan_falls_back_to_buy_and_hold():
    fwd = [_bar("2025-02-03", 100, 104, 98, 102)]
    sim = sb.simulate_trade(100.0, None, fwd)
    assert sim["outcome"] == "no_plan"
    assert sim["realized_r"] is None
    assert sim["final_return_pct"] == 2.0


def test_record_and_evaluate_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "SCREEN_DIR", tmp_path)

    scan_d = datetime.now(UTC).date() - timedelta(days=30)
    row = {
        "scan_date": scan_d.isoformat(),
        "ticker": "TEST",
        "swing_score": 80.0,
        "factor_scores": {"stage2": 90, "breakout": 70, "rs": 60, "catalyst": 0, "smart_money": 0},
        "flags": ["stage2:new_52w_high", "risk:ok_stop"],
        "trade_plan": PLAN,
        "close_at_scan": 100.0,
    }
    (tmp_path / f"swing_{scan_d.isoformat()}.jsonl").write_text(json.dumps(row) + "\n")

    # Forward series: entry bar on scan day, then a rise that tags the 2R target.
    bars = [_bar(scan_d.isoformat(), 100, 101, 99, 100)]
    for k in range(1, 11):
        d = (scan_d + timedelta(days=k)).isoformat()
        px = 100 + k  # climbs to 110 → hits target1 (110)
        bars.append(_bar(d, px, px + 1, px - 1, px))
    monkeypatch.setattr(sb.prices, "fetch", lambda t, period="1y": {"bars": bars})

    res = sb.evaluate(window_days=14)
    assert res["evaluated"] == 1
    assert res["overall_expectancy"]["n_with_plan"] == 1
    assert res["overall_expectancy"]["expectancy_r"] == 2.0  # target hit
    assert res["underpowered"] is True  # one trade → honestly flagged


def test_evaluate_empty_is_honest():
    res = sb.evaluate(window_days=14)
    # With the real (near-empty) screen dir this must not raise and must note state.
    assert "note" in res
