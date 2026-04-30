from __future__ import annotations

import concurrent.futures
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from src.config import DEFAULT_UNIVERSE, DEFAULT_WEIGHTS
from src.data import (
    _cache,
    apewisdom,
    catalysts,
    finra,
    fundamentals,
    insiders,
    options,
    prices,
    stocktwits,
)
from src.data import universe as universe_builder
from src.data.prices import DataUnavailable
from src.score.backtest import record_snapshot
from src.score.composite import collect_flags, composite, is_red_flag
from src.score.factors import compute_all

SCAN_CACHE_TTL = 120  # seconds — serve the same scan config from disk cache


def fetch_ticker_bundle(ticker: str) -> dict[str, Any]:
    """Fetch all data sources for a ticker. Soft-fails per source.
    Kept sequential per-ticker — yfinance throttles heavily on >30 concurrent calls.
    Parallelism is at the outer scan level instead (more tickers at once).
    """
    bundle: dict[str, Any] = {"ticker": ticker, "errors": {}}
    sources = {
        "prices": lambda: prices.fetch(ticker, period="6mo"),
        "fundamentals": lambda: fundamentals.fetch(ticker),
        "options": lambda: options.fetch(ticker),
        "stocktwits": lambda: stocktwits.fetch(ticker),
        "catalysts": lambda: catalysts.fetch(ticker),
        "finra": lambda: finra.fetch(ticker),
        "apewisdom": lambda: apewisdom.fetch(ticker),
        "insiders": lambda: insiders.fetch(ticker),
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


def score_ticker(ticker: str, weights: dict | None = None) -> dict[str, Any]:
    bundle = fetch_ticker_bundle(ticker)
    excluded, red_flag = is_red_flag(bundle)

    factors = compute_all(bundle)
    score = composite(factors, weights)
    flags = collect_flags(factors)
    if red_flag:
        flags.append(f"risk:{red_flag}")
        if red_flag == "late_party":
            score = max(0, score - 30)
        elif red_flag == "post_blowoff":
            score = max(0, score - 25)

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


def scan(
    tickers: list[str] | None = None,
    weights: dict | None = None,
    max_workers: int = 16,
    min_score: float = 0,
    limit: int = 20,
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
    weights = weights or DEFAULT_WEIGHTS

    cache_key = hashlib.sha1(
        json.dumps(
            {"universe": universe, "weights": weights, "min_score": min_score, "limit": limit},
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    if not force_refresh:
        cached = _cache.get("scans", cache_key, SCAN_CACHE_TTL)
        if cached:
            cached["cached"] = True
            return cached

    results = []
    errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(score_ticker, t, weights): t for t in universe}
        for fut in concurrent.futures.as_completed(future_map):
            t = future_map[fut]
            try:
                res = fut.result()
                if not res["excluded"]:
                    results.append(res)
                else:
                    errors.append({"ticker": t, "reason": res["exclude_reason"]})
            except Exception as e:
                errors.append({"ticker": t, "reason": f"scan_error: {e}"})

    results.sort(key=lambda r: r["score"], reverse=True)
    filtered = [r for r in results if r["score"] >= min_score][:limit]

    output = {
        "as_of": datetime.now(UTC).isoformat(),
        "universe_size": len(universe),
        "universe_sources": universe_sources,
        "scored": len(results),
        "returned": len(filtered),
        "weights": weights,
        "min_score": min_score,
        "results": filtered,
        "excluded": errors,
        "cached": False,
    }
    _cache.put("scans", cache_key, output)

    try:
        record_snapshot({**output, "results": results})
    except Exception:
        pass

    return output
