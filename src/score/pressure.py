"""
Multiplicative squeeze-pressure scorer.

Parallel signal to the linear 5-factor composite — runs simultaneously
on every ticker, doesn't replace anything else. Implements the consensus
model from the literature review:
- Allen, Haas, Nowak, Pirovano & Tengulov (2025) "Squeezing Shorts Through
  Social Media Platforms" — the interaction WSB × SI × Call_OI predicts
  +5–7% next-day abnormal return, AUC ~0.66–0.70.
- SqueezeMetrics / SpotGamma dealer-gamma formulation.
- Engelberg, Evans, Leonard, Reed & Ringgenberg (2018) — short-fee
  acceleration as a leading indicator (approximated via FINRA daily
  short-volume velocity since we lack paid borrow data).

Three pressures, each normalized to roughly 0-100, combined via geometric
mean. A high score requires ALL THREE pressures firing — single-factor
candidates score near zero, matching the empirical finding that squeezes
are an interaction effect.
"""
from __future__ import annotations

import math


_RISK_FREE = 0.045
_IV_FALLBACK = 0.6
_IV_STALE_THRESHOLD = 0.05
_DTE_MIN = 3   # 0–2 DTE is 0DTE chaos, not squeeze-mechanic gamma
_DTE_MAX = 21
_MIN_OI = 50


# ────────────────────────────────────────────────────────────────────────
#  L — Lending Pressure
#  When iBorrowDesk data is present: real CTB + utilization proxy + fee
#  acceleration drive the score (Engelberg 2018 — dominates 102 anomalies).
#  When absent: fall back to SI%/DTC + FINRA short-volume acceleration as
#  the previous proxy. Reg SHO threshold-list residency adds a 1.3× kicker.
# ────────────────────────────────────────────────────────────────────────

def lending_pressure(
    fund: dict | None,
    finra: dict | None,
    iborrowdesk: dict | None = None,
    regsho: dict | None = None,
) -> float:
    if not fund:
        return 0.0

    si_pct = fund.get("short_percent_of_float") or 0
    dtc = fund.get("short_ratio") or 0

    L_level = si_pct / 0.20  # 1.0 at 20% SI/float, the practitioner threshold
    L_dtc = math.sqrt(dtc / 5) if dtc > 0 else 0.5  # √(DTC/5)

    # Borrow signal: prefer iBorrowDesk live data, fall back to FINRA accel.
    L_borrow = 1.0
    if iborrowdesk:
        util = iborrowdesk.get("utilization_proxy")
        fee_accel = iborrowdesk.get("fee_acceleration")
        fee = iborrowdesk.get("latest_fee_pct")

        # Utilization: 1.0 baseline at util ≤ 0.5; ramps to 2.5× at full scarcity.
        util_term = 1.0
        if util is not None:
            util_term = 1.0 + max(0.0, util - 0.5) * 3.0  # 0.5→1.0, 0.75→1.75, 1.0→2.5

        # Fee acceleration: 1.0 at flat; ramps to 2× at 3× fee in 2d vs 5d baseline.
        accel_term = 1.0
        if fee_accel is not None and fee_accel > 1.0:
            accel_term = 1.0 + min(1.0, (fee_accel - 1.0) * 0.5)

        # Hard-to-borrow level: above 5% fee, every additional 10% adds 0.5.
        fee_term = 1.0
        if fee is not None and fee >= 5.0:
            fee_term = 1.0 + min(1.5, (fee - 5.0) / 10.0 * 0.5)

        L_borrow = util_term * accel_term * fee_term
    elif finra and finra.get("series"):
        series = finra["series"]
        if len(series) >= 6:
            recent = [s.get("short_ratio", 0) for s in series[:3]]
            older = [s.get("short_ratio", 0) for s in series[3:]]
            recent_avg = sum(recent) / len(recent)
            older_avg = sum(older) / len(older) if older else 0
            if older_avg > 0:
                L_borrow = recent_avg / older_avg

    L = L_level * L_dtc * L_borrow

    # Reg SHO threshold list — names with ≥5 consecutive settlement days of
    # persistent FTDs face mandatory close-out under Rule 204. Mechanical
    # forced-cover pressure. Boost ≥1.3× when present, more on extended stays.
    if regsho and regsho.get("on_threshold_list"):
        days = regsho.get("consecutive_days") or 1
        boost = 1.3 + min(0.7, max(0, days - 5) * 0.05)  # 5d→1.3, 10d→1.55, 20d→2.0
        L *= boost

    return L


# ────────────────────────────────────────────────────────────────────────
#  G — Gamma Pressure
#  Dealer dollar-gamma on near-money near-expiry calls, normalized by
#  market cap. Formula follows SqueezeMetrics/SpotGamma convention:
#    GEX_K = γ(S, K, τ, σ) · OI · 100 · S²   (dollar-shares per 1% move)
#  No extra √τ weighting — BS gamma already amplifies near-expiry.
# ────────────────────────────────────────────────────────────────────────

def _bs_gamma(S: float, K: float, T: float, sigma: float, r: float = _RISK_FREE) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    nd1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return nd1 / (S * sigma * sqrt_T)


def gamma_pressure(options_data: dict | None, fund: dict | None) -> float:
    if not options_data or not fund:
        return 0.0

    spot = options_data.get("spot") or 0
    strikes = options_data.get("gamma_strikes") or []
    float_shares = fund.get("float_shares") or fund.get("shares_outstanding") or 0

    if spot <= 0 or float_shares <= 0 or not strikes:
        return 0.0

    total_dollar_gamma = 0.0
    for s in strikes:
        K = s.get("strike") or 0
        oi = s.get("oi") or 0
        iv = s.get("iv") or 0
        dte = s.get("dte") if s.get("dte") is not None else 99
        if oi < _MIN_OI or dte < _DTE_MIN or dte > _DTE_MAX or K <= 0:
            continue
        if iv < _IV_STALE_THRESHOLD:
            iv = _IV_FALLBACK  # stale-chain fallback

        T = dte / 365.0
        gamma_val = _bs_gamma(spot, K, T, iv)
        if gamma_val <= 0:
            continue
        # SqueezeMetrics formula: γ · OI · 100 (shares/contract) · S²
        dollar_gamma = gamma_val * oi * 100 * spot * spot
        total_dollar_gamma += dollar_gamma

    market_cap = spot * float_shares
    return total_dollar_gamma / market_cap


# ────────────────────────────────────────────────────────────────────────
#  S — Social Pressure
#  Multi-source confirmation of retail attention.
#  WSB (Apewisdom): rank + day-over-day velocity.
#  StockTwits: 24h engagement × polarity.
#  Combined via geometric mean when both fire; half-credit single source.
# ────────────────────────────────────────────────────────────────────────

def social_pressure(stocktwits: dict | None, apewisdom: dict | None) -> float:
    wsb = 0.0
    if apewisdom:
        rank = apewisdom.get("rank") or 999
        mentions = apewisdom.get("mentions") or 0
        prior = apewisdom.get("mentions_24h_ago")

        rank_score = max(0.0, 1 - rank / 100) * 10 if rank <= 100 else 0.0

        if prior and prior > 0:
            velocity = mentions / prior
            velocity_score = max(0.0, velocity - 1) * 5  # 2× → 5, 3× → 10
        else:
            velocity_score = math.log1p(max(mentions, 0)) if mentions >= 10 else 0.0

        wsb = rank_score + velocity_score

    st = 0.0
    if stocktwits:
        n = stocktwits.get("messages_sampled") or 0
        bull = stocktwits.get("bull_ratio") or 0.5
        if n >= 20:
            engagement = math.log1p(n / 10)
            polarity = max(0.0, (bull - 0.5) * 2)  # 0.5 bull → 0, 1.0 bull → 1
            st = engagement * polarity * 5

    if wsb > 0 and st > 0:
        return math.sqrt(wsb * st) * 2  # geometric mean × 2 to preserve magnitude
    return max(wsb, st) * 0.5  # single-source penalty


# ────────────────────────────────────────────────────────────────────────
#  Composite — geometric mean of normalized pressures.
#  Range: 0–100. Single-factor candidate → score near 0.
#  All three elevated → score 70+.
# ────────────────────────────────────────────────────────────────────────

def squeeze_score(L: float, G: float, S: float) -> dict:
    L_norm = min(100.0, L * 10)        # L=10 → 100   (e.g., 40% SI × 2× DTC × 1.5× accel)
    G_norm = min(100.0, G * 500)       # G=0.2 → 100  (dealer gamma = 20% of market cap)
    S_norm = min(100.0, S * 5)         # S=20 → 100   (e.g., WSB rank 5 + 3× velocity + ST hot)

    if L_norm <= 0 or G_norm <= 0 or S_norm <= 0:
        composite = 0.0
    else:
        # Geometric mean: a single zero → composite zero, by design.
        composite = (L_norm * G_norm * S_norm) ** (1 / 3)

    return {
        "score": round(composite, 1),
        "components": {
            "lending": round(L_norm, 1),
            "gamma": round(G_norm, 1),
            "social": round(S_norm, 1),
        },
        "raw": {
            "L": round(L, 4),
            "G": round(G, 6),
            "S": round(S, 4),
        },
    }


def compute(bundle: dict) -> dict:
    """Takes a scanner bundle, returns the full pressure result."""
    L = lending_pressure(
        bundle.get("fundamentals"),
        bundle.get("finra"),
        bundle.get("iborrowdesk"),
        bundle.get("regsho"),
    )
    G = gamma_pressure(bundle.get("options"), bundle.get("fundamentals"))
    S = social_pressure(bundle.get("stocktwits"), bundle.get("apewisdom"))
    return squeeze_score(L, G, S)
