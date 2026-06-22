from __future__ import annotations

import concurrent.futures
import hashlib
import json
import threading
import time
from datetime import UTC, datetime
from typing import Any

from src.config import (
    ALPHAVANTAGE_API_KEY,
    DEFAULT_UNIVERSE,
    DEFAULT_WEIGHTS,
    FINNHUB_API_KEY,
    INNER_FETCH_CONCURRENCY,
)
from src.data import (
    _cache,
    apewisdom,
    catalysts,
    dilution,
    finra,
    ftd,
    fundamentals,
    iborrowdesk,
    insiders,
    inst_holders,
    options,
    prices,
    regsho,
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
    """Fetch all data sources for a ticker in parallel (small inner pool).

    Yfinance is still the main throttle risk, so we keep INNER_FETCH_CONCURRENCY
    modest (default 5). This overlaps I/O for StockTwits, EDGAR, Finnhub, etc.
    while the outer ThreadPoolExecutor (max_workers=16) handles ticker-level
    parallelism.
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
        "iborrowdesk": lambda: iborrowdesk.fetch(ticker),
        "regsho": lambda: regsho.fetch(ticker),
        "ftd": lambda: ftd.fetch(ticker),   # SEC Fails-to-Deliver — powerful free signal
    }

    timings = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=INNER_FETCH_CONCURRENCY
    ) as pool:
        future_to_name = {pool.submit(fn): name for name, fn in sources.items()}
        for future in concurrent.futures.as_completed(future_to_name):
            name = future_to_name[future]
            t0 = time.time()
            try:
                bundle[name] = future.result()
            except DataUnavailable as e:
                bundle[name] = None
                bundle["errors"][name] = str(e)
            except Exception as e:
                bundle[name] = None
                bundle["errors"][name] = f"unexpected: {e}"
            timings[name] = round((time.time() - t0) * 1000)
    bundle["fetch_timings_ms"] = timings
    return bundle


def score_ticker(ticker: str, weights: dict | None = None) -> dict[str, Any]:
    bundle = fetch_ticker_bundle(ticker)
    excluded, red_flag = is_red_flag(bundle)

    factors = compute_all(bundle)
    score = composite(factors, weights, fund=bundle.get("fundamentals"))
    flags = collect_flags(factors)
    if red_flag:
        flags.append(f"risk:{red_flag}")
        if red_flag == "late_party":
            score = max(0, score - 30)
        elif red_flag == "post_blowoff":
            score = max(0, score - 25)

    # Dilution risk — a pending offering (424B*) or fresh S-1 will kill any
    # squeeze setup overnight. Treat as a score demote, sized by severity.
    # A fresh 8-K Item 3.02 (Unregistered Equity Sale) inside 48h is the
    # canonical "thesis is dead" signal — most squeezes die on this filing.
    # Zero the composite outright rather than apply a -35 demote.
    dil = bundle.get("dilution") or {}
    dil_severity = dil.get("severity") or "low"
    if dil.get("fresh_8k_dilutive"):
        flags.append("risk:dilution_8k_fresh")
        score = 0  # thesis just died — let calibration prove this is right later
    elif dil_severity == "critical":
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
        "fetch_timings_ms": bundle.get("fetch_timings_ms", {}),
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
    min_pressure: float = 0,
    limit: int = 20,
    force_refresh: bool = False,
    dynamic_universe: bool = True,
    sort_by: str = "composite",  # "composite" | "pressure"
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
            {
                "universe": universe,
                "weights": weights,
                "min_score": min_score,
                "min_pressure": min_pressure,
                "limit": limit,
                "sort_by": sort_by,
            },
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
                        min_pressure=min_pressure,
                        limit=limit,
                        dynamic_universe=dynamic_universe,
                        sort_by=sort_by,
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

    # Apply regime multiplier — squeezes don't survive risk-off. Hits both
    # the linear composite and the multiplicative pressure score.
    regime_mult = regime.get("multiplier", 1.0)
    if regime_mult != 1.0:
        for r in results:
            r["score_pre_regime"] = r["score"]
            r["score"] = round(r["score"] * regime_mult, 1)
            ps = r.get("pressure_score")
            if ps:
                ps["score_pre_regime"] = ps["score"]
                ps["score"] = round(ps["score"] * regime_mult, 1)

    # Sort by requested metric. "best short squeeze setups" (imminent) use
    # sort_by="pressure" — the multiplicative L·G·S signal.
    def _get_pressure(r: dict) -> float:
        ps = r.get("pressure_score") or {}
        return ps.get("score", 0.0) if isinstance(ps, dict) else 0.0

    if sort_by in ("pressure", "pressure_score"):
        results.sort(key=_get_pressure, reverse=True)
        primary_filter_key = "pressure"
        filter_threshold = min_pressure
    else:
        results.sort(key=lambda r: r.get("score", 0), reverse=True)
        primary_filter_key = "composite"
        filter_threshold = min_score

    # Filter on the chosen primary metric (min_score always applies to composite
    # for quality floor; min_pressure is additional when sorting by pressure).
    if primary_filter_key == "pressure":
        filtered = [
            r
            for r in results
            if (r.get("score", 0) >= min_score)
            and (_get_pressure(r) >= filter_threshold)
        ][:limit]
    else:
        filtered = [r for r in results if r.get("score", 0) >= filter_threshold][:limit]

    # Optional lightweight Alpha Vantage enrichment (only on top results, only if key present)
    if ALPHAVANTAGE_API_KEY:
        try:
            from src.data.alphavantage import enrich_top_results
            filtered = enrich_top_results(filtered, top_n=min(5, len(filtered)))
        except Exception as e:
            logger.debug("Alpha Vantage enrichment skipped: %s", e)

    # Finnhub enrichment — excellent free tier (60/min). Strong option for
    # reliable quotes + fundamentals. Run on more results than AV.
    if FINNHUB_API_KEY:
        try:
            from src.data.finnhub import enrich_top_results as finnhub_enrich
            filtered = finnhub_enrich(filtered, top_n=min(10, len(filtered)))
        except Exception as e:
            logger.debug("Finnhub enrichment skipped: %s", e)

    # Quality gate for "right signals": when sorting by pressure, require
    # meaningful pressure + some evidence of real short/settlement stress.
    # This prevents low-quality noise even if someone has decent composite.
    pre_gate_count = len(filtered)
    if sort_by in ("pressure", "pressure_score"):
        filtered = [
            r for r in filtered
            if _get_pressure(r) >= max(15, filter_threshold)  # require real pressure
            and (
                (r.get("ftd") or {}).get("latest_ftd", 0) > 50000  # some actual FTDs
                or (r.get("pressure_score") or {}).get("components", {}).get("lending", 0) > 20
            )
        ]
    quality_gate_filtered = pre_gate_count - len(filtered)

    output = {
        "as_of": datetime.now(UTC).isoformat(),
        "universe_size": len(universe),
        "universe_sources": universe_sources,
        "scored": len(results),
        "returned": len(filtered),
        "quality_gate_filtered": quality_gate_filtered,
        "weights": weights,
        "regime": regime,
        "min_score": min_score,
        "min_pressure": min_pressure,
        "sort_by": sort_by,
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
