"""
Sector base rates for short interest, used to normalize SI signal by industry.

20% SI in a biotech is base-rate; 20% SI in a mega-cap tech name is
extraordinary. The current model treats them identically. This module
provides per-sector reference distributions so SI factor scoring can rank
percentile-within-sector rather than against a universal threshold.

Reference points are approximations from public market-aggregates
(MarketBeat sector SI dashboards, FINRA bi-monthly SI reports rolled up
by GICS sector, 2024-2026 averages). They're updated infrequently — drift
exists but the cross-sectional ordering is stable. When tuning the model
against the calibration dashboard, prefer adjusting these references over
adjusting score_si thresholds.

Keys match yfinance's `info.sector` strings (close to GICS sector level).
Biotech distinction (Healthcare sub-industry) would need yfinance
`.industry` granularity — a v2 refinement.
"""
from __future__ import annotations

# Per-sector reference SI %float distributions: (median, p75, p90).
# A name at p90 in its sector is in the top 10% of shorting concentration
# for that industry — the threshold for "this is unusual."
SECTOR_SI_REFERENCE: dict[str, tuple[float, float, float]] = {
    "Healthcare":             (0.06, 0.16, 0.32),
    "Technology":             (0.03, 0.08, 0.18),
    "Consumer Cyclical":      (0.04, 0.12, 0.28),
    "Communication Services": (0.03, 0.08, 0.18),
    "Financial Services":     (0.02, 0.05, 0.12),
    "Energy":                 (0.03, 0.08, 0.18),
    "Industrials":            (0.03, 0.07, 0.15),
    "Consumer Defensive":     (0.02, 0.06, 0.12),
    "Real Estate":            (0.03, 0.07, 0.15),
    "Basic Materials":        (0.03, 0.07, 0.15),
    "Utilities":              (0.02, 0.04, 0.10),
}
DEFAULT_REF: tuple[float, float, float] = (0.04, 0.10, 0.20)


def sector_reference(sector: str | None) -> tuple[float, float, float]:
    """(median, p75, p90) for the named sector, or a market-wide default."""
    if not sector:
        return DEFAULT_REF
    return SECTOR_SI_REFERENCE.get(sector, DEFAULT_REF)


def si_pct_normalized(si_pct: float | None, sector: str | None) -> float:
    """
    Map raw SI%float onto a 0–1 percentile-within-sector value.

    Two-piece linear interpolation:
      below median -> 0.0–0.5 (scaled by si/median)
      median–p90   -> 0.5–0.9
      above p90    -> 0.9–1.0 (capped at 2×p90)

    Returns 0.0 for None or non-positive SI.
    """
    if not si_pct or si_pct <= 0:
        return 0.0

    median, _p75, p90 = sector_reference(sector)

    if si_pct <= median:
        if median <= 0:
            return 0.0
        return min(0.5, (si_pct / median) * 0.5)

    if si_pct <= p90:
        if p90 <= median:
            return 0.9
        return 0.5 + (si_pct - median) / (p90 - median) * 0.4

    # above p90 — diminishing returns past 2×p90
    excess = (si_pct - p90) / max(p90, 0.01)
    return min(1.0, 0.9 + excess * 0.1)


def si_pct_reference_p75(sector: str | None) -> float:
    """p75 of the sector's SI distribution — used as the lending-pressure
    L_level normalizer in `pressure.py` (replaces the universal 0.20)."""
    return sector_reference(sector)[1]
