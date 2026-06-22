from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger("squeeze-finder")

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

from src import tracker
from src.analyst.openrouter import (
    OpenRouterError,
    facts_block,
    facts_block_quicktake,
    facts_block_zero_dte,
    generate_narrative,
    generate_quicktake,
    generate_zero_dte_narrative,
)
from src.config import DEFAULT_UNIVERSE, DEFAULT_WEIGHTS, CACHE_DIR, FINNHUB_API_KEY
from src.data import _cache, prices
from src.data.prices import DataUnavailable
from src.options.recommender import recommend as recommend_options
from src.options.zero_dte_scorer import screen_universe as screen_zero_dte
from src.scanner import scan, score_ticker
from src.score.swing_factors import SWING_WEIGHTS
from src.swing_scanner import swing_scan

NARRATIVE_CACHE_TTL = 1800


def _prewarm_scan() -> None:
    """Background warm-up on server start so the first homepage hit is fast."""
    t0 = time.time()
    try:
        result = scan(limit=25)
        logger.info(
            "prewarm done in %.1fs · scored=%d returned=%d",
            time.time() - t0,
            result.get("scored", 0),
            result.get("returned", 0),
        )
    except Exception as e:
        logger.warning("prewarm failed: %s", e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("SQUEEZE_PREWARM", "1") != "0":
        logger.info("kicking off background prewarm scan...")
        threading.Thread(target=_prewarm_scan, daemon=True, name="prewarm").start()

    # Background periodic refresher for FTD (best free settlement signal) + clinical catalysts
    def _start_periodic_refresh():
        import time
        def _refresher():
            while True:
                try:
                    from src.data import ftd as ftd_mod
                    ftd_mod.refresh()
                    logger.info("Periodic FTD + catalyst refresh completed (catalysts will refresh on next access)")
                except Exception as e:
                    logger.debug("Periodic refresh skipped: %s", e)
                time.sleep(6 * 3600)  # every 6 hours
        t = threading.Thread(target=_refresher, daemon=True, name="ftd-clinical-refresher")
        t.start()

    _start_periodic_refresh()
    yield


app = FastAPI(title="squeeze-finder", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "universe": len(DEFAULT_UNIVERSE),
        "cors_origins": CORS_ORIGINS,
    }


@app.get("/api/scan")
def scan_endpoint(
    limit: int = Query(20, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    min_pressure: float = Query(0, ge=0, le=100),
    sort_by: str = Query("composite", description="composite (default, discovery) or pressure (imminent best setups)"),
    tickers: str | None = Query(None, description="comma-separated override of default universe"),
    w_sentiment: float = Query(DEFAULT_WEIGHTS["sentiment"], ge=0, le=1),
    w_options: float = Query(DEFAULT_WEIGHTS["options"], ge=0, le=1),
    w_si: float = Query(DEFAULT_WEIGHTS["si"], ge=0, le=1),
    w_ta: float = Query(DEFAULT_WEIGHTS["ta"], ge=0, le=1),
    w_catalyst: float = Query(DEFAULT_WEIGHTS["catalyst"], ge=0, le=1),
) -> dict:
    weights = {
        "sentiment": w_sentiment,
        "options": w_options,
        "si": w_si,
        "ta": w_ta,
        "catalyst": w_catalyst,
    }
    total = sum(weights.values())
    if abs(total - 1.0) > 0.001:
        weights = {k: v / total for k, v in weights.items()}

    universe = None
    if tickers:
        universe = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    return scan(
        tickers=universe,
        weights=weights,
        min_score=min_score,
        min_pressure=min_pressure,
        limit=limit,
        sort_by=sort_by,
    )


@app.get("/api/ticker/{symbol}")
def ticker_endpoint(symbol: str) -> dict:
    symbol = symbol.upper()
    # Fast fail for clearly bad/delisted tickers when we have Finnhub
    if FINNHUB_API_KEY:
        try:
            from src.data.finnhub import is_valid_ticker
            if not is_valid_ticker(symbol):
                raise HTTPException(status_code=404, detail=f"ticker not found or delisted: {symbol}")
        except HTTPException:
            raise
        except Exception:
            pass  # don't block on check failure

    try:
        result = score_ticker(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if result.get("excluded"):
        raise HTTPException(status_code=422, detail=f"excluded: {result.get('exclude_reason')}")
    return {**result, "weights": DEFAULT_WEIGHTS}


QUICKTAKE_CACHE_TTL = 1800  # 30 min — per-row scan annotations


@app.get("/api/ticker/{symbol}/quicktake")
def quicktake_endpoint(symbol: str) -> dict:
    """One-sentence Haiku take for a scan-table row. Lazy-loaded on click.

    ~$0.001/call, ~2s on cold cache, instant on cached. Different from
    /narrative which is the deeper bull/bear analysis.
    """
    symbol = symbol.upper()
    cached = _cache.get("quicktakes", symbol, QUICKTAKE_CACHE_TTL)
    if cached:
        return {**cached, "cached": True}

    try:
        result = score_ticker(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if result.get("excluded"):
        raise HTTPException(status_code=422, detail=f"excluded: {result.get('exclude_reason')}")

    try:
        out = generate_quicktake(facts_block_quicktake(result))
    except OpenRouterError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    output = {
        "ticker": symbol,
        "score": result["score"],
        "take": out["take"],
        "model_used": out["model_used"],
        "cached": False,
    }
    _cache.put("quicktakes", symbol, output)
    return output


@app.get("/api/ticker/{symbol}/narrative")
def narrative_endpoint(symbol: str) -> dict:
    symbol = symbol.upper()

    cached = _cache.get("narratives", symbol, NARRATIVE_CACHE_TTL)
    if cached:
        return {**cached, "cached": True}

    try:
        result = score_ticker(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if result.get("excluded"):
        raise HTTPException(status_code=422, detail=f"excluded: {result.get('exclude_reason')}")

    try:
        narrative = generate_narrative(facts_block(result))
    except OpenRouterError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    output = {"ticker": symbol, "score": result["score"], "narrative": narrative, "cached": False}
    _cache.put("narratives", symbol, output)
    return output


@app.get("/api/universe")
def universe_endpoint() -> dict:
    return {"tickers": DEFAULT_UNIVERSE, "count": len(DEFAULT_UNIVERSE)}


@app.get("/api/backtest")
def backtest_endpoint(window: int = Query(5, ge=1, le=60)) -> dict:
    """Hit-rate by composite-score decile across recorded scan snapshots.

    Wraps the same logic as `uv run squeeze backtest --window N`. Read-only,
    no cache (snapshots are filesystem-cheap to reread). Used by the
    scheduled weekly digest agent — see /Users/rash/squeeze-finder docs.
    """
    from src.score.backtest import evaluate as backtest_evaluate

    return backtest_evaluate(window_days=window)


CALIBRATION_CACHE_TTL = 3600  # 1h — snapshots are immutable; recompute hourly


@app.get("/api/calibration")
def calibration_endpoint(
    window: int = Query(5, ge=1, le=60),
    threshold: float = Query(10.0, ge=1.0, le=100.0, description="max drawup % defining a win"),
    buckets: int = Query(10, ge=4, le=20),
) -> dict:
    """Brier-score decomposition + reliability diagram for composite & pressure.

    Returns {composite, pressure} each with brier, reliability, resolution,
    skill, lift_at_top_decile, spearman_ic, and per-bucket reliability rows.
    Use to verify each P0/P1 change actually improves calibration — not
    just absolute returns.

    Cached 1h since the underlying scan snapshots are immutable on disk.
    First call across many tickers blows past nginx's 180s timeout
    (forward-return computation hits prices.fetch per snapshot); cache
    serves subsequent requests instantly.
    """
    cache_key = f"w{window}_t{threshold}_b{buckets}"
    cached = _cache.get("calibration", cache_key, CALIBRATION_CACHE_TTL)
    if cached:
        return {**cached, "cached": True}

    from src.score.calibration import evaluate as calibration_evaluate

    result = calibration_evaluate(
        window_days=window,
        win_threshold_pct=threshold,
        n_buckets=buckets,
    )
    _cache.put("calibration", cache_key, result)
    return {**result, "cached": False}


@app.get("/api/swing-scan")
def swing_scan_endpoint(
    limit: int = Query(25, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    tickers: str | None = Query(None, description="comma-separated override of default universe"),
    w_stage2: float = Query(SWING_WEIGHTS["stage2"], ge=0, le=1),
    w_breakout: float = Query(SWING_WEIGHTS["breakout"], ge=0, le=1),
    w_rs: float = Query(SWING_WEIGHTS["rs"], ge=0, le=1),
    w_catalyst: float = Query(SWING_WEIGHTS["catalyst"], ge=0, le=1),
    w_smart_money: float = Query(SWING_WEIGHTS["smart_money"], ge=0, le=1),
) -> dict:
    """Swing-trade scan: Stage-2 trend + volume-confirmed breakout + RS vs SPY +
    catalyst + smart-money confirm. Catches multi-week trend continuations
    (INTC-style AI rally, SNDK-style memory breakout) early."""
    weights = {
        "stage2": w_stage2,
        "breakout": w_breakout,
        "rs": w_rs,
        "catalyst": w_catalyst,
        "smart_money": w_smart_money,
    }
    total = sum(weights.values())
    if abs(total - 1.0) > 0.001:
        weights = {k: v / total for k, v in weights.items()}

    universe = None
    if tickers:
        universe = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    return swing_scan(tickers=universe, weights=weights, min_score=min_score, limit=limit)


@app.get("/api/zero-dte")
def zero_dte_endpoint(top_per_side: int = Query(3, ge=1, le=10), refresh: bool = False) -> dict:
    """Same-day-expiry options ranked by 2x/5x/10x payoff probability.

    Restricted to mega-caps + major-index ETFs and gated to RTH 9:45a–3:30p ET.
    Outside that window, returns ok=false with a blocked_reason.
    """
    try:
        return screen_zero_dte(top_per_side=top_per_side, force_refresh=refresh)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"zero-dte screen failed: {e}") from e


ZERO_DTE_NARRATIVE_TTL = 300  # 5 min — 0DTE quotes move fast


@app.get("/api/zero-dte/{ticker}/narrative")
def zero_dte_narrative_endpoint(ticker: str) -> dict:
    """Haiku tactical analysis of one ticker's 0DTE chain. Cached 5 min."""
    ticker = ticker.upper()
    cached = _cache.get("zero_dte_narratives", ticker, ZERO_DTE_NARRATIVE_TTL)
    if cached:
        return {**cached, "cached": True}

    screen = screen_zero_dte(top_per_side=3)
    if not screen.get("ok"):
        raise HTTPException(
            status_code=422,
            detail=f"screener parked: {screen.get('blocked_reason')}",
        )

    ranked = next((r for r in screen["results"] if r["ticker"] == ticker), None)
    if not ranked or not (ranked["calls"] or ranked["puts"]):
        raise HTTPException(status_code=404, detail=f"no 0DTE candidates for {ticker}")

    facts = facts_block_zero_dte(ranked)
    try:
        narrative = generate_zero_dte_narrative(facts)
    except OpenRouterError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    output = {
        "ticker": ticker,
        "as_of": ranked["as_of"],
        "spot": ranked["spot"],
        "expiry": ranked["expiry"],
        "narrative": narrative,
        "cached": False,
    }
    _cache.put("zero_dte_narratives", ticker, output)
    return output


@app.get("/api/ticker/{symbol}/options")
def options_recommendations(symbol: str, top: int = 8) -> dict:
    symbol = symbol.upper()
    try:
        return recommend_options(symbol, top_n=top)
    except DataUnavailable as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"options recommender failed: {e}") from e


@app.get("/api/ticker/{symbol}/chart")
def chart_endpoint(symbol: str, period: str = "3mo") -> dict:
    """OHLCV + trade levels: ATR-risk SL/TP snapped to volume-profile S/R."""
    from src.score.levels import compute_chart_levels

    symbol = symbol.upper()
    try:
        p = prices.fetch(symbol, period=period)
    except DataUnavailable as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    bars = p.get("bars") or []
    if not bars:
        raise HTTPException(status_code=404, detail=f"no bars for {symbol}")

    return {
        "ticker": symbol,
        "period": period,
        "as_of": p.get("as_of"),
        "bars": bars,
        "levels": compute_chart_levels(bars),
    }


# ------------- tracker -------------


class OpenIdeaBody(BaseModel):
    ticker: str
    thesis: str
    invalidation: str
    time_stop: str | None = None
    force: bool = False
    notes: str = ""


class CloseIdeaBody(BaseModel):
    close_reason: str
    exit_ref_price: float | None = None
    peak_drawup_pct: float | None = None
    peak_drawdown_pct: float | None = None


class PostmortemBody(BaseModel):
    outcome: str
    return_ref_pct: float | None = None
    what_worked: str
    what_missed: str
    factor_calibration: dict[str, str]
    lesson: str


@app.get("/api/ideas")
def list_ideas_endpoint(status: str | None = Query(None)) -> dict:
    ideas = tracker.list_ideas()
    if status:
        ideas = [i for i in ideas if i["status"] == status]
    return {"count": len(ideas), "ideas": ideas}


@app.get("/api/ideas/{idea_id}")
def get_idea_endpoint(idea_id: str) -> dict:
    idea = tracker.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail=f"no idea {idea_id}")
    return idea


@app.post("/api/ideas")
def open_idea_endpoint(body: OpenIdeaBody) -> dict:
    ticker = body.ticker.upper()
    try:
        result = score_ticker(ticker)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"score_ticker failed: {e}") from e

    try:
        event = tracker.open_idea(
            ticker=ticker,
            ticker_result=result,
            thesis=body.thesis,
            invalidation=body.invalidation,
            time_stop=body.time_stop,
            force=body.force,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return event


@app.post("/api/ideas/{idea_id}/close")
def close_idea_endpoint(idea_id: str, body: CloseIdeaBody) -> dict:
    try:
        return tracker.close_idea(
            idea_id=idea_id,
            close_reason=body.close_reason,
            exit_ref_price=body.exit_ref_price,
            peak_drawup_pct=body.peak_drawup_pct,
            peak_drawdown_pct=body.peak_drawdown_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/ideas/{idea_id}/postmortem")
def postmortem_endpoint(idea_id: str, body: PostmortemBody) -> dict:
    try:
        return tracker.postmortem(
            idea_id=idea_id,
            outcome=body.outcome,
            return_ref_pct=body.return_ref_pct,
            what_worked=body.what_worked,
            what_missed=body.what_missed,
            factor_calibration=body.factor_calibration,
            lesson=body.lesson,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
