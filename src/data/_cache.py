from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.config import CACHE_DIR


def _path(source: str, key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_")
    return CACHE_DIR / source / f"{safe}.json"


def get(source: str, key: str, ttl_seconds: int) -> Any | None:
    p = _path(source, key)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > ttl_seconds:
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def put(source: str, key: str, value: Any) -> None:
    p = _path(source, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, default=str))


def age_seconds(source: str, key: str) -> float | None:
    p = _path(source, key)
    if not p.exists():
        return None
    return time.time() - p.stat().st_mtime
