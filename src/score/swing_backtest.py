"""
Forward-return + realized-expectancy measurement for the SWING scan.

Two responsibilities, mirroring src/score/backtest.py but tuned for a 2-4 week
hold and an explicit trade plan:

1. `record_swing_snapshot(scan_result)` — appends one row per scored ticker to
   `data/screens/swing_YYYY-MM-DD.jsonl` with the swing score, factor
   breakdown, close at scan, flags, AND the trade plan (entry/stop/targets).
   Recording the plan is what lets us later simulate the *actual trade*, not
   just a buy-and-hold return.

2. `evaluate(window_days)` — for every snapshot older than `window_days`,
   replays the trade against forward OHLC bars: did price hit the stop first
   (−1R), a profit target first (+2R/+3R), or neither (mark-to-market at the
   horizon)? Aggregates realized expectancy (in R), win rate, stop-out rate,
   and final returns by swing-score decile. This is the ground truth for
   whether a higher swing score actually earns more money over the hold.

Stop/target levels are stored as recorded *prices* but applied as *fractions of
the recorded entry*, so split/dividend adjustments in the forward series can't
corrupt the simulation.

Honest by construction: with only a few scan-days of data the aggregates are
noise, and `evaluate` says so in `note` until the sample is large enough.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.config import SCREEN_DIR
from src.data import prices
from src.data.prices import DataUnavailable

if TYPE_CHECKING:
    from pathlib import Path

# Below these thresholds, decile/expectancy stats are statistically meaningless.
MIN_EVAL_FOR_SIGNAL = 200      # total ticker-days evaluated
MIN_SCAN_DAYS_FOR_SIGNAL = 10  # distinct, non-overlapping scan days


def _snapshot_path(d: date) -> Path:
    return SCREEN_DIR / f"swing_{d.isoformat()}.jsonl"


def record_swing_snapshot(scan_result: dict[str, Any]) -> int:
    """Append one row per scored swing result to today's snapshot file.

    Dedups within the file by (ticker, score) so multiple same-day scans don't
    pollute the dataset. Returns rows written.
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
                seen.add((row["ticker"], row["swing_score"]))
            except (json.JSONDecodeError, KeyError):
                continue

    weights = scan_result.get("weights") or {}
    written = 0
    with path.open("a") as f:
        for r in results:
            key = (r["ticker"], r["score"])
            if key in seen:
                continue
            plan = r.get("trade_plan") or None
            compact_plan = None
            if plan:
                compact_plan = {
                    "entry": plan.get("entry"),
                    "stop": plan.get("stop"),
                    "targets": plan.get("targets"),
                    "target_r_multiples": plan.get("target_r_multiples"),
                    "risk_pct": plan.get("risk_pct"),
                    "grade": plan.get("grade"),
                }
            row = {
                "scan_date": today.isoformat(),
                "as_of": r.get("as_of"),
                "ticker": r["ticker"],
                "swing_score": r["score"],
                "weights": weights,
                "factor_scores": {k: r["factors"][k]["score"] for k in r["factors"]},
                "close_at_scan": r.get("price"),
                "flags": r.get("flags") or [],
                "trade_plan": compact_plan,
            }
            f.write(json.dumps(row) + "\n")
            written += 1
    return written


def _iter_snapshots(min_age_days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC).date() - timedelta(days=min_age_days)
    rows: list[dict] = []
    for p in sorted(SCREEN_DIR.glob("swing_*.jsonl")):
        try:
            d = date.fromisoformat(p.stem.replace("swing_", ""))
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


def _forward_path(ticker: str, scan_date: date, window_days: int) -> dict | None:
    """Entry (adjusted) close + the forward OHLC bars within the window."""
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
        future = [b for b in bars if b["date"] >= entry_iso]
        if not future:
            return None
        entry_bar = future[0]

    entry_idx = bars.index(entry_bar)
    end_iso = (scan_date + timedelta(days=window_days)).isoformat()
    forward = [b for b in bars[entry_idx + 1:] if b["date"] <= end_iso]
    if not forward:
        return None

    entry_px = entry_bar["close"]
    if entry_px <= 0:
        return None
    return {"entry_close": entry_px, "forward": forward}


def simulate_trade(entry_adj: float, plan: dict | None, forward: list[dict]) -> dict:
    """Replay a trade over forward bars. Returns realized R, outcome, exit return %.

    Levels from the recorded plan are converted to fractions of the recorded
    entry, then applied to the (adjustment-consistent) forward entry close. When
    a single bar straddles both stop and the first target, the stop is assumed
    hit first (conservative). With no plan, falls back to mark-to-market return.
    """
    final_px = forward[-1]["close"]
    max_high = max(b["high"] for b in forward)
    min_low = min(b["low"] for b in forward)
    final_return_pct = round((final_px / entry_adj - 1) * 100, 2)
    max_drawup_pct = round((max_high / entry_adj - 1) * 100, 2)
    max_drawdown_pct = round((min_low / entry_adj - 1) * 100, 2)

    if not plan or not plan.get("entry") or not plan.get("stop") or not plan.get("targets"):
        return {
            "outcome": "no_plan",
            "realized_r": None,
            "exit_return_pct": final_return_pct,
            "final_return_pct": final_return_pct,
            "max_drawup_pct": max_drawup_pct,
            "max_drawdown_pct": max_drawdown_pct,
        }

    rec_entry = plan["entry"]
    risk_frac = (rec_entry - plan["stop"]) / rec_entry  # > 0
    if risk_frac <= 0:
        return {
            "outcome": "bad_plan",
            "realized_r": None,
            "exit_return_pct": final_return_pct,
            "final_return_pct": final_return_pct,
            "max_drawup_pct": max_drawup_pct,
            "max_drawdown_pct": max_drawdown_pct,
        }

    stop_level = entry_adj * (plan["stop"] / rec_entry)
    target1 = entry_adj * (plan["targets"][0] / rec_entry)
    r_mult_target1 = (plan.get("target_r_multiples") or [2.0])[0]

    for b in forward:
        hit_stop = b["low"] <= stop_level
        hit_target = b["high"] >= target1
        if hit_stop and hit_target:
            hit_target = False  # conservative: assume stop first
        if hit_stop:
            return {
                "outcome": "stop",
                "realized_r": -1.0,
                "exit_return_pct": round(-risk_frac * 100, 2),
                "final_return_pct": final_return_pct,
                "max_drawup_pct": max_drawup_pct,
                "max_drawdown_pct": max_drawdown_pct,
            }
        if hit_target:
            return {
                "outcome": "target",
                "realized_r": round(r_mult_target1, 2),
                "exit_return_pct": round(r_mult_target1 * risk_frac * 100, 2),
                "final_return_pct": final_return_pct,
                "max_drawup_pct": max_drawup_pct,
                "max_drawdown_pct": max_drawdown_pct,
            }

    # Neither hit by the horizon — mark to market.
    mtm_r = (final_px / entry_adj - 1) / risk_frac
    return {
        "outcome": "open",
        "realized_r": round(mtm_r, 2),
        "exit_return_pct": final_return_pct,
        "final_return_pct": final_return_pct,
        "max_drawup_pct": max_drawup_pct,
        "max_drawdown_pct": max_drawdown_pct,
    }


def _spearman_ic(pairs: list[tuple[float, float]]) -> float | None:
    """Spearman rank correlation, no scipy. None if degenerate."""
    n = len(pairs)
    if n < 5:
        return None

    def _ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    xr = _ranks([p[0] for p in pairs])
    yr = _ranks([p[1] for p in pairs])
    mx = sum(xr) / n
    my = sum(yr) / n
    cov = sum((xr[i] - mx) * (yr[i] - my) for i in range(n))
    vx = sum((xr[i] - mx) ** 2 for i in range(n))
    vy = sum((yr[i] - my) ** 2 for i in range(n))
    if vx <= 0 or vy <= 0:
        return None
    return round(cov / (vx * vy) ** 0.5, 3)


def _expectancy(rows: list[dict]) -> dict:
    """Win rate / avg win / avg loss / expectancy (R) over trades with a plan."""
    rs = [r["sim"]["realized_r"] for r in rows if r["sim"].get("realized_r") is not None]
    if not rs:
        return {"n_with_plan": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    return {
        "n_with_plan": len(rs),
        "win_rate_r": round(len(wins) / len(rs), 3),
        "avg_win_r": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_r": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "stop_rate": round(sum(1 for r in rows if r["sim"]["outcome"] == "stop") / len(rows), 3),
        "target_rate": round(sum(1 for r in rows if r["sim"]["outcome"] == "target") / len(rows), 3),
    }


def evaluate(window_days: int = 14) -> dict[str, Any]:
    """Realized expectancy + final-return by swing-score decile over the hold."""
    snapshots = _iter_snapshots(min_age_days=window_days)
    if not snapshots:
        return {
            "window_days": window_days,
            "snapshots": 0,
            "evaluated": 0,
            "deciles": [],
            "note": f"no swing snapshots older than {window_days}d — run the scan daily to accrue",
        }

    evaluated: list[dict] = []
    scan_days: set[str] = set()
    for snap in snapshots:
        scan_d = date.fromisoformat(snap["scan_date"])
        path = _forward_path(snap["ticker"], scan_d, window_days)
        if not path:
            continue
        sim = simulate_trade(path["entry_close"], snap.get("trade_plan"), path["forward"])
        evaluated.append({**snap, "sim": sim})
        scan_days.add(snap["scan_date"])

    if not evaluated:
        return {
            "window_days": window_days,
            "snapshots": len(snapshots),
            "evaluated": 0,
            "deciles": [],
            "note": "snapshots found but no forward prices available yet",
        }

    sorted_rows = sorted(evaluated, key=lambda r: r["swing_score"])
    n = len(sorted_rows)
    bucket_size = max(1, n // 10)
    deciles: list[dict] = []
    for i in range(10):
        lo = i * bucket_size
        hi = (i + 1) * bucket_size if i < 9 else n
        bucket = sorted_rows[lo:hi]
        if not bucket:
            continue
        rets = [r["sim"]["final_return_pct"] for r in bucket]
        dds = [r["sim"]["max_drawdown_pct"] for r in bucket]
        wins = sum(1 for x in rets if x > 0)
        exp = _expectancy(bucket)
        deciles.append({
            "decile": i + 1,
            "n": len(bucket),
            "score_range": [round(bucket[0]["swing_score"], 1), round(bucket[-1]["swing_score"], 1)],
            "avg_return_pct": round(sum(rets) / len(rets), 2),
            "median_return_pct": round(sorted(rets)[len(rets) // 2], 2),
            "win_rate": round(wins / len(rets), 3),
            "avg_max_drawdown_pct": round(sum(dds) / len(dds), 2),
            "expectancy_r": exp.get("expectancy_r"),
            "stop_rate": exp.get("stop_rate"),
            "target_rate": exp.get("target_rate"),
        })

    overall = _expectancy(evaluated)
    ic_ret = _spearman_ic([(r["swing_score"], r["sim"]["final_return_pct"]) for r in evaluated])
    ic_r = _spearman_ic([
        (r["swing_score"], r["sim"]["realized_r"])
        for r in evaluated
        if r["sim"].get("realized_r") is not None
    ])

    # Top-decile lift on realized expectancy vs. the full sample.
    top = deciles[-1] if deciles else None
    lift = None
    if top and overall.get("expectancy_r") not in (None, 0) and top.get("expectancy_r") is not None:
        lift = round(top["expectancy_r"] / overall["expectancy_r"], 2)

    by_flag: dict[str, list[dict]] = defaultdict(list)
    for r in evaluated:
        for flag in r.get("flags", []):
            by_flag[flag].append(r)
    flag_table = sorted(
        [
            {
                "flag": flag,
                "n": len(rows),
                "avg_return_pct": round(sum(x["sim"]["final_return_pct"] for x in rows) / len(rows), 2),
                "expectancy_r": _expectancy(rows).get("expectancy_r"),
            }
            for flag, rows in by_flag.items()
            if len(rows) >= 5
        ],
        key=lambda r: (r["expectancy_r"] if r["expectancy_r"] is not None else -99),
        reverse=True,
    )

    underpowered = len(evaluated) < MIN_EVAL_FOR_SIGNAL or len(scan_days) < MIN_SCAN_DAYS_FOR_SIGNAL
    note = None
    if underpowered:
        note = (
            f"UNDERPOWERED: {len(evaluated)} ticker-days across {len(scan_days)} scan-days. "
            f"Need ≥{MIN_EVAL_FOR_SIGNAL} ticker-days and ≥{MIN_SCAN_DAYS_FOR_SIGNAL} scan-days "
            f"for these aggregates to mean anything. Keep accruing."
        )

    return {
        "window_days": window_days,
        "snapshots": len(snapshots),
        "evaluated": len(evaluated),
        "scan_days": len(scan_days),
        "as_of": datetime.now(UTC).isoformat(),
        "overall_expectancy": overall,
        "spearman_ic_score_vs_return": ic_ret,
        "spearman_ic_score_vs_r": ic_r,
        "top_decile_expectancy_lift": lift,
        "deciles": deciles,
        "flag_performance": flag_table,
        "underpowered": underpowered,
        "note": note,
    }
