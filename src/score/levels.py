"""
Chart trade levels — ATR risk model snapped to volume-profile support/resistance.

Powers the ticker chart's TP / SL markers. Methodology:

- **Volume profile**: distribute each bar's volume across the price bins its
  [low, high] spans, then find the Point of Control (POC = the price where the
  most shares changed hands) and the high-volume nodes (HVNs). HVNs act as
  support/resistance precisely because that's where the most volume traded.
- **SL**: just below the nearest HVN *support* under price (volume-based), with
  an ATR buffer; risk is clamped to 0.8–3 ATR so the stop is never noise-tight
  nor absurdly wide.
- **TP**: the nearest HVN *resistance* above price that offers at least 1.5R
  (a real level the move would target); if none, a clean 3R multiple. An R
  ladder (2R/3R/5R) is returned for context.

Pure functions over OHLCV bars (dicts with low/high/close/volume). No fetching.
"""
from __future__ import annotations

from typing import Any

from src.score.risk import atr as _atr

PROFILE_BINS = 50
HVN_PERCENTILE = 0.70      # bins at/above this volume percentile are high-volume nodes
STOP_ATR_MULT = 2.0        # volatility stop when no volume support exists
MIN_RISK_ATR = 0.8         # clamp risk to a sane ATR band
MAX_RISK_ATR = 3.0
PRIMARY_TARGET_R = 3.0     # default reward when no clean resistance to aim at
MIN_TP_R = 1.5             # a resistance must be ≥ this many R away to be the TP
LADDER_RS = (2.0, 3.0, 5.0)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def volume_profile(bars: list[dict], bins: int = PROFILE_BINS) -> dict | None:
    """Volume-by-price. Returns {poc, nodes:[prices], lo, hi} or None."""
    if len(bars) < 10:
        return None
    lo = min(b["low"] for b in bars)
    hi = max(b["high"] for b in bars)
    if hi <= lo:
        return None
    width = (hi - lo) / bins
    vol = [0.0] * bins

    def _bin(price: float) -> int:
        return _clamp_int(int((price - lo) / width), 0, bins - 1)

    for b in bars:
        blo, bhi, v = b["low"], b["high"], float(b["volume"])
        if v <= 0:
            continue
        lo_idx, hi_idx = _bin(blo), _bin(bhi)
        span = hi_idx - lo_idx + 1
        share = v / span
        for i in range(lo_idx, hi_idx + 1):
            vol[i] += share

    poc_idx = max(range(bins), key=lambda i: vol[i])
    poc = lo + (poc_idx + 0.5) * width
    ordered = sorted(vol)
    thresh = ordered[int(HVN_PERCENTILE * (bins - 1))]
    nodes = [lo + (i + 0.5) * width for i in range(bins) if vol[i] >= thresh and vol[i] > 0]
    return {"poc": poc, "nodes": nodes, "lo": lo, "hi": hi}


def _clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


def compute_chart_levels(bars: list[dict]) -> dict[str, Any]:
    """ATR-risk SL/TP snapped to volume-profile S/R. Always returns usable levels."""
    last = bars[-1]["close"]
    a = _atr(bars) or max(last * 0.02, 0.01)

    vp = volume_profile(bars)
    nodes = vp["nodes"] if vp else []
    supports = sorted([p for p in nodes if p < last], reverse=True)      # nearest first
    resistances = sorted([p for p in nodes if p > last])                 # nearest first

    # ---- SL: nearest volume support (buffered) or volatility stop, risk clamped
    sl_raw = supports[0] - 0.30 * a if supports else last - STOP_ATR_MULT * a
    risk = _clamp(last - sl_raw, MIN_RISK_ATR * a, MAX_RISK_ATR * a)
    sl = last - risk
    sl_basis = "volume_support" if supports else "atr_floor"

    # ---- TP: nearest resistance giving ≥ MIN_TP_R, else a clean 3R multiple
    tp = last + PRIMARY_TARGET_R * risk
    tp_basis = "r_multiple"
    for r_price in resistances:
        if r_price - last >= MIN_TP_R * risk:
            tp = r_price
            tp_basis = "volume_resistance"
            break

    rr = (tp - last) / risk if risk > 0 else 0.0
    ladder = [{"r": r, "price": round(last + r * risk, 2)} for r in LADDER_RS]

    return {
        "entry": round(last, 2),
        "stop": round(sl, 2),
        "tp": round(tp, 2),
        "atr": round(a, 2),
        "risk_pct": round(risk / last * 100, 2) if last > 0 else 0.0,
        "rr": round(rr, 2),
        "tp_pct": round((tp / last - 1) * 100, 1) if last > 0 else 0.0,
        "sl_basis": sl_basis,
        "tp_basis": tp_basis,
        "ladder": ladder,
        "poc": round(vp["poc"], 2) if vp else None,
        "support": round(supports[0], 2) if supports else None,
        "resistance": round(resistances[0], 2) if resistances else None,
    }
