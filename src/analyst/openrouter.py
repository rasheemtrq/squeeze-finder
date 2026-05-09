"""
OpenRouter client for analyst narrative generation.
Uses Claude Haiku 4.5 — paid; ~$0.004 per narrative call.
Output is always a structured dict: {tldr, bull: [...], bear: [...], model_used}.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from src.config import OPENROUTER_API_KEY

URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS = [
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-haiku-4-5",  # fallback — some routers use dash, not dot
]

SYSTEM = (
    "You are a terse equity analyst. Given a JSON facts block about a potential "
    "short-squeeze candidate, produce a strict JSON response with these keys:\n"
    '  "tldr": a 2-3 sentence thesis (≤60 words)\n'
    '  "bull": 3 short bullets on the squeeze setup (each ≤20 words)\n'
    '  "bear": 3 short bullets on risks and invalidation (each ≤20 words)\n'
    "Rules:\n"
    "- Use ONLY numbers present in the facts block. Do not invent prices, targets, or metrics.\n"
    "- No price targets. No timing predictions beyond scheduled events.\n"
    "- 'bear' must be specific — what breaks the thesis?\n"
    "- Return ONLY the JSON object. No prose before or after. No markdown fences."
)


class OpenRouterError(Exception):
    pass


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def _call(model: str, facts_json: str, timeout: float = 45) -> dict | None:
    if not OPENROUTER_API_KEY:
        raise OpenRouterError("OPENROUTER_API_KEY not set")
    r = httpx.post(
        URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "squeeze-finder",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": facts_json},
            ],
            "temperature": 0.4,
            "max_tokens": 600,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    content = body["choices"][0]["message"]["content"]
    return _extract_json(content)


def _validate(obj: Any) -> dict | None:
    if not isinstance(obj, dict):
        return None
    tldr = obj.get("tldr")
    bull = obj.get("bull")
    bear = obj.get("bear")
    if not isinstance(tldr, str) or not tldr.strip():
        return None
    if not isinstance(bull, list) or not isinstance(bear, list):
        return None
    bull = [str(b).strip() for b in bull if str(b).strip()][:5]
    bear = [str(b).strip() for b in bear if str(b).strip()][:5]
    if not bull or not bear:
        return None
    return {"tldr": tldr.strip(), "bull": bull, "bear": bear}


def generate_narrative(facts: dict) -> dict:
    """Generate via Claude Haiku 4.5 (paid). Tries id variants for routing safety."""
    facts_json = json.dumps(facts, default=str, indent=2)
    last_error = None

    for model in MODELS:
        try:
            raw = _call(model, facts_json)
        except httpx.HTTPStatusError as e:
            last_error = f"{model}: http {e.response.status_code} {e.response.text[:200]}"
            continue
        except Exception as e:
            last_error = f"{model}: {e}"
            continue

        validated = _validate(raw)
        if validated:
            return {**validated, "model_used": model}
        last_error = f"{model}: invalid response shape"

    raise OpenRouterError(f"narrative generation failed; last: {last_error}")


SYSTEM_ZERO_DTE = (
    "You are a tactical 0DTE options analyst. Given a JSON facts block with "
    "today's expiry options chain for a single ticker, return strict JSON:\n"
    '  "tldr": 1-2 sentence read of the chain (≤40 words)\n'
    '  "calls": 1-2 short bullets on the best call setup (each ≤25 words; '
    "reference specific strikes/spots from the facts)\n"
    '  "puts":  1-2 short bullets on the best put setup (each ≤25 words; '
    "reference specific strikes/spots from the facts)\n"
    '  "risk":  1-2 short bullets on 0DTE-specific risks: theta cliff, '
    "liquidity, gap, time stop (each ≤25 words)\n"
    "Rules:\n"
    "- Use ONLY numbers in the facts block (strikes, spots, deltas, P(2x/5x/10x), "
    "TP/SL spot levels, hours_until_close, regime). Do not invent prices.\n"
    "- Be tactical: name the trigger spot, the TP1 and SL spots, and what time "
    "the trade is dead.\n"
    "- If chain_stale=true, say so and recommend waiting.\n"
    "- Return ONLY the JSON object. No prose, no markdown fences."
)


def _call_zero_dte(model: str, facts_json: str, timeout: float = 45) -> dict | None:
    if not OPENROUTER_API_KEY:
        raise OpenRouterError("OPENROUTER_API_KEY not set")
    r = httpx.post(
        URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "squeeze-finder/0dte",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_ZERO_DTE},
                {"role": "user", "content": facts_json},
            ],
            "temperature": 0.4,
            "max_tokens": 700,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    return _extract_json(body["choices"][0]["message"]["content"])


def _validate_zero_dte(obj: Any) -> dict | None:
    if not isinstance(obj, dict):
        return None
    tldr = obj.get("tldr")
    calls = obj.get("calls") or []
    puts = obj.get("puts") or []
    risk = obj.get("risk") or []
    if not isinstance(tldr, str) or not tldr.strip():
        return None
    calls = [str(b).strip() for b in calls if str(b).strip()][:4]
    puts = [str(b).strip() for b in puts if str(b).strip()][:4]
    risk = [str(b).strip() for b in risk if str(b).strip()][:4]
    if not (calls or puts):
        return None
    return {
        "tldr": tldr.strip(),
        "calls": calls,
        "puts": puts,
        "risk": risk,
    }


def generate_zero_dte_narrative(facts: dict) -> dict:
    """Generate Haiku 0DTE analysis. Same routing/fallback shape as squeeze narrative."""
    facts_json = json.dumps(facts, default=str, indent=2)
    last_error = None

    for model in MODELS:
        try:
            raw = _call_zero_dte(model, facts_json)
        except httpx.HTTPStatusError as e:
            last_error = f"{model}: http {e.response.status_code} {e.response.text[:200]}"
            continue
        except Exception as e:
            last_error = f"{model}: {e}"
            continue

        validated = _validate_zero_dte(raw)
        if validated:
            return {**validated, "model_used": model}
        last_error = f"{model}: invalid response shape"

    raise OpenRouterError(f"0DTE narrative generation failed; last: {last_error}")


SYSTEM_QUICKTAKE = (
    "You are a tactical squeeze-trading analyst. Given a JSON facts block "
    "about a single ticker, return strict JSON with exactly this shape:\n"
    '  {"take": "<one sentence, ≤30 words>"}\n'
    "Rules:\n"
    "- ONE sentence describing the current setup in tactical terms.\n"
    "- Lead with the strongest signal (the highest-scoring factor or most-"
    "informative flag).\n"
    "- End with the biggest risk or invalidator (a flag prefixed with risk:, "
    "or what would kill the thesis).\n"
    "- Use ONLY numbers/flags in the facts block. Do not invent prices or "
    "targets.\n"
    "- No price targets. No timing predictions beyond named events.\n"
    "- Return ONLY the JSON object, no prose, no markdown."
)


def _call_quicktake(model: str, facts_json: str, timeout: float = 25) -> dict | None:
    if not OPENROUTER_API_KEY:
        raise OpenRouterError("OPENROUTER_API_KEY not set")
    r = httpx.post(
        URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "squeeze-finder/quicktake",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_QUICKTAKE},
                {"role": "user", "content": facts_json},
            ],
            "temperature": 0.3,
            "max_tokens": 120,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return _extract_json(r.json()["choices"][0]["message"]["content"])


def generate_quicktake(facts: dict) -> dict:
    """One-sentence Haiku take. ~$0.001/call, ~2s latency."""
    facts_json = json.dumps(facts, default=str, indent=2)
    last_error = None
    for model in MODELS:
        try:
            raw = _call_quicktake(model, facts_json)
        except httpx.HTTPStatusError as e:
            last_error = f"{model}: http {e.response.status_code} {e.response.text[:200]}"
            continue
        except Exception as e:
            last_error = f"{model}: {e}"
            continue
        if isinstance(raw, dict) and isinstance(raw.get("take"), str) and raw["take"].strip():
            return {"take": raw["take"].strip(), "model_used": model}
        last_error = f"{model}: invalid response shape"
    raise OpenRouterError(f"quicktake generation failed; last: {last_error}")


def facts_block_quicktake(ticker_result: dict) -> dict:
    """Slim facts block for the per-row quicktake — just enough for one sentence."""
    f = ticker_result.get("factors") or {}
    return {
        "ticker": ticker_result["ticker"],
        "name": ticker_result.get("name"),
        "price": ticker_result.get("price"),
        "composite_score": ticker_result["score"],
        "factors": {
            k: {"score": (f.get(k) or {}).get("score"), "flag": (f.get(k) or {}).get("signals", {}).get("flag")}
            for k in ("sentiment", "options", "si", "ta", "catalyst")
        },
        "flags": ticker_result.get("flags", []),
    }


def facts_block_zero_dte(ranked: dict, regime: dict | None = None) -> dict:
    """Compact facts block for one ticker's 0DTE chain. Strips noisy fields."""
    def _slim(c: dict) -> dict:
        return {
            "side": c["side"],
            "strike": c["strike"],
            "mid": c["mid"],
            "delta": c["delta"],
            "iv": c["iv"],
            "vol": c["volume"],
            "oi": c["open_interest"],
            "p_2x": c["p_2x"],
            "p_5x": c["p_5x"],
            "p_10x": c["p_10x"],
            "tp1_spot": c.get("tp1_spot"),
            "tp2_spot": c.get("tp2_spot"),
            "tp3_spot": c.get("tp3_spot"),
            "sl_spot": c.get("sl_spot"),
            "tp1_price": c.get("tp1_price"),
            "sl_price": c.get("sl_price"),
        }
    return {
        "ticker": ranked["ticker"],
        "spot": ranked["spot"],
        "expiry": ranked["expiry"],
        "hours_until_close": ranked.get("hours_until_close"),
        "chain_stale": ranked.get("chain_stale", False),
        "regime": (regime or {}).get("regime"),
        "vix": (regime or {}).get("vix"),
        "calls": [_slim(c) for c in (ranked.get("calls") or [])[:3]],
        "puts": [_slim(c) for c in (ranked.get("puts") or [])[:3]],
    }


def facts_block(ticker_result: dict) -> dict:
    """Reduce a score_ticker result to the minimal facts block for the LLM."""
    f = ticker_result.get("factors", {})
    return {
        "ticker": ticker_result["ticker"],
        "name": ticker_result.get("name"),
        "price": ticker_result.get("price"),
        "market_cap": ticker_result.get("market_cap"),
        "composite_score": ticker_result["score"],
        "factors": {
            "sentiment": {
                "score": f.get("sentiment", {}).get("score"),
                "signals": f.get("sentiment", {}).get("signals"),
            },
            "options": {
                "score": f.get("options", {}).get("score"),
                "signals": f.get("options", {}).get("signals"),
            },
            "si": {
                "score": f.get("si", {}).get("score"),
                "signals": f.get("si", {}).get("signals"),
            },
            "ta": {
                "score": f.get("ta", {}).get("score"),
                "signals": f.get("ta", {}).get("signals"),
            },
            "catalyst": {
                "score": f.get("catalyst", {}).get("score"),
                "signals": f.get("catalyst", {}).get("signals"),
            },
        },
        "flags": ticker_result.get("flags", []),
    }
