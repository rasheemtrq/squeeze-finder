"""Unit tests for swing factor scoring."""
from src.score import swing_factors as sf


def _bars_from_closes(closes: list[float], spread_pct: float = 0.01) -> list[dict]:
    bars = []
    for i, c in enumerate(closes):
        bars.append({
            "date": f"2024-{(i // 28) % 12 + 1:02d}-{(i % 28) + 1:02d}",
            "open": c,
            "high": c * (1 + spread_pct),
            "low": c * (1 - spread_pct),
            "close": c,
            "volume": 1_000_000,
        })
    return bars


def test_stage2_strong_uptrend_scores_high():
    # 240-bar steady uptrend ending at its 52-week high.
    closes = [50 + i * 0.4 for i in range(240)]
    score, sig = sf.score_stage2({"bars": _bars_from_closes(closes)})
    assert score >= 70
    assert sig["golden_cross"] is True
    assert sig["ema50_rising"] is True
    assert sig["pct_of_52w_high"] >= 95
    assert sig["flag"] in ("stage2_clean", "new_52w_high")


def test_stage2_downtrend_scores_low():
    closes = [200 - i * 0.4 for i in range(240)]
    score, sig = sf.score_stage2({"bars": _bars_from_closes(closes)})
    assert score <= 35
    assert sig["golden_cross"] is False
    assert sig["flag"] == "stage1_or_4"


def test_stage2_insufficient_history():
    score, sig = sf.score_stage2({"bars": _bars_from_closes([100] * 100)})
    assert score == 0.0
    assert sig["reason"] == "insufficient_history"


def test_stage2_mid_range_loses_52w_high_points():
    # Uptrend then a 20% pullback → still golden but far from highs.
    closes = [50 + i * 0.4 for i in range(220)] + [(50 + 219 * 0.4) * 0.8] * 20
    score, sig = sf.score_stage2({"bars": _bars_from_closes(closes)})
    assert sig["pct_of_52w_high"] < 85  # docked the proximity component


def test_relative_strength_outperformer():
    ticker = _bars_from_closes([100 + i * 0.5 for i in range(140)])   # +~0.5/day
    spy = _bars_from_closes([400 + i * 0.1 for i in range(140)])      # +~0.1/day
    score, sig = sf.score_relative_strength({"bars": ticker}, {"bars": spy})
    assert score > 0
    assert sig["rs_3m_pp"] > 0
    assert sig["flag"] in ("rs_leader", "rs_positive")


def test_relative_strength_laggard():
    ticker = _bars_from_closes([200 - i * 0.3 for i in range(140)])
    spy = _bars_from_closes([400 + i * 0.2 for i in range(140)])
    score, sig = sf.score_relative_strength({"bars": ticker}, {"bars": spy})
    assert sig["rs_3m_pp"] < 0


def test_breakout_on_high_volume():
    closes = [100.0] * 79 + [108.0]  # tight base then a pop above the 60d high
    bars = _bars_from_closes(closes)
    bars[-1]["volume"] = 5_000_000   # ~5x the 1M base → rvol high
    score, sig = sf.score_breakout_volume({"bars": bars})
    assert sig["breaking_60d_high"] is True
    assert sig["rvol"] >= 2.0
    assert score > 0


def test_composite_swing_weighting():
    full = {k: {"score": 100.0, "signals": {}} for k in sf.SWING_WEIGHTS}
    assert sf.composite_swing(full) == 100.0
    only_stage2 = {k: {"score": (100.0 if k == "stage2" else 0.0), "signals": {}} for k in sf.SWING_WEIGHTS}
    assert sf.composite_swing(only_stage2) == round(100.0 * sf.SWING_WEIGHTS["stage2"], 1)


def test_collect_swing_flags_namespaced():
    factors = {k: {"score": 0.0, "signals": {"flag": None}} for k in sf.SWING_WEIGHTS}
    factors["stage2"]["signals"]["flag"] = "stage2_clean"
    factors["rs"]["signals"]["flag"] = "rs_leader"
    flags = sf.collect_swing_flags(factors)
    assert "stage2:stage2_clean" in flags
    assert "rs:rs_leader" in flags


def test_compute_price_only_uptrend_positive():
    bars = _bars_from_closes([50 + i * 0.4 for i in range(240)])
    spy = _bars_from_closes([400 + i * 0.05 for i in range(240)])
    score = sf.compute_price_only({"bars": bars}, {"bars": spy})
    assert score > 0


def test_compute_price_only_no_data_is_zero():
    assert sf.compute_price_only(None, None) == 0.0
