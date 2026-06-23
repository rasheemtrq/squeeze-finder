"""
Intraday crypto scalp signal — 1-minute momentum micro-breakout.

Scalping on Alpaca lives or dies on COST: 0.25% taker per side → ~0.5% round-trip
before spread. So the signal only fires on coins moving enough to clear that, and
every plan carries an explicit cost model (round-trip fee + live spread), the net
take-profit/stop, and the breakeven win rate it implies. Outcomes are recorded
NET of cost so the bot brain learns fee-adjusted expectancy, not fantasy.

Signal (0-100), long-only, on the last ~60 one-minute bars:
  - micro-breakout above the prior 15-minute high (volume-weighted)
  - relative volume surge (this minute vs the last 20)
  - intraday trend: price above VWAP and a fast EMA
  - short momentum: 5-minute return
Gated by a 1-minute ATR floor — if it's too quiet to reach the target inside the
time stop, skip it.

Pure functions over bars + a quote. No fetching, no orders.
"""
from __future__ import annotations

from typing import Any

BREAKOUT_LOOKBACK = 15   # bars (minutes) defining the level to break
MOM_LOOKBACK = 5         # minutes for the short momentum read
RVOL_WINDOW = 20         # bars for the average-volume baseline
ATR_PERIOD = 14


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _vwap(bars: list[dict]) -> float | None:
    num = den = 0.0
    for b in bars:
        typical = (b["high"] + b["low"] + b["close"]) / 3
        num += typical * b["volume"]
        den += b["volume"]
    return num / den if den > 0 else None


def _atr_pct(bars: list[dict], period: int = ATR_PERIOD) -> float | None:
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, lo, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    last = bars[-1]["close"]
    return a / last * 100 if last > 0 else None


def scalp_signal(bars: list[dict], params: dict) -> dict | None:
    """Momentum micro-breakout score for one coin, or None if too quiet/thin."""
    if len(bars) < max(BREAKOUT_LOOKBACK + 2, ATR_PERIOD + 2, RVOL_WINDOW + 2):
        return None
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    vols = [b["volume"] for b in bars]
    last = closes[-1]
    if last <= 0:
        return None

    atr_pct = _atr_pct(bars)
    if atr_pct is None or atr_pct < params["min_atr_pct"]:
        return None  # not enough intraday range to clear costs inside the time stop

    ema9 = _ema(closes, 9) or last
    vwap = _vwap(bars) or last
    base_vol = sum(vols[-(RVOL_WINDOW + 1):-1]) / RVOL_WINDOW
    rvol = vols[-1] / base_vol if base_vol > 0 else 0.0
    prior_high = max(highs[-(BREAKOUT_LOOKBACK + 1):-1])
    breakout = last > prior_high
    mom5 = (last / closes[-(MOM_LOOKBACK + 1)] - 1) * 100

    flags = ["asset:crypto"]
    s = 0.0
    if breakout:
        s += 25
        flags.append("scalp:breakout")
        if rvol >= 1.5:
            s += 15
    if rvol >= 2:
        s += 25
        flags.append("scalp:vol_surge")
    elif rvol >= 1.5:
        s += 18
    elif rvol >= 1.2:
        s += 10
    if last > vwap and last > ema9:
        s += 20
        flags.append("scalp:above_vwap_ema")
    elif last > vwap or last > ema9:
        s += 8
    if mom5 > 0:
        s += min(15, mom5 * 7.5)

    return {
        "score": round(_clip(s), 1),
        "price": last,
        "atr_pct": round(atr_pct, 3),
        "rvol": round(rvol, 2),
        "vwap": round(vwap, 6),
        "breakout": breakout,
        "mom5_pct": round(mom5, 3),
        "flags": flags,
    }


def build_scalp_plan(
    pair: str, sig: dict, quote: dict, equity: float, params: dict
) -> dict[str, Any] | None:
    """Fee-aware spot-long scalp plan, or None if it can't be sized / can't clear cost."""
    sl_pct = params["sl_pct"]
    tp_pct = params["tp_pct"]
    if sl_pct <= 0:
        return None

    # cost = round-trip taker fee + live spread (crossed once each side)
    spread_pct = quote.get("spread_pct") or 0.0
    cost_pct = 2 * params["taker_fee_pct"] + spread_pct
    win_net = tp_pct - cost_pct
    loss_net = sl_pct + cost_pct
    if win_net <= 0:
        return None  # target can't even clear costs — never trade this
    breakeven_wr = loss_net / (win_net + loss_net)

    risk_budget = equity * params["risk_pct_per_trade"] / 100.0
    notional = round(min(risk_budget / (sl_pct / 100.0), equity * params["max_position_pct"] / 100.0), 2)
    if notional < params["min_notional"]:
        return None

    entry = quote.get("ask") or sig["price"]
    return {
        "ticker": pair,
        "setup_score": sig["score"],
        "flags": sig["flags"],
        "strategy": "scalp_momentum",
        "notional": notional,
        "est_cost": notional,
        "risk_usd": round(notional * sl_pct / 100.0, 2),
        "underlying": {
            "entry": round(entry, 6),
            "stop": round(entry * (1 - sl_pct / 100), 6),
            "tp": round(entry * (1 + tp_pct / 100), 6),
        },
        "exit": {
            "sl_pct": sl_pct,                       # gross; graph reads this for R
            "tp_pct": tp_pct,                       # gross
            "time_stop_minutes": params["time_stop_minutes"],
            "cost_pct": round(cost_pct, 4),         # subtracted from gross to log net
            "win_net_pct": round(win_net, 3),
            "loss_net_pct": round(loss_net, 3),
            "breakeven_wr": round(breakeven_wr, 3),
        },
        "signal": {k: sig[k] for k in ("atr_pct", "rvol", "vwap", "breakout", "mom5_pct")},
    }


def scan_scalp(client, params: dict) -> list[dict]:
    """Score the tradable universe on live 1-minute data (one bars + one quotes call)."""
    from src.crypto.universe import tradable_pairs

    pairs = tradable_pairs()
    bars_map = client.crypto_bars(pairs, "1Min", params["bars_lookback"])
    quotes = client.crypto_latest_quotes(pairs)

    out: list[dict] = []
    for pair in pairs:
        sig = scalp_signal(bars_map.get(pair) or [], params)
        if not sig or sig["score"] <= 0:
            continue
        out.append({"ticker": pair, "quote": quotes.get(pair) or {}, **sig})
    out.sort(key=lambda r: r["score"], reverse=True)
    return out
