"""
Calibration dashboard — Brier-score decomposition + reliability diagram
for the composite-score → realized-squeeze mapping.

Why this exists: every weight/threshold change we ship adds a free
parameter to a model with ~5–30 real squeezes per year in our universe.
Without calibration measurement, we can't tell which changes actually
help — and many will look great in absolute-return-by-decile but fail
the reliability test (model overconfident at the high end).

Outputs:
1. Reliability diagram — score-bucket × realized-hit-rate; the closer to
   diagonal, the better calibrated.
2. Brier score decomposition (Murphy 1973):
     BS = Reliability − Resolution + Uncertainty
   - Reliability: how close bucket means are to bucket-realized hit rates
     (lower = better; 0 = perfectly calibrated)
   - Resolution: how much bucket hit-rates differ from base rate (higher
     = better; this is the "model actually distinguishes wins")
   - Uncertainty: base-rate term = p(1-p); ceiling we can't reduce
3. Lift over baseline: hit-rate at top decile / overall base rate.
4. Spearman rank IC: rank-correlation of score with forward return.

We compute the same metrics on both the linear composite and the
multiplicative pressure score so they can be compared head-to-head.

A "win" is defined as forward return ≥ `win_threshold_pct` over the
`window_days` horizon. Default: ≥10% over 5 trading days. Adjust per
the strategy you actually trade.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from src.score.backtest import _forward_return, _iter_snapshots


def _bucket(score: float, n_buckets: int = 10) -> int:
    """Map a 0–100 score into a bucket index 0..n_buckets-1."""
    if score < 0:
        return 0
    if score >= 100:
        return n_buckets - 1
    return min(n_buckets - 1, int(score / (100 / n_buckets)))


def _spearman_ic(pairs: list[tuple[float, float]]) -> float | None:
    """Rank correlation between (score, forward_return) without scipy."""
    if len(pairs) < 5:
        return None
    n = len(pairs)
    # rank both columns (average ranks for ties)
    def _ranks(vals: list[float]) -> list[float]:
        indexed = sorted(range(len(vals)), key=lambda i: vals[i])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(indexed):
            j = i
            while j + 1 < len(indexed) and vals[indexed[j + 1]] == vals[indexed[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg_rank
            i = j + 1
        return ranks

    rx = _ranks([p[0] for p in pairs])
    ry = _ranks([p[1] for p in pairs])
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    cov = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
    var_x = sum((r - mean_x) ** 2 for r in rx)
    var_y = sum((r - mean_y) ** 2 for r in ry)
    if var_x <= 0 or var_y <= 0:
        return None
    return round(cov / (var_x ** 0.5 * var_y ** 0.5), 4)


def _brier_decomposition(
    pairs: list[tuple[float, int]],
    n_buckets: int = 10,
) -> dict[str, Any]:
    """
    pairs: list of (predicted_probability_in_[0,1], realized_binary_in_{0,1}).
    Returns Brier score, reliability, resolution, uncertainty + per-bucket
    reliability rows for the diagram.
    """
    n = len(pairs)
    if n == 0:
        return {"n": 0, "brier": None, "reliability": None, "resolution": None, "uncertainty": None, "buckets": []}

    base_rate = sum(y for _, y in pairs) / n
    uncertainty = base_rate * (1 - base_rate)

    # raw Brier
    brier = sum((p - y) ** 2 for p, y in pairs) / n

    # bucket the predictions
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_buckets)]
    for p, y in pairs:
        idx = min(n_buckets - 1, int(p * n_buckets))
        buckets[idx].append((p, y))

    reliability = 0.0
    resolution = 0.0
    diagram: list[dict] = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        n_k = len(bucket)
        p_bar = sum(p for p, _ in bucket) / n_k
        y_bar = sum(y for _, y in bucket) / n_k
        reliability += (n_k / n) * (p_bar - y_bar) ** 2
        resolution += (n_k / n) * (y_bar - base_rate) ** 2
        diagram.append({
            "bucket": i,
            "score_range_pct": [round(i * 100 / n_buckets, 1), round((i + 1) * 100 / n_buckets, 1)],
            "n": n_k,
            "predicted_p": round(p_bar, 3),
            "realized_hit_rate": round(y_bar, 3),
            "gap": round(p_bar - y_bar, 3),  # positive = overconfident
        })

    return {
        "n": n,
        "base_rate": round(base_rate, 3),
        "brier": round(brier, 4),
        "reliability": round(reliability, 4),  # lower better
        "resolution": round(resolution, 4),    # higher better
        "uncertainty": round(uncertainty, 4),
        "skill": round(resolution - reliability, 4),  # net signal; >0 = better than base rate
        "buckets": diagram,
    }


def evaluate(
    window_days: int = 5,
    win_threshold_pct: float = 10.0,
    n_buckets: int = 10,
) -> dict[str, Any]:
    """
    Full calibration report for both composite and pressure scores.

    Args:
        window_days: forward-return horizon, calendar days
        win_threshold_pct: threshold defining a "win" (forward return >= this %)
        n_buckets: reliability-diagram resolution

    Returns dict with keys: composite, pressure, summary, settings.
    """
    snapshots = _iter_snapshots(min_age_days=window_days)

    pairs_composite: list[tuple[float, float]] = []  # (score, return)
    pairs_pressure: list[tuple[float, float]] = []
    win_composite: list[tuple[float, int]] = []      # (predicted_p, win)
    win_pressure: list[tuple[float, int]] = []
    drawup_pairs: list[tuple[float, float]] = []     # composite-score vs max drawup

    evaluated = 0
    for snap in snapshots:
        try:
            scan_d = date.fromisoformat(snap["scan_date"])
        except (ValueError, KeyError):
            continue
        fwd = _forward_return(snap["ticker"], scan_d, window_days)
        if not fwd:
            continue
        evaluated += 1

        final_ret = fwd["final_return_pct"]
        drawup = fwd["max_drawup_pct"]
        composite_score = snap.get("composite", 0)
        # We use max_drawup as the "win" signal — captures the entire forward
        # window's upside, not just close-to-close (which is what a squeeze
        # trader would actually realize via an intraday exit).
        won = 1 if drawup >= win_threshold_pct else 0

        pairs_composite.append((composite_score, final_ret))
        win_composite.append((composite_score / 100.0, won))
        drawup_pairs.append((composite_score, drawup))

        pressure_score = (snap.get("pressure_score") or {}).get("score")
        if pressure_score is not None:
            pairs_pressure.append((pressure_score, final_ret))
            win_pressure.append((pressure_score / 100.0, won))

    if not evaluated:
        return {
            "settings": {
                "window_days": window_days,
                "win_threshold_pct": win_threshold_pct,
                "n_buckets": n_buckets,
            },
            "snapshots": len(snapshots),
            "evaluated": 0,
            "note": "no evaluable snapshots — need scan history older than window_days",
        }

    composite_report = _brier_decomposition(win_composite, n_buckets=n_buckets)
    pressure_report = (
        _brier_decomposition(win_pressure, n_buckets=n_buckets)
        if win_pressure else {"n": 0, "note": "no pressure_score in any snapshot"}
    )

    # Lift @ top decile
    def _lift(buckets: list[dict]) -> float | None:
        if not buckets:
            return None
        base = sum(b["realized_hit_rate"] * b["n"] for b in buckets) / sum(b["n"] for b in buckets)
        top = next((b for b in reversed(buckets) if b["n"] > 0), None)
        if not top or base <= 0:
            return None
        return round(top["realized_hit_rate"] / base, 2)

    return {
        "settings": {
            "window_days": window_days,
            "win_threshold_pct": win_threshold_pct,
            "n_buckets": n_buckets,
        },
        "as_of": datetime.now(UTC).isoformat(),
        "snapshots": len(snapshots),
        "evaluated": evaluated,
        "composite": {
            **composite_report,
            "lift_at_top_decile": _lift(composite_report.get("buckets") or []),
            "spearman_ic_score_vs_return": _spearman_ic(pairs_composite),
            "spearman_ic_score_vs_drawup": _spearman_ic(drawup_pairs),
        },
        "pressure": {
            **pressure_report,
            "lift_at_top_decile": _lift(pressure_report.get("buckets") or [])
                if pressure_report.get("buckets") else None,
            "spearman_ic_score_vs_return": _spearman_ic(pairs_pressure) if pairs_pressure else None,
        },
    }
