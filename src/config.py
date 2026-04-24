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
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "squeeze-finder local")

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
    "GME", "AMC", "BBAI", "SOFI", "PLTR", "HOOD", "RIVN", "LCID", "NKLA",
    "MARA", "RIOT", "CLSK", "HUT", "BTBT",
    "CVNA", "WOLF", "UPST", "OPEN", "SKLZ", "FUBO",
    "SPCE", "RKLB", "ASTS", "JOBY", "ACHR",
    "IONQ", "QBTS", "RGTI", "QUBT",
    "TLRY", "CGC", "ACB", "SNDL",
    "BYND", "PTON", "WKHS", "BLNK", "CHPT",
    "MSTR", "COIN",
    "PRPL", "ARCT", "GNUS",
    "BILL", "AI", "SMCI", "IREN",
]
