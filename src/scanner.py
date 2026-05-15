from __future__ import annotations

import concurrent.futures
import hashlib
import json
import threading
from datetime import UTC, datetime
from typing import Any

from src.config import DEFAULT_UNIVERSE, DEFAULT_WEIGHTS
from src.data import (
    _cache,
    apewisdom,
    catalysts,
    dilution,
    finra,
    fundamentals,
    insiders,
    inst_holders,
    options,
    prices,
    stocktwits,
)
from src.data import (
    regime as regime_data,
)
from src.data import universe as universe_builder
from src.data.prices import DataUnavailable
from src.score.backtest import record_snapshot
from src.score.composite import collect_flags, composite, is_red_flag
from src.score.factors import compute_all
from src.score.pressure import compute as compute_pressure

SCAN_CACHE_FRESH_TTL = 600   # 10 min — under this age, served as fresh, no refresh
SCAN_CACHE_MAX_AGE = 3600    # 1 hour — beyond this, treat as missing and full-refetch
# Stale-while-revalidate: between FRESH_TTL and MAX_AGE, serve cached value
# instantly AND fire a background refresh. User never waits for a cold scan.

# In-flight refresh dedupe so simultaneous stale hits don't fire N parallel
# scans against the same cache key.
_in_flight_refreshes: set[str] = set()
_in_flight_lock = threading.Lock()


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
        "dilution": lambda: dilution.fetch(ticker),
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

    # Dilution risk — a pending offering (424B*) or fresh S-1 will kill any
    # squeeze setup overnight. Treat as a score demote, sized by severity.
    dil = bundle.get("dilution") or {}
    dil_severity = dil.get("severity") or "low"
    if dil_severity == "critical":
        flags.append("risk:dilution_critical")
        score = max(0, score - 35)
    elif dil_severity == "high":
        flags.append("risk:dilution_high")
        score = max(0, score - 20)
    elif dil_severity == "moderate":
        flags.append("risk:dilution_shelf")
        score = max(0, score - 8)

    pressure = compute_pressure(bundle)
    if pressure["score"] >= 70:
        flags.append("pressure:red_alert")
    elif pressure["score"] >= 50:
        flags.append("pressure:high")

    fund = bundle.get("fundamentals") or {}
    prices_data = bundle.get("prices") or {}

    return {
        "ticker": ticker,
        "name": fund.get("name", ticker),
        "price": fund.get("price") or prices_data.get("close"),
        "market_cap": fund.get("market_cap"),
        "score": score,
        "pressure_score": pressure,
        "factors": factors,
        "flags": flags,
        "excluded": excluded,
        "exclude_reason": red_flag if excluded else None,
        "as_of": datetime.now(UTC).isoformat(),
        "errors": bundle.get("errors", {}),
    }


def _maybe_refresh_in_background(cache_key: str, **scan_kwargs: Any) -> None:
    """Fire a background scan refresh, deduped per cache_key."""
    with _in_flight_lock:
        if cache_key in _in_flight_refreshes:
            return
        _in_flight_refreshes.add(cache_key)

    def _run() -> None:
        try:
            scan(force_refresh=True, **scan_kwargs)
        except Exception:
            pass
        finally:
            with _in_flight_lock:
                _in_flight_refreshes.discard(cache_key)

    threading.Thread(target=_run, daemon=True, name=f"scan-refresh-{cache_key}").start()


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
        # Stale-while-revalidate: serve any cached value newer than MAX_AGE
        # immediately. If older than FRESH_TTL, fire a background refresh
        # (deduped via _in_flight_refreshes) so the next request gets fresh.
        age = _cache.age_seconds("scans", cache_key)
        if age is not None and age < SCAN_CACHE_MAX_AGE:
            cached = _cache.get("scans", cache_key, SCAN_CACHE_MAX_AGE)
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

    # One regime read per scan, applied to every ticker as a multiplier on
    # the composite. Soft-fail: in risk-off we want to *down-weight* the
    # whole scan, but if the regime fetcher itself fails we run as risk_on.
    regime: dict[str, Any]
    try:
        regime = regime_data.fetch()
    except Exception as e:
        regime = {"regime": "unknown", "multiplier": 1.0, "error": str(e)}

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

    # Apply regime multiplier — squeezes don't survive risk-off.
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
    _cache.put("scans", cache_key, output)

    try:
        record_snapshot({**output, "results": results})
    except Exception:
        pass

    return output
