"""Volume-profile + ATR chart levels."""
from src.score import levels


def _bars(closes, vols=None):
    return [
        {
            "date": f"2025-{(i // 28) % 12 + 1:02d}-{(i % 28) + 1:02d}",
            "open": c,
            "high": c * 1.01,
            "low": c * 0.99,
            "close": c,
            "volume": (vols[i] if vols else 1_000_000),
        }
        for i, c in enumerate(closes)
    ]


def test_volume_profile_poc_at_high_volume_price():
    closes = [100.0] * 30 + [110.0] * 5
    vols = [5_000_000] * 30 + [400_000] * 5  # most volume traded at ~100
    vp = levels.volume_profile(_bars(closes, vols))
    assert vp is not None
    assert 98 <= vp["poc"] <= 102


def test_levels_sl_below_tp_above():
    closes = [100 + (i % 5) for i in range(60)]
    lv = levels.compute_chart_levels(_bars(closes))
    assert lv["stop"] < lv["entry"] < lv["tp"]
    assert lv["rr"] > 0
    assert len(lv["ladder"]) == 3
    assert lv["risk_pct"] > 0


def test_levels_risk_clamped_to_atr_band():
    closes = [50 + i * 0.5 for i in range(60)]
    lv = levels.compute_chart_levels(_bars(closes))
    risk = lv["entry"] - lv["stop"]
    assert 0.7 * lv["atr"] <= risk <= 3.2 * lv["atr"]  # clamped 0.8–3 ATR (rounding slack)


def test_levels_degrade_gracefully_on_short_history():
    lv = levels.compute_chart_levels(_bars([100.0] * 6))
    assert lv["stop"] < lv["entry"] < lv["tp"]  # ATR-only path still yields levels
    assert lv["poc"] is None
