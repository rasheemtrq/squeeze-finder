"""
US-equity market regime classifier — FRED-driven (free, no API key needed).

Squeezes are dispersion-fueled: they ignite in risk-on / loose-conditions
regimes and die fast in vol-stress / tight-credit regimes. Practitioner
literature (Macrosynergy on VIX term structure; AQR risk-parity papers;
Chicago Fed's NFCI docs) converges on four canonical signals:

  1. VIX term structure (VIX vs VIX-3M)
     - Backwardation (VIX > VIX-3M) ≈ near-perfect risk-off binary; has
       preceded every >5% S&P drawdown since 2004. Squeezes don't survive.
  2. NFCI (Chicago Fed National Financial Conditions Index)
     - Negative = looser-than-average; positive = tighter.
     - NFCI < 0 historically associated with frothy retail conditions.
  3. ICE BofA US High Yield OAS (BAMLH0A0HYM2)
     - <3.5% = tight credit / risk-on; >5% = stressed credit.
  4. VIX absolute level — basic sentiment gauge.

We combine these into a single multiplier in [0.5, 1.3] applied to both
the linear composite and the multiplicative pressure score. The most-
restrictive condition wins (VIX backwardation kill-switch beats all
loose signals).

All four series come from FRED public CSV — no API key required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data import _cache
from src.data.prices import DataUnavailable

CACHE_TTL_SECONDS = 3600  # 1h — FRED updates daily/weekly
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

_SERIES = {
    "vix": "VIXCLS",
    "vix3m": "VXVCLS",
    "nfci": "NFCI",
    "hy_oas": "BAMLH0A0HYM2",
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def _latest(series_id: str) -> float | None:
    """Last non-null observation from a FRED daily/weekly CSV."""
    r = httpx.get(
        FRED_CSV.format(series=series_id),
        timeout=15,
        follow_redirects=True,
        headers={"User-Agent": "squeeze-finder/0.1"},
    )
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    # walk from the bottom — last row is most recent
    for line in reversed(lines[1:]):  # skip header
        parts = line.split(",")
        if len(parts) >= 2 and parts[1] not in ("", "."):
            try:
                return float(parts[1])
            except ValueError:
                continue
    return None


def fetch(force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = _cache.get("regime", "us_equity_fred", CACHE_TTL_SECONDS)
        if cached:
            return cached

    try:
        vix = _latest(_SERIES["vix"])
        vix3m = _latest(_SERIES["vix3m"])
        nfci = _latest(_SERIES["nfci"])
        hy_oas = _latest(_SERIES["hy_oas"])
    except Exception as e:
        raise DataUnavailable(f"FRED regime fetch failed: {e}") from e

    if vix is None or vix3m is None or nfci is None or hy_oas is None:
        raise DataUnavailable(
            f"missing FRED series: VIX={vix} VIX3M={vix3m} NFCI={nfci} HYOAS={hy_oas}"
        )

    backwardation = vix > vix3m  # the kill switch
    vix_term_ratio = round(vix / vix3m, 3) if vix3m > 0 else None

    # Most-restrictive wins. Note thresholds are calibrated against the
    # academic literature, not fit to backtest (which would overfit).
    if backwardation:
        regime = "vol_stress"
        multiplier = 0.50
        reason = "VIX > VIX-3M (backwardation kill-switch)"
    elif nfci > 0.5 or hy_oas > 5.0:
        regime = "risk_off"
        multiplier = 0.70
        reason = (
            f"NFCI {nfci:+.2f} > 0.5"
            if nfci > 0.5
            else f"HY OAS {hy_oas:.2f}% > 5%"
        )
    elif nfci < 0 and hy_oas < 3.5 and vix < 18:
        regime = "risk_on"
        multiplier = 1.20
        reason = "NFCI<0, HY OAS<3.5%, VIX<18"
    else:
        regime = "neutral"
        multiplier = 1.00
        reason = "no extreme signal"

    result = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "regime": regime,
        "multiplier": multiplier,
        "reason": reason,
        "vix": round(vix, 2),
        "vix3m": round(vix3m, 2),
        "vix_term_ratio": vix_term_ratio,
        "backwardation": backwardation,
        "nfci": round(nfci, 3),
        "hy_oas_pct": round(hy_oas, 2),
        "source": "FRED",
    }
    _cache.put("regime", "us_equity_fred", result)
    return result
