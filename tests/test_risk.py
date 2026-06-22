"""Unit tests for the ATR risk model + trade plan."""
from src.score import risk


def _flat_bars(n: int, close: float = 100.0, spread: float = 1.0) -> list[dict]:
    """n bars, flat close, constant high-low spread → constant ATR = 2·spread."""
    return [
        {
            "date": f"2025-01-{(i % 28) + 1:02d}",
            "open": close,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": 1_000_000,
        }
        for i in range(n)
    ]


def _prices(bars: list[dict]) -> dict:
    return {"bars": bars}


def test_atr_constant_true_range():
    # close flat at 100, high=101, low=99 → TR = max(2, 1, 1) = 2 every bar.
    assert abs(risk.atr(_flat_bars(30)) - 2.0) < 1e-9


def test_atr_insufficient_bars_returns_none():
    assert risk.atr(_flat_bars(5)) is None


def test_trade_plan_structural_stop_and_targets():
    plan = risk.build_trade_plan(_prices(_flat_bars(30)), account_risk_pct=1.0)
    assert plan is not None
    assert plan["entry"] == 100.0
    # swing low (last 10) = 99; structural = 99 − 0.25·2 = 98.5; gap 1.5 ≥ 0.5·ATR → kept.
    assert abs(plan["stop"] - 98.5) < 1e-9
    assert plan["stop_basis"] == "structural"
    assert abs(plan["risk_pct"] - 1.5) < 1e-6
    # targets at 2R/3R of 1.5 risk → 103.0, 104.5
    assert plan["targets"] == [103.0, 104.5]
    assert plan["grade"] == "tight"


def test_position_size_scales_inverse_to_risk_and_caps():
    plan = risk.build_trade_plan(_prices(_flat_bars(30)), account_risk_pct=1.0)
    # 1% account risk / 1.5% per-share risk = 66.7% → capped at MAX_POSITION_PCT.
    assert plan["position_pct"] == risk.MAX_POSITION_PCT
    assert plan["position_capped"] is True


def test_wide_stop_is_graded_and_penalized():
    bars = _flat_bars(30)
    bars[-3]["low"] = 80.0  # a deep recent low forces a wide structural stop
    plan = risk.build_trade_plan(_prices(bars))
    assert plan["grade"] == "wide"
    assert plan["risk_pct"] > risk.WIDE_STOP_RISK_PCT
    assert risk.risk_quality_multiplier(plan) == 0.85


def test_risk_quality_multiplier_bands():
    assert risk.risk_quality_multiplier({"grade": "tight"}) == 1.06
    assert risk.risk_quality_multiplier({"grade": "ok"}) == 1.0
    assert risk.risk_quality_multiplier({"grade": "wide"}) == 0.85
    assert risk.risk_quality_multiplier(None) == 1.0


def test_trade_plan_none_on_short_history():
    assert risk.build_trade_plan(_prices(_flat_bars(5))) is None
    assert risk.build_trade_plan({"bars": []}) is None
    assert risk.build_trade_plan(None) is None
