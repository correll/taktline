"""Work-hours schedule + open-time math, used to make OEE relative to the hours a
plant is actually meant to be running (not calendar time).

A schedule is a 7×24 grid: ``schedule[day][hour]`` holds a 4-bit **quarter mask**
for that clock hour — bit ``i`` (``1 << i``) marks the 15-minute quarter
``[i·15, (i+1)·15)`` minutes into the hour as open. So bit 0 = ``:00–:15`` …
bit 3 = ``:45–:00``; ``0b1111`` (15) is the whole hour, ``0`` is closed. Day 0 =
Monday … 6 = Sunday; hour ``h`` covers the local clock hour ``[h:00, h+1:00)``,
evaluated in the company's timezone.

Because each quarter is addressed independently, a shift can start late (drop the
early bits — ``0b1110`` opens at ``:15``) *or* end early (drop the late bits —
``0b0111`` closes at ``:45``).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

FULL_HOUR = 0b1111   # all four quarters open


def default_work_hours() -> list[list[int]]:
    """Monday–Friday 9am–5pm fully open; weekends closed."""
    return [[FULL_HOUR if (d < 5 and 9 <= h < 17) else 0 for h in range(24)] for d in range(7)]


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def open_seconds(start_utc: datetime | None, end_utc: datetime | None,
                 schedule: list[list[int]] | None, tzname: str = "UTC") -> float:
    """Seconds within [start, end] that fall inside open work hours."""
    if not schedule or start_utc is None or end_utc is None or end_utc <= start_utc:
        return 0.0
    tz = _tz(tzname)
    start = start_utc.astimezone(tz)
    end = end_utc.astimezone(tz)
    total = 0.0
    cur = start.replace(minute=0, second=0, microsecond=0)
    guard = 0
    while cur < end and guard < 24 * 500:          # ~500-day cap, plenty for any report
        guard += 1
        nxt = cur + timedelta(hours=1)
        try:
            mask = int(schedule[cur.weekday()][cur.hour])
        except (IndexError, TypeError, ValueError):
            mask = 0
        mask = max(0, min(FULL_HOUR, mask))
        if mask:
            for i in range(4):                     # each open quarter contributes its overlap
                if mask & (1 << i):
                    q_start = cur + timedelta(minutes=15 * i)
                    seg_start = max(q_start, start)
                    seg_end = min(q_start + timedelta(minutes=15), end)
                    if seg_end > seg_start:
                        total += (seg_end - seg_start).total_seconds()
        cur = nxt
    return total
