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

from src import tracker
from src.analyst.openrouter import OpenRouterError, facts_block, generate_narrative
from src.config import DEFAULT_UNIVERSE, DEFAULT_WEIGHTS
from src.data import _cache, prices
from src.data.prices import DataUnavailable
from src.options.recommender import recommend as recommend_options
from src.scanner import scan, score_ticker

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
    yield


app = FastAPI(title="squeeze-finder", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "universe": len(DEFAULT_UNIVERSE)}


@app.get("/api/scan")
def scan_endpoint(
    limit: int = Query(20, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
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

    return scan(tickers=universe, weights=weights, min_score=min_score, limit=limit)


@app.get("/api/ticker/{symbol}")
def ticker_endpoint(symbol: str) -> dict:
    symbol = symbol.upper()
    try:
        result = score_ticker(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if result.get("excluded"):
        raise HTTPException(status_code=422, detail=f"excluded: {result.get('exclude_reason')}")
    return result


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
    """OHLCV + computed trade levels (entry, stop, 60d breakout, 2x/5x/10x targets)."""
    symbol = symbol.upper()
    try:
        p = prices.fetch(symbol, period=period)
    except DataUnavailable as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    bars = p.get("bars") or []
    if not bars:
        raise HTTPException(status_code=404, detail=f"no bars for {symbol}")

    last = bars[-1]["close"]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    prior_high_60 = max(highs[-61:-1]) if len(highs) >= 61 else max(highs[:-1] or highs)
    recent_low_20 = min(lows[-20:]) if len(lows) >= 20 else min(lows)
    stop = max(recent_low_20, last * 0.92)

    levels = {
        "entry": round(last, 2),
        "stop": round(stop, 2),
        "breakout_60d": round(prior_high_60, 2),
        "target_2x": round(last * 2, 2),
        "target_5x": round(last * 5, 2),
        "target_10x": round(last * 10, 2),
    }

    return {
        "ticker": symbol,
        "period": period,
        "as_of": p.get("as_of"),
        "bars": bars,
        "levels": levels,
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
