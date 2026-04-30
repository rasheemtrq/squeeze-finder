"""
Forward-return measurement for the squeeze scan.

Two responsibilities:

1. `record_snapshot(scan_result)` — appends a row per scored ticker to
   `data/screens/scan_YYYYMMDD.jsonl` with the score, factor breakdown, and
   close at the time of the scan. Idempotent per (date, ticker, score) so
   re-running a scan in the same day doesn't create duplicates.

2. `evaluate(window_days)` — for every recorded snapshot older than
   `window_days`, joins forward closes from the prices cache and reports
   hit-rate by score-decile. This is the ground truth for whether changes to
   factors or weights actually move forward returns.

Intentionally descriptive, not a parameter-search loop. Once we have ~4 weeks
of data the user can re-tune weights manually.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import SCREEN_DIR
from src.data import prices
from src.data.prices import DataUnavailable


def _snapshot_path(d: date) -> Path:
    return SCREEN_DIR / f"scan_{d.isoformat()}.jsonl"


def record_snapshot(scan_result: dict[str, Any]) -> int:
    """Append one row per scored result to today's snapshot file. Returns rows written.

    Dedups within the same file by (ticker, score) to keep multiple same-day
    scans from polluting the dataset — a re-scan with identical scores is a
    no-op, but a re-scan with a different score (e.g. after intraday data
    update) still records.
    """
    results = scan_result.get("results") or []
    if not results:
        return 0

    today = datetime.now(UTC).date()
    path = _snapshot_path(today)

    seen: set[tuple[str, float]] = set()
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
                seen.add((row["ticker"], row["composite"]))
            except (json.JSONDecodeError, KeyError):
                continue

    weights = scan_result.get("weights") or {}
    written = 0
    with path.open("a") as f:
        for r in results:
            key = (r["ticker"], r["score"])
            if key in seen:
                continue
            row = {
                "scan_date": today.isoformat(),
                "as_of": r.get("as_of"),
                "ticker": r["ticker"],
                "composite": r["score"],
                "weights": weights,
                "factor_scores": {k: r["factors"][k]["score"] for k in r["factors"]},
                "close_at_scan": r.get("price"),
                "flags": r.get("flags") or [],
            }
            f.write(json.dumps(row) + "\n")
            written += 1
    return written


def _iter_snapshots(min_age_days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC).date() - timedelta(days=min_age_days)
    rows: list[dict] = []
    for p in sorted(SCREEN_DIR.glob("scan_*.jsonl")):
        try:
            d = date.fromisoformat(p.stem.replace("scan_", ""))
        except ValueError:
            continue
        if d > cutoff:
            continue
        for line in p.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _forward_return(ticker: str, scan_date: date, window_days: int) -> dict | None:
    """Compute final return + max favorable excursion over `window_days` calendar days."""
    try:
        bundle = prices.fetch(ticker, period="1y")
    except DataUnavailable:
        return None
    bars = bundle.get("bars") or []
    if not bars:
        return None

    by_date = {b["date"]: b for b in bars}
    entry_iso = scan_date.isoformat()
    entry_bar = by_date.get(entry_iso)
    if not entry_bar:
        # find next trading day on or after scan_date
        future = [b for b in bars if b["date"] >= entry_iso]
        if not future:
            return None
        entry_bar = future[0]

    entry_idx = bars.index(entry_bar)
    end_iso = (scan_date + timedelta(days=window_days)).isoformat()
    forward = [b for b in bars[entry_idx + 1 :] if b["date"] <= end_iso]
    if not forward:
        return None

    entry_px = entry_bar["close"]
    if entry_px <= 0:
        return None

    final_px = forward[-1]["close"]
    max_high = max(b["high"] for b in forward)
    min_low = min(b["low"] for b in forward)

    return {
        "entry_date": entry_bar["date"],
        "entry_close": entry_px,
        "final_close": final_px,
        "final_return_pct": round((final_px / entry_px - 1) * 100, 2),
        "max_drawup_pct": round((max_high / entry_px - 1) * 100, 2),
        "max_drawdown_pct": round((min_low / entry_px - 1) * 100, 2),
        "bars_observed": len(forward),
    }


def evaluate(window_days: int = 5) -> dict[str, Any]:
    """Hit-rate and average return by score-decile across all eligible snapshots."""
    snapshots = _iter_snapshots(min_age_days=window_days)
    if not snapshots:
        return {
            "window_days": window_days,
            "snapshots": 0,
            "evaluated": 0,
            "deciles": [],
            "note": f"no snapshots older than {window_days}d",
        }

    evaluated = []
    for snap in snapshots:
        scan_d = date.fromisoformat(snap["scan_date"])
        fwd = _forward_return(snap["ticker"], scan_d, window_days)
        if not fwd:
            continue
        evaluated.append({**snap, "forward": fwd})

    if not evaluated:
        return {
            "window_days": window_days,
            "snapshots": len(snapshots),
            "evaluated": 0,
            "deciles": [],
            "note": "snapshots found but no forward prices available",
        }

    # decile by composite score
    sorted_rows = sorted(evaluated, key=lambda r: r["composite"])
    n = len(sorted_rows)
    bucket_size = max(1, n // 10)
    deciles: list[dict] = []
    for i in range(10):
        lo = i * bucket_size
        hi = (i + 1) * bucket_size if i < 9 else n
        bucket = sorted_rows[lo:hi]
        if not bucket:
            continue
        rets = [r["forward"]["final_return_pct"] for r in bucket]
        drawups = [r["forward"]["max_drawup_pct"] for r in bucket]
        wins = sum(1 for r in rets if r > 0)
        big_wins = sum(1 for r in drawups if r >= 50)
        deciles.append({
            "decile": i + 1,
            "n": len(bucket),
            "score_range": [round(bucket[0]["composite"], 1), round(bucket[-1]["composite"], 1)],
            "avg_return_pct": round(sum(rets) / len(rets), 2),
            "median_return_pct": round(sorted(rets)[len(rets) // 2], 2),
            "win_rate": round(wins / len(rets), 3),
            "pct_with_50pct_drawup": round(big_wins / len(drawups), 3),
            "avg_max_drawup_pct": round(sum(drawups) / len(drawups), 2),
        })

    by_flag: dict[str, list[float]] = defaultdict(list)
    for r in evaluated:
        for flag in r.get("flags", []):
            by_flag[flag].append(r["forward"]["final_return_pct"])
    flag_table = sorted(
        [
            {
                "flag": flag,
                "n": len(rets),
                "avg_return_pct": round(sum(rets) / len(rets), 2),
                "win_rate": round(sum(1 for x in rets if x > 0) / len(rets), 3),
            }
            for flag, rets in by_flag.items()
            if len(rets) >= 5
        ],
        key=lambda r: r["avg_return_pct"],
        reverse=True,
    )

    return {
        "window_days": window_days,
        "snapshots": len(snapshots),
        "evaluated": len(evaluated),
        "as_of": datetime.now(UTC).isoformat(),
        "deciles": deciles,
        "flag_performance": flag_table,
    }
