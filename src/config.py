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

# ------------- Paper-trading bot (Alpaca) -------------
# PAPER ONLY. The bot uses the paper endpoint unless ALPACA_PAPER=false is set
# explicitly AND the runner is invoked with an explicit live flag (not enabled
# in this build). Free paper keys: https://alpaca.markets → Paper Trading.
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() != "false"  # default: paper
BOT_TRADES_LOG = DATA_DIR / "bot_trades.jsonl"

# Hard risk caps — checked before every order. Override via env.
BOT_PARAMS = {
    "risk_pct_per_trade": float(os.getenv("BOT_RISK_PCT", "1.0")),       # % equity risked/trade (= premium for long calls)
    "max_open_positions": int(os.getenv("BOT_MAX_POSITIONS", "5")),
    "max_daily_loss_pct": float(os.getenv("BOT_MAX_DAILY_LOSS_PCT", "3.0")),
    "max_deploy_pct": float(os.getenv("BOT_MAX_DEPLOY_PCT", "20.0")),    # total premium-at-risk cap
    "min_setup_score": float(os.getenv("BOT_MIN_SCORE", "50")),
    "option_tp_pct": float(os.getenv("BOT_OPTION_TP_PCT", "100")),       # take profit at +100% premium
    "option_sl_pct": float(os.getenv("BOT_OPTION_SL_PCT", "50")),        # stop at -50% premium
    "time_stop_dte": int(os.getenv("BOT_TIME_STOP_DTE", "7")),          # close at <= 7 DTE (theta cliff)
    "default_equity": float(os.getenv("BOT_DEFAULT_EQUITY", "100000")),  # dry-run sizing when no Alpaca account
}

# ------------- Spot-crypto momentum bot (Alpaca) -------------
# PAPER ONLY, same paper account + AlpacaClient as the options bot. Spot crypto
# is plain long exposure (no leverage / liquidation / funding), so risk is
# defined: max loss = notional bought. Sizing is risk-normalized to the ATR/
# volume stop. Crypto trades 24/7 — the crypto runner has no market-hours gate.
# Candidate universe: liquid USD-quoted majors; intersected with Alpaca's live
# tradable set at runtime and skipped if yfinance lacks history.
CRYPTO_UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD", "LTC/USD",
    "BCH/USD", "UNI/USD", "AAVE/USD", "DOGE/USD", "XRP/USD", "DOT/USD",
    "MKR/USD", "CRV/USD", "XTZ/USD", "GRT/USD", "SHIB/USD", "YFI/USD",
    "SUSHI/USD", "BAT/USD",
]

# Hard risk caps for the crypto bot — checked before every order. Override via env.
CRYPTO_BOT_PARAMS = {
    "risk_pct_per_trade": float(os.getenv("CRYPTO_RISK_PCT", "1.0")),        # % equity risked to the stop
    "max_open_positions": int(os.getenv("CRYPTO_MAX_POSITIONS", "5")),
    "max_daily_loss_pct": float(os.getenv("CRYPTO_MAX_DAILY_LOSS_PCT", "5.0")),
    "max_deploy_pct": float(os.getenv("CRYPTO_MAX_DEPLOY_PCT", "30.0")),     # total notional-at-risk cap
    "max_position_pct": float(os.getenv("CRYPTO_MAX_POSITION_PCT", "10.0")), # per-name notional cap
    "min_setup_score": float(os.getenv("CRYPTO_MIN_SCORE", "55")),          # momentum composite floor
    "time_stop_days": int(os.getenv("CRYPTO_TIME_STOP_DAYS", "21")),        # close after N days held
    "min_notional": float(os.getenv("CRYPTO_MIN_NOTIONAL", "10")),          # skip orders below this
    "default_equity": float(os.getenv("CRYPTO_DEFAULT_EQUITY", "100000")),  # dry-run sizing fallback
}

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
