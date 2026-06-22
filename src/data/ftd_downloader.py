"""
Polite downloader for SEC FTD monthly zip files.

This module is only imported during explicit refresh operations, never during
normal per-ticker scans. It is deliberately conservative with rate limits.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data.ftd import RAW_DIR
from src.config import SEC_USER_AGENT

HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=10, max=60),
)
def download_one(month: str, half: str) -> bool:
    """
    Download one monthly FTD file if it doesn't already exist locally.
    Returns True if we have the file (either downloaded or already present).
    """
    filename = f"cnsfails{month}{half}.zip"
    local = RAW_DIR / filename

    if local.exists() and local.stat().st_size > 100_000:
        return True

    url = f"https://www.sec.gov/files/data/fails-deliver-data/{filename}"

    try:
        # Be very polite to SEC
        time.sleep(2.0)
        with httpx.stream("GET", url, headers=HEADERS, timeout=60, follow_redirects=True) as r:
            if r.status_code == 404:
                logger.info("FTD file not yet published: %s", filename)
                return False
            if r.status_code == 429:
                logger.warning("429 from SEC for %s — will retry later", filename)
                r.raise_for_status()
            r.raise_for_status()

            with open(local, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=65536):
                    f.write(chunk)

        logger.info("Downloaded %s (%.1f MB)", filename, local.stat().st_size / 1e6)
        return True
    except Exception as e:
        logger.warning("Failed to download %s: %s", filename, e)
        if local.exists():
            local.unlink(missing_ok=True)
        return False