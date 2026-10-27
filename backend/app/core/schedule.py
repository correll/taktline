"""Work-hours schedule + open-time math, used to make utilisation relative to the
hours a plant is actually meant to be running (not calendar time).

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

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

FULL_HOUR = 0b1111   # all four quarters open
MAX_BREAKS = 12


class Schedule(list):
    """The 7×24 quarter grid, carrying the plant's breaks with it.

    Breaks are minutes of the local day, ``[[start, end], ...]``, the same on
    every day. They are not representable in the grid — a ten-minute tea
    break does not fall on quarter boundaries — and they matter: available
    time is the shift *less* its breaks (Rother and Shook's data box), so a
    break counted as open time charges idle minutes to every station's utilisation,
    and a lot that waits through one appears to have been worked.

    A list subclass so that every function here, and every caller that
    passes the grid along, keeps working unchanged; the breaks travel with it.
    """

    def __init__(self, grid, breaks=()):
        super().__init__(grid)
        self.breaks = normalise_breaks(breaks)


def normalise_breaks(breaks) -> list:
    out = []
    for b in breaks or ():
        try:
            a, z = int(b[0]), int(b[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= a < z <= 24 * 60:
            out.append([a, z])
    out.sort()
    merged: list = []
    for a, z in out:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], z)
        else:
            merged.append([a, z])
    return merged[:MAX_BREAKS]


def _breaks_of(schedule) -> list:
    return getattr(schedule, "breaks", None) or []


def break_spans(start_utc: datetime, end_utc: datetime, schedule, tzname: str = "UTC") -> list:
    """The breaks that fall inside [start, end], as UTC pairs, clipped."""
    brk = _breaks_of(schedule)
    if not brk or end_utc <= start_utc:
        return []
    tz = _tz(tzname)
    d0 = (start_utc.astimezone(tz) - timedelta(days=1)).date()
    d1 = (end_utc.astimezone(tz) + timedelta(days=1)).date()
    out = []
    d = d0
    while d <= d1:
        for a, z in brk:
            la = datetime.combine(d, time(0), tzinfo=tz) + timedelta(minutes=a)
            lz = datetime.combine(d, time(0), tzinfo=tz) + timedelta(minutes=z)
            ua, uz = max(la.astimezone(timezone.utc), start_utc), min(lz.astimezone(timezone.utc), end_utc)
            if uz > ua:
                out.append((ua, uz))
        d += timedelta(days=1)
    return out


def _subtract(intervals: list, holes: list) -> list:
    """Interval difference of two sorted lists of (a, b) pairs."""
    if not holes:
        return intervals
    holes = sorted(holes)
    out = []
    for a, b in intervals:
        cur = a
        for ha, hb in holes:
            if hb <= cur or ha >= b:
                continue
            if ha > cur:
                out.append((cur, ha))
            cur = max(cur, hb)
            if cur >= b:
                break
        if cur < b:
            out.append((cur, b))
    return out


def break_overlap_seconds(start_utc, end_utc, schedule, tzname: str = "UTC",
                          also_off: list | None = None) -> float:
    """Seconds of [start, end] that fall in a break during open hours, not
    counting time already in ``also_off`` (pauses), so nothing is taken off
    twice."""
    if start_utc is None or end_utc is None or end_utc <= start_utc:
        return 0.0
    spans = break_spans(start_utc, end_utc, schedule, tzname)
    if not spans:
        return 0.0
    opened = _open_intervals_grid(start_utc, end_utc, schedule, tzname)
    inb = []
    for a, b in spans:
        for oa, ob in opened:
            lo, hi = max(a, oa), min(b, ob)
            if hi > lo:
                inb.append((lo, hi))
    if also_off:
        inb = _subtract(sorted(inb), sorted(also_off))
    return sum((b - a).total_seconds() for a, b in inb)


def default_work_hours() -> list[list[int]]:
    """Monday–Friday 9am–5pm fully open; weekends closed."""
    return [[FULL_HOUR if (d < 5 and 9 <= h < 17) else 0 for h in range(24)] for d in range(7)]


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _is_open(schedule: list[list[int]], local: datetime) -> bool:
    """Is the quarter containing this LOCAL time an open one?"""
    try:
        mask = int(schedule[local.weekday()][local.hour])
    except (IndexError, TypeError, ValueError):
        return False
    mask = max(0, min(FULL_HOUR, mask))
    return bool(mask & (1 << (local.minute // 15)))


def _quarters(start_utc: datetime, end_utc: datetime):
    """Walk [start, end] in 15-minute steps of REAL time, yielding each step's
    UTC instant.

    Real time, deliberately, rather than wall-clock time. Both of these used to
    advance a *local* datetime by an hour at a time, which counts 24 local
    hours whatever actually elapsed: an open day was reported as 24 h on the
    Sunday the clocks go forward (23 real hours) and as 24 h on the Sunday they
    go back (25). The first understates utilisation and the second can push it over
    100%, twice a year, for every customer not on UTC whose line runs a
    weekend shift — and utilisation is a ratio, so an hour of phantom denominator is
    not a rounding error.

    Every real-world UTC offset is a multiple of 15 minutes, so a local quarter
    boundary is always a UTC quarter boundary too, and stepping the UTC grid
    visits each local quarter exactly as often as it genuinely occurred: the
    hour that does not exist in spring is never visited, and the hour that
    happens twice in autumn is visited twice.
    """
    cur = start_utc.astimezone(timezone.utc)
    cur = cur.replace(minute=(cur.minute // 15) * 15, second=0, microsecond=0)
    guard = 0
    while cur < end_utc and guard < 4 * 24 * 500:   # ~500-day cap
        guard += 1
        yield cur
        cur += timedelta(minutes=15)


def open_seconds(start_utc: datetime | None, end_utc: datetime | None,
                 schedule: list[list[int]] | None, tzname: str = "UTC") -> float:
    """Seconds within [start, end] that fall inside open work hours."""
    if not schedule or start_utc is None or end_utc is None or end_utc <= start_utc:
        return 0.0
    if _breaks_of(schedule):
        return sum((b - a).total_seconds()
                   for a, b in open_intervals(start_utc, end_utc, schedule, tzname))
    tz = _tz(tzname)
    total = 0.0
    for cur in _quarters(start_utc, end_utc):
        if not _is_open(schedule, cur.astimezone(tz)):
            continue
        seg_start = max(cur, start_utc)
        seg_end = min(cur + timedelta(minutes=15), end_utc)
        if seg_end > seg_start:
            total += (seg_end - seg_start).total_seconds()
    return total


def shift_starts(start_utc: datetime, end_utc: datetime,
                 schedule: list[list[int]] | None, tzname: str = "UTC") -> list[datetime]:
    """Every moment in [start, end] where the plant *opens* — a closed quarter
    followed by an open one.

    This is what resets the line-cycle-time clock. Without it, the first lot of
    a Monday would be charged with the whole weekend: work that could not have
    been done is not delay, and a metric that says otherwise is one nobody will
    trust twice.

    Returned in UTC, ascending. The quarter immediately *before* the window is
    inspected too, so a window that begins mid-shift is not mistaken for an
    opening.
    """
    if not schedule or end_utc <= start_utc:
        return []
    tz = _tz(tzname)
    out: list[datetime] = []
    prev_open = None
    for cur in _quarters(start_utc, end_utc):
        if prev_open is None:                      # the quarter before the window
            prev_open = _is_open(schedule, (cur - timedelta(minutes=15)).astimezone(tz))
        is_open = _is_open(schedule, cur.astimezone(tz))
        if is_open and not prev_open and cur >= start_utc:
            out.append(cur)
        prev_open = is_open
    return out


def open_intervals(start_utc: datetime, end_utc: datetime,
                   schedule: list[list[int]] | None, tzname: str = "UTC") -> list[tuple]:
    """The open stretches of [start, end] as merged (from, to) UTC pairs,
    breaks taken out.

    Computed once per question and then swept against a step function, so a
    time average over thousands of events does not walk the calendar once per
    event."""
    grid = _open_intervals_grid(start_utc, end_utc, schedule, tzname)
    return _subtract(grid, break_spans(start_utc, end_utc, schedule, tzname))


def _open_intervals_grid(start_utc: datetime, end_utc: datetime,
                         schedule: list[list[int]] | None, tzname: str = "UTC") -> list[tuple]:
    if not schedule or end_utc <= start_utc:
        return []
    tz = _tz(tzname)
    out: list[list] = []
    for cur in _quarters(start_utc, end_utc):
        if not _is_open(schedule, cur.astimezone(tz)):
            continue
        a, b = max(cur, start_utc), min(cur + timedelta(minutes=15), end_utc)
        if b <= a:
            continue
        if out and out[-1][1] >= a:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]
