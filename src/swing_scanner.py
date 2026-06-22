"""
Swing-trade scanner. Different game from the squeeze scanner — looks for
multi-week trend continuation setups (Stage-2 + volume-confirmed breakouts
+ relative strength) rather than 2-10x asymmetric squeeze plays.

Reuses:
  - The same dynamic universe builder (core watchlist + WSB + StockTwits trending)
  - Most data fetchers (prices, fundamentals, catalysts, insiders, inst_holders)
  - The same SWR cache pattern
  - The same regime gate (risk-off cuts swing scores too)

Skips (doesn't fetch):
  - StockTwits / Apewisdom (sentiment irrelevant for institutional swings)
  - Options / FINRA (no derivatives signal needed)
  - Dilution (relevant later, not for catching the move early)

The result: swing scan is materially faster than squeeze scan since 4 of
the 11 squeeze data sources are skipped.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import json
import threading
from datetime import UTC, datetime
from typing import Any

from src.config import DEFAULT_UNIVERSE, INNER_FETCH_CONCURRENCY
from src.data import (
    _cache,
    catalysts,
    fundamentals,
    insiders,
    inst_holders,
    liquid_universe,
    prices,
)
from src.data import (
    regime as regime_data,
)
from src.data import universe as universe_builder
from src.data.prices import DataUnavailable
from src.score.composite import is_red_flag
from src.score.risk import build_trade_plan, risk_quality_multiplier
from src.score.swing_backtest import record_swing_snapshot
from src.score.swing_factors import (
    SWING_WEIGHTS,
    collect_swing_flags,
    composite_swing,
    compute_price_only,
    compute_swing,
)

SCAN_CACHE_FRESH_TTL = 1800   # 30 min fresh
SCAN_CACHE_MAX_AGE = 86400    # 24 h serve-stale (warm cron keeps it fresh in-hours)

_in_flight_refreshes: set[str] = set()
_in_flight_lock = threading.Lock()


def fetch_swing_bundle(ticker: str) -> dict[str, Any]:
    """Lean per-ticker fetch — only the sources swing factors need.

    Note: prices fetched at period=1y so we have enough bars for the 200-day
    EMA in score_stage2.
    """
    bundle: dict[str, Any] = {"ticker": ticker, "errors": {}}
    sources = {
        "prices": lambda: prices.fetch(ticker, period="1y"),
        "fundamentals": lambda: fundamentals.fetch(ticker),
        "catalysts": lambda: catalysts.fetch(ticker),
        "insiders": lambda: insiders.fetch(ticker),
        "inst_holders": lambda: inst_holders.fetch(ticker),
    }

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=INNER_FETCH_CONCURRENCY
    ) as pool:
        future_to_name = {pool.submit(fn): name for name, fn in sources.items()}
        for future in concurrent.futures.as_completed(future_to_name):
            name = future_to_name[future]
            try:
                bundle[name] = future.result()
            except DataUnavailable as e:
                bundle[name] = None
                bundle["errors"][name] = str(e)
            except Exception as e:
                bundle[name] = None
                bundle["errors"][name] = f"unexpected: {e}"
    return bundle


def score_ticker_swing(
    ticker: str, spy_prices: dict | None = None, weights: dict | None = None
) -> dict[str, Any]:
    bundle = fetch_swing_bundle(ticker)
    excluded, red_flag = is_red_flag(bundle)  # share the illiquid-name gate

    factors = compute_swing(bundle, spy_prices=spy_prices)
    score = composite_swing(factors, weights)
    flags = collect_swing_flags(factors)

    # Swing-specific risk demotes — different from squeeze (we WANT names
    # that are running; "late_party" demote does NOT apply here. Only
    # post_blowoff applies — even swings shouldn't chase 200%+ in 60d).
    if red_flag == "post_blowoff":
        flags.append(f"risk:{red_flag}")
        score = max(0, score - 25)
    elif red_flag and excluded:
        flags.append(f"risk:{red_flag}")

    # Concrete trade plan (entry/stop/targets/size) + R:R-quality coupling.
    # Tight-risk setups earn more R per move, so nudge the rank toward them;
    # extended setups (wide stop) get demoted. This is the reliability lever.
    prices_data = bundle.get("prices") or {}
    trade_plan = build_trade_plan(prices_data)
    if trade_plan:
        score = round(score * risk_quality_multiplier(trade_plan), 1)
        flags.append(f"risk:{trade_plan['grade']}_stop")

    fund = bundle.get("fundamentals") or {}

    return {
        "ticker": ticker,
        "name": fund.get("name", ticker),
        "price": fund.get("price") or prices_data.get("close"),
        "market_cap": fund.get("market_cap"),
        "score": score,
        "factors": factors,
        "trade_plan": trade_plan,
        "flags": flags,
        "excluded": excluded,
        "exclude_reason": red_flag if excluded else None,
        "as_of": datetime.now(UTC).isoformat(),
        "errors": bundle.get("errors", {}),
    }


def _maybe_refresh_in_background(cache_key: str, **scan_kwargs: Any) -> None:
    with _in_flight_lock:
        if cache_key in _in_flight_refreshes:
            return
        _in_flight_refreshes.add(cache_key)

    def _run() -> None:
        try:
            swing_scan(force_refresh=True, **scan_kwargs)
        except Exception:
            pass
        finally:
            with _in_flight_lock:
                _in_flight_refreshes.discard(cache_key)

    threading.Thread(target=_run, daemon=True, name=f"swing-refresh-{cache_key}").start()


def _prefilter_price_only(
    universe: list[str], spy_prices: dict | None, top_n: int, max_workers: int
) -> list[str]:
    """Stage 1: rank the universe on a price-only swing score (one fetch each).

    Returns the top_n tickers by the renormalized stage2/breakout/RS score, so
    only the strongest trends pay for the expensive Stage-2 enrichment. Names
    that fail to fetch or score 0 are dropped.
    """
    scored: list[tuple[str, float]] = []

    def _score(t: str) -> tuple[str, float] | None:
        try:
            p = prices.fetch(t, period="1y")
        except Exception:
            return None
        s = compute_price_only(p, spy_prices)
        return (t, s) if s > 0 else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for fut in concurrent.futures.as_completed([pool.submit(_score, t) for t in universe]):
            r = fut.result()
            if r:
                scored.append(r)

    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored[:top_n]]


def swing_scan(
    tickers: list[str] | None = None,
    weights: dict | None = None,
    max_workers: int = 16,
    min_score: float = 0,
    limit: int = 25,
    force_refresh: bool = False,
    dynamic_universe: bool = True,
    universe_mode: str = "liquid",
    prefilter_n: int = 60,
) -> dict[str, Any]:
    if tickers:
        universe = tickers
        universe_sources: dict[str, list[str]] = {"override": list(tickers)}
        mode = "override"
    else:
        mode = universe_mode if universe_mode else ("dynamic" if dynamic_universe else "core")
        if mode == "liquid":
            built = liquid_universe.build()
            universe = built["tickers"]
            universe_sources = built["sources"]
        elif mode == "dynamic":
            built = universe_builder.build(DEFAULT_UNIVERSE)
            universe = built["tickers"]
            universe_sources = built["sources"]
        else:
            mode = "core"
            universe = DEFAULT_UNIVERSE
            universe_sources = {"core": list(DEFAULT_UNIVERSE)}
    weights = weights or SWING_WEIGHTS

    cache_key = hashlib.sha1(
        json.dumps(
            {
                "universe": universe,
                "weights": weights,
                "min_score": min_score,
                "limit": limit,
                "prefilter_n": prefilter_n,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]

    if not force_refresh:
        age = _cache.age_seconds("swing_scans", cache_key)
        if age is not None and age < SCAN_CACHE_MAX_AGE:
            cached = _cache.get("swing_scans", cache_key, SCAN_CACHE_MAX_AGE)
            if cached:
                cached["cached"] = True
                cached["cache_age_seconds"] = round(age, 1)
                cached["cache_stale"] = age > SCAN_CACHE_FRESH_TTL
                if cached["cache_stale"]:
                    _maybe_refresh_in_background(
                        cache_key,
                        tickers=tickers,
                        weights=weights,
                        max_workers=max_workers,
                        min_score=min_score,
                        limit=limit,
                        universe_mode=mode,
                        prefilter_n=prefilter_n,
                    )
                return cached

    # Pull SPY once for the relative-strength factor — used by every ticker.
    try:
        spy_prices = prices.fetch("SPY", period="1y")
    except Exception:
        spy_prices = None

    regime: dict[str, Any]
    try:
        regime = regime_data.fetch()
    except Exception as e:
        regime = {"regime": "unknown", "multiplier": 1.0, "error": str(e)}

    # Stage 1 — for large universes, prefilter on a cheap price-only score so we
    # only pay for full enrichment on the strongest trends.
    scan_list = universe
    prefiltered = False
    if not tickers and len(universe) > prefilter_n:
        scan_list = _prefilter_price_only(universe, spy_prices, prefilter_n, max_workers)
        prefiltered = True

    results = []
    errors = []

    # Stage 2 — full scoring + trade plan on the survivors.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(score_ticker_swing, t, spy_prices, weights): t for t in scan_list
        }
        for fut in concurrent.futures.as_completed(future_map):
            t = future_map[fut]
            try:
                res = fut.result()
                if not res["excluded"]:
                    results.append(res)
                else:
                    errors.append({"ticker": t, "reason": res["exclude_reason"]})
            except Exception as e:
                errors.append({"ticker": t, "reason": f"swing_scan_error: {e}"})

    # Apply regime multiplier — swings also fade in risk-off
    regime_mult = regime.get("multiplier", 1.0)
    if regime_mult != 1.0:
        for r in results:
            r["score_pre_regime"] = r["score"]
            r["score"] = round(r["score"] * regime_mult, 1)

    results.sort(key=lambda r: r["score"], reverse=True)
    filtered = [r for r in results if r["score"] >= min_score][:limit]

    output = {
        "as_of": datetime.now(UTC).isoformat(),
        "universe_mode": mode,
        "universe_size": len(universe),
        "universe_sources": universe_sources,
        "prefiltered_to": len(scan_list) if prefiltered else None,
        "scored": len(results),
        "returned": len(filtered),
        "weights": weights,
        "regime": regime,
        "min_score": min_score,
        "results": filtered,
        "excluded": errors,
        "cached": False,
    }
    _cache.put("swing_scans", cache_key, output)

    # Persist a forward-return snapshot so swing fidelity can accrue over time.
    # Records the full scored set (not just the returned top-N) so the backtest
    # has score dispersion to bucket. Best-effort: never fail a scan on this.
    with contextlib.suppress(Exception):
        record_swing_snapshot({**output, "results": results})

    return output
