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
import hashlib
import json
import threading
from datetime import UTC, datetime
from typing import Any

from src.config import DEFAULT_UNIVERSE
from src.data import (
    _cache,
    catalysts,
    fundamentals,
    insiders,
    inst_holders,
    prices,
)
from src.data import (
    regime as regime_data,
)
from src.data import universe as universe_builder
from src.data.prices import DataUnavailable
from src.score.composite import is_red_flag
from src.score.swing_factors import (
    SWING_WEIGHTS,
    collect_swing_flags,
    composite_swing,
    compute_swing,
)

SCAN_CACHE_FRESH_TTL = 600
SCAN_CACHE_MAX_AGE = 3600

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
    for name, fn in sources.items():
        try:
            bundle[name] = fn()
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

    fund = bundle.get("fundamentals") or {}
    prices_data = bundle.get("prices") or {}

    return {
        "ticker": ticker,
        "name": fund.get("name", ticker),
        "price": fund.get("price") or prices_data.get("close"),
        "market_cap": fund.get("market_cap"),
        "score": score,
        "factors": factors,
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


def swing_scan(
    tickers: list[str] | None = None,
    weights: dict | None = None,
    max_workers: int = 16,
    min_score: float = 0,
    limit: int = 25,
    force_refresh: bool = False,
    dynamic_universe: bool = True,
) -> dict[str, Any]:
    if tickers:
        universe = tickers
        universe_sources: dict[str, list[str]] = {"override": list(tickers)}
    elif dynamic_universe:
        built = universe_builder.build(DEFAULT_UNIVERSE)
        universe = built["tickers"]
        universe_sources = built["sources"]
    else:
        universe = DEFAULT_UNIVERSE
        universe_sources = {"core": list(DEFAULT_UNIVERSE)}
    weights = weights or SWING_WEIGHTS

    cache_key = hashlib.sha1(
        json.dumps(
            {"universe": universe, "weights": weights, "min_score": min_score, "limit": limit},
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
                        dynamic_universe=dynamic_universe,
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

    results = []
    errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(score_ticker_swing, t, spy_prices, weights): t for t in universe
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
        "universe_size": len(universe),
        "universe_sources": universe_sources,
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
    return output
