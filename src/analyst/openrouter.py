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
