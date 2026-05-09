"""
US equity market hours, ET-aware. Used by the 0DTE screener to gate
recommendations to a sane intraday window.

Why a window inside RTH (not the full session)?
- Pre-9:45 ET: opening-auction noise; quotes are wide and unstable.
- Post-15:30 ET: theta dominates everything; gains compress and the
  cost-to-exit becomes punishing on top of the obvious gamma blow-up risk.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

OPEN_TIME = time(9, 30)
CLOSE_TIME = time(16, 0)
SCREENER_OPEN_TIME = time(9, 45)
# Reddit-corpus consensus across r/options + r/Daytrading: 0DTE edge concentrates
# in the first 2-3 hours after open. Midday and afternoon are mostly chop where
# theta dominates and directional moves get faded. Tightened from 15:30 to 13:00.
SCREENER_CLOSE_TIME = time(13, 0)

# 2025-2026 US market holidays (NYSE). Update annually.
HOLIDAYS = {
    # 2025
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17), date(2025, 4, 18),
    date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4), date(2025, 9, 1),
    date(2025, 11, 27), date(2025, 12, 25),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
}


def now_et() -> datetime:
    return datetime.now(ET)


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in HOLIDAYS


def is_market_open(now: datetime | None = None) -> bool:
    n = now or now_et()
    if not is_trading_day(n.date()):
        return False
    t = n.time()
    return OPEN_TIME <= t < CLOSE_TIME


def is_screener_window(now: datetime | None = None) -> tuple[bool, str | None]:
    """Return (allowed, reason_when_blocked).

    Reasons: 'closed', 'pre_open', 'auction_noise', 'midday_chop'.
    """
    n = now or now_et()
    if not is_trading_day(n.date()):
        return False, "closed"
    t = n.time()
    if t < OPEN_TIME:
        return False, "pre_open"
    if t < SCREENER_OPEN_TIME:
        return False, "auction_noise"
    if t >= SCREENER_CLOSE_TIME and t < CLOSE_TIME:
        return False, "midday_chop"
    if t >= CLOSE_TIME:
        return False, "closed"
    return True, None


def hours_until_close(now: datetime | None = None) -> float:
    """Hours of trading remaining today. Returns 0 outside RTH."""
    n = now or now_et()
    if not is_market_open(n):
        return 0.0
    close_dt = datetime.combine(n.date(), CLOSE_TIME, tzinfo=ET)
    return max(0.0, (close_dt - n).total_seconds() / 3600.0)


def next_market_close(now: datetime | None = None) -> datetime:
    n = now or now_et()
    candidate = datetime.combine(n.date(), CLOSE_TIME, tzinfo=ET)
    if n >= candidate or not is_trading_day(n.date()):
        d = n.date() + timedelta(days=1)
        while not is_trading_day(d):
            d += timedelta(days=1)
        candidate = datetime.combine(d, CLOSE_TIME, tzinfo=ET)
    return candidate
