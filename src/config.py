from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DEEPDIVE_DIR = DATA_DIR / "deepdives"
SCREEN_DIR = DATA_DIR / "screens"
IDEAS_LOG = DATA_DIR / "ideas.jsonl"

for d in (CACHE_DIR, DEEPDIVE_DIR, SCREEN_DIR):
    d.mkdir(parents=True, exist_ok=True)

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Analyst-narrative models (OpenRouter), tried in order — first valid JSON wins.
# Defaults to FREE models that support JSON-mode output. Fallback ordering
# matters more here than with a paid model: free endpoints rate-limit and go
# offline, so a diverse chain (different providers) keeps narratives working.
# Override with OPENROUTER_MODELS=comma,separated,ids — e.g. set it back to
# "anthropic/claude-haiku-4.5" to use the paid model. Free models still require
# an OPENROUTER_API_KEY (a free OpenRouter account).
# Free model chain for all agentic LLM calls. Text/instruction-tuned models
# lead (Gemma, then Qwen-instruct) for more natural narrative prose than the
# reasoning models; nemotron-3-super-120b is the reliable safety net so a
# narrative never fails. Free Gemma/Qwen are popular and 429 often, so the
# fallback frequently serves — that's expected. Override via OPENROUTER_MODELS
# (e.g. anthropic/claude-haiku-4.5 for a paid, always-on text model). All must
# support JSON-mode output. Needs an OPENROUTER_API_KEY.
_DEFAULT_OPENROUTER_MODELS = (
    "google/gemma-4-31b-it:free,"
    "qwen/qwen3-next-80b-a3b-instruct:free,"
    "nvidia/nemotron-3-super-120b-a12b:free"
)
OPENROUTER_MODELS = [
    m.strip()
    for m in os.getenv("OPENROUTER_MODELS", _DEFAULT_OPENROUTER_MODELS).split(",")
    if m.strip()
]
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "squeeze-finder local")
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")

CACHE_TTL = {
    "prices_intraday": 300,
    "prices_eod": 86400,
    "fundamentals": 604800,
    "si": 86400 * 3,
    "options": 900,
    "stocktwits": 600,
    "earnings": 21600,
    "finra": 21600,
}

STALE_THRESHOLD_DAYS = {
    "si": 20,
    "prices": 1,
    "options": 1 / 24,
    "stocktwits": 1 / 24,
    "earnings": 1,
}

DEFAULT_WEIGHTS = {
    "sentiment": 0.30,
    "options": 0.25,
    "si": 0.20,
    "ta": 0.15,
    "catalyst": 0.10,
}

DEFAULT_UNIVERSE = [
    "GME", "AMC", "BBAI", "SOFI", "PLTR", "HOOD",
    "MARA", "RIOT", "CLSK",
    "CVNA", "WOLF", "UPST",
    "RKLB", "ASTS",
    "IONQ",
    "MSTR", "COIN",
    "ARCT",
    "SMCI", "IREN",
]

# Concurrency for fetching the ~10-12 data sources *inside* one ticker.
# Small value to avoid hammering yfinance (the main throttle) while still
# overlapping I/O for StockTwits, EDGAR, Finnhub, etc.
INNER_FETCH_CONCURRENCY = 5
