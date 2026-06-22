"""
SEC Fails-to-Deliver (FTD) data — best free high-signal source for settlement pressure.

This follows the correct pattern for this type of data (large, infrequently
updated official government datasets):

- **Ingest** (expensive, rate-limited): Run infrequently (manually or on a
  schedule). Downloads the monthly zip files from SEC, parses them, and builds
  a compact local index of recent FTD history per ticker.

- **Query** (fast, local-only): The scanner calls `fetch()` which is now a
  pure read from the pre-built index. Zero network calls during scans.

Data is published ~2x per month. The signal (persistent/rising FTDs relative
to float) is a strong leading indicator for short squeeze pressure and
complements the existing RegSHO threshold list.

Usage in dev:
  uv run python -m src.cli ftd refresh

In production, run the refresh on a schedule (daily is fine — it will only
actually download when new files are due).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import CACHE_DIR, CACHE_TTL
from src.data import _cache

logger = logging.getLogger(__name__)

RAW_DIR = CACHE_DIR / "ftd_raw"
INDEX_DIR = CACHE_DIR / "ftd_index"
RAW_DIR.mkdir(parents=True, exist_ok=True)
INDEX_DIR.mkdir(parents=True, exist_ok=True)

FTD_LOOKBACK_DAYS = 90  # How much history we keep in the fast index

# Expected publication cadence (approximate)
def _expected_files_for_lookback() -> list[tuple[str, str]]:
    """Return list of (YYYYMM, 'a'/'b') we should have for current lookback."""
    today = date.today()
    start = today - timedelta(days=FTD_LOOKBACK_DAYS + 45)
    files = []
    d = start
    while d <= today + timedelta(days=20):
        ym = d.strftime("%Y%m")
        # First half ('a') published end of month; second half ('b') ~15th next
        files.append((ym, "a"))
        files.append((ym, "b"))
        d += timedelta(days=32)
        d = d.replace(day=1)
    # Dedup while preserving order
    seen = set()
    unique = []
    for item in files:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[-6:]  # Last ~3 months is plenty


def _raw_path(month: str, half: str) -> Path:
    return RAW_DIR / f"cnsfails{month}{half}.zip"


def refresh(force: bool = False) -> dict:
    """
    Download any missing recent FTD monthly files and rebuild the per-ticker index.
    This is the only place network I/O for FTD should happen.
    Returns summary of what was done.
    """
    from . import ftd_downloader  # Local import to avoid circularity during dev

    expected = _expected_files_for_lookback()
    downloaded = []
    for ym, half in expected:
        path = _raw_path(ym, half)
        if not path.exists() or force:
            success = ftd_downloader.download_one(ym, half)
            if success:
                downloaded.append(f"{ym}{half}")

    # Rebuild compact index from all available raw files
    index = _build_index_from_raw(expected)
    index_path = INDEX_DIR / "recent.json"
    index_path.write_text(json.dumps(index, default=str))

    logger.info("FTD refresh complete. Files downloaded: %s", downloaded)
    return {
        "downloaded": downloaded,
        "index_tickers": len(index),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def _build_index_from_raw(expected_files: list) -> dict[str, list[dict]]:
    """Parse raw zips and produce {ticker: [recent FTD records]}."""
    from zipfile import ZipFile
    import csv
    from io import TextIOWrapper

    index: dict[str, list[dict]] = {}
    cutoff = (date.today() - timedelta(days=FTD_LOOKBACK_DAYS)).isoformat().replace("-", "")

    for ym, half in expected_files:
        path = _raw_path(ym, half)
        if not path.exists():
            continue
        try:
            with ZipFile(path) as z:
                for name in z.namelist():
                    with z.open(name) as f:
                        text = TextIOWrapper(f, encoding="utf-8", errors="ignore")
                        reader = csv.reader(text, delimiter="|")
                        for row in reader:
                            if len(row) < 4:
                                continue
                            try:
                                settlement = row[0].strip()
                                if settlement < cutoff:
                                    continue
                                symbol = row[2].strip().upper()
                                qty = int(row[3].strip() or 0)
                                if not symbol or qty <= 0:
                                    continue
                                if symbol not in index:
                                    index[symbol] = []
                                index[symbol].append({
                                    "settlement_date": settlement,
                                    "quantity": qty,
                                })
                            except Exception:
                                continue
        except Exception as e:
            logger.warning("Failed to parse %s: %s", path, e)

    # Dedup + sort + trim per ticker
    for sym in list(index.keys()):
        seen = set()
        clean = []
        for r in sorted(index[sym], key=lambda x: x["settlement_date"], reverse=True):
            if r["settlement_date"] in seen:
                continue
            seen.add(r["settlement_date"])
            clean.append(r)
            if len(clean) > 40:
                break
        index[sym] = list(reversed(clean))
    return index


def fetch(ticker: str, force_refresh: bool = False, **kwargs) -> dict:
    """
    Fast, local-only lookup of recent FTD data for a ticker.
    Never performs network I/O. Call `refresh()` separately when you want fresh data.
    """
    ticker = ticker.upper()
    cache_key = f"ftd_{ticker}"

    if not force_refresh:
        cached = _cache.get("ftd", cache_key, CACHE_TTL.get("finra", 21600))
        if cached:
            return cached

    index_path = INDEX_DIR / "recent.json"
    if not index_path.exists():
        # No index yet — return empty but valid shape so scoring doesn't blow up
        result = {
            "ticker": ticker,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "ftds": [],
            "latest_ftd": 0,
            "avg_ftd_recent": 0,
            "ftd_count": 0,
            "source": "SEC FTD (not yet indexed — run refresh)",
        }
        return result

    try:
        index = json.loads(index_path.read_text())
    except Exception:
        index = {}

    ftds = index.get(ticker, [])
    latest = ftds[-1]["quantity"] if ftds else 0
    recent = ftds[-10:] if ftds else []
    avg = sum(r["quantity"] for r in recent) / len(recent) if recent else 0

    result = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "ftds": ftds[-15:],
        "latest_ftd": latest,
        "avg_ftd_recent": round(avg),
        "ftd_count": len(ftds),
        "source": "SEC FTD (cnsfails)",
    }

    _cache.put("ftd", cache_key, result)
    return result


# Convenience for CLI / manual use
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        print(refresh(force="--force" in sys.argv))
    else:
        print("Usage: python -m src.data.ftd refresh [--force]")