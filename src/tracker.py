"""
Append-only JSONL idea tracker. One event per line: open | update | close | postmortem.
See .claude/skills/idea-tracker/SKILL.md for protocol.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import IDEAS_LOG


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_seq(ticker: str) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    n = 0
    if IDEAS_LOG.exists():
        for line in IDEAS_LOG.read_text().splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "open" and ev.get("ts", "").startswith(today) and ev.get("ticker") == ticker:
                n += 1
    return n + 1


def _append(event: dict) -> None:
    IDEAS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with IDEAS_LOG.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def _read_all() -> list[dict]:
    if not IDEAS_LOG.exists():
        return []
    events = []
    for line in IDEAS_LOG.read_text().splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def open_idea(
    ticker: str,
    ticker_result: dict,
    thesis: str,
    invalidation: str,
    time_stop: str | None = None,
    force: bool = False,
    notes: str = "",
) -> dict:
    score = ticker_result["score"]
    if not force and score < 70:
        raise ValueError(f"score {score} < 70 threshold; pass force=True to override")
    if not thesis.strip() or not invalidation.strip():
        raise ValueError("thesis and invalidation are required")

    today = datetime.now(timezone.utc).date().isoformat()
    seq = _today_seq(ticker)
    idea_id = f"{today}-{ticker}-{seq:02d}"

    factors = ticker_result.get("factors", {})
    event = {
        "event": "open",
        "ts": _now_iso(),
        "idea_id": idea_id,
        "ticker": ticker.upper(),
        "score_at_entry": score,
        "factors": {k: v.get("score") for k, v in factors.items()},
        "thesis": thesis.strip(),
        "invalidation": invalidation.strip(),
        "time_stop": time_stop,
        "entry_ref_price": ticker_result.get("price"),
        "notes": notes,
    }
    _append(event)
    return event


def close_idea(
    idea_id: str,
    close_reason: str,
    exit_ref_price: float | None = None,
    peak_drawup_pct: float | None = None,
    peak_drawdown_pct: float | None = None,
) -> dict:
    open_event = _find_open(idea_id)
    if not open_event:
        raise ValueError(f"no open idea with id {idea_id}")

    opened = datetime.fromisoformat(open_event["ts"])
    now = datetime.now(timezone.utc)
    days_held = round((now - opened).total_seconds() / 86400, 2)

    event = {
        "event": "close",
        "ts": _now_iso(),
        "idea_id": idea_id,
        "ticker": open_event["ticker"],
        "exit_ref_price": exit_ref_price,
        "close_reason": close_reason,
        "days_held": days_held,
        "peak_drawup_pct": peak_drawup_pct,
        "peak_drawdown_pct": peak_drawdown_pct,
    }
    _append(event)
    return event


def postmortem(
    idea_id: str,
    outcome: str,
    return_ref_pct: float | None,
    what_worked: str,
    what_missed: str,
    factor_calibration: dict[str, str],
    lesson: str,
) -> dict:
    close_event = _find_close(idea_id)
    if not close_event:
        raise ValueError(f"no close event for idea {idea_id} — close it first")

    event = {
        "event": "postmortem",
        "ts": _now_iso(),
        "idea_id": idea_id,
        "ticker": close_event["ticker"],
        "outcome": outcome,
        "return_ref_pct": return_ref_pct,
        "what_worked": what_worked.strip(),
        "what_missed": what_missed.strip(),
        "factor_calibration": factor_calibration,
        "lesson": lesson.strip(),
    }
    _append(event)
    return event


def _find_open(idea_id: str) -> dict | None:
    for ev in _read_all():
        if ev.get("event") == "open" and ev.get("idea_id") == idea_id:
            return ev
    return None


def _find_close(idea_id: str) -> dict | None:
    for ev in _read_all():
        if ev.get("event") == "close" and ev.get("idea_id") == idea_id:
            return ev
    return None


def list_ideas() -> list[dict]:
    """
    Materialize idea state from the event log.
    Each idea: status (open/closed/postmortemed), entry + close + postmortem merged.
    """
    events = _read_all()
    ideas: dict[str, dict] = {}
    for ev in events:
        idea_id = ev.get("idea_id")
        if not idea_id:
            continue
        event_kind = ev.get("event")
        if event_kind == "open":
            ideas[idea_id] = {
                "idea_id": idea_id,
                "ticker": ev["ticker"],
                "status": "open",
                "opened_at": ev["ts"],
                "score_at_entry": ev.get("score_at_entry"),
                "factors_at_entry": ev.get("factors"),
                "thesis": ev.get("thesis"),
                "invalidation": ev.get("invalidation"),
                "time_stop": ev.get("time_stop"),
                "entry_ref_price": ev.get("entry_ref_price"),
                "notes": ev.get("notes"),
                "updates": [],
                "closed": None,
                "postmortem": None,
            }
        elif event_kind == "update" and idea_id in ideas:
            ideas[idea_id]["updates"].append(ev)
        elif event_kind == "close" and idea_id in ideas:
            ideas[idea_id]["status"] = "closed"
            ideas[idea_id]["closed"] = ev
        elif event_kind == "postmortem" and idea_id in ideas:
            ideas[idea_id]["status"] = "postmortemed"
            ideas[idea_id]["postmortem"] = ev

    return sorted(ideas.values(), key=lambda i: i["opened_at"], reverse=True)


def get_idea(idea_id: str) -> dict | None:
    for i in list_ideas():
        if i["idea_id"] == idea_id:
            return i
    return None
