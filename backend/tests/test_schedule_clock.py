"""The clock the statistics are measured against.

OEE is working time ÷ *open* time, and line cycle time restarts at every shift
opening, so both numbers are only as good as this module. It is also the one
place in the product where the arithmetic is genuinely subtle: a calendar day
is not always 24 hours, and a plant's local hours are not the same thing as
elapsed time.

Everything here is a pure function of (window, schedule, timezone), so these
tests can name an exact instant and assert an exact number of seconds — no
database, no clock mocking, no flakiness.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.schedule import FULL_HOUR, default_work_hours, open_seconds, shift_starts

NY = "America/New_York"
BERLIN = "Europe/Berlin"
KATHMANDU = "Asia/Kathmandu"          # UTC+05:45 — a quarter-hour offset
ALWAYS = [[FULL_HOUR] * 24 for _ in range(7)]
NINE_TO_FIVE = [[FULL_HOUR if 9 <= h < 17 else 0 for h in range(24)] for _ in range(7)]

H = 3600.0


def _local_day(y, m, d, tzname):
    """The real instants bounding one local calendar day."""
    tz = ZoneInfo(tzname)
    a = datetime(y, m, d, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    b = (datetime(y, m, d, 12, 0, tzinfo=tz) + timedelta(hours=24)).replace(
        hour=0, minute=0).astimezone(timezone.utc)
    return a, b


# ── Daylight saving ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,date,tzname,hours", [
    ("spring forward", (2026, 3, 8), NY, 23),      # 02:00 never happens
    ("fall back", (2026, 11, 1), NY, 25),          # 01:00 happens twice
    ("ordinary day", (2026, 6, 10), NY, 24),
    ("spring forward (EU)", (2026, 3, 29), BERLIN, 23),
    ("fall back (EU)", (2026, 10, 25), BERLIN, 25),
])
def test_an_always_open_day_reports_the_hours_that_really_elapsed(label, date, tzname, hours):
    """Regression. The walk advanced a *local* datetime an hour at a time, so
    it counted 24 local hours whatever actually elapsed: 24 h on a 23-hour day
    and 24 h on a 25-hour one. OEE is a ratio — an hour of phantom denominator
    understates it in spring, and a missing hour can push it over 100% in
    autumn. Twice a year, for every customer not on UTC running a weekend
    shift."""
    start, end = _local_day(*date, tzname)
    assert (end - start).total_seconds() == hours * H, "the fixture itself is wrong"
    assert open_seconds(start, end, ALWAYS, tzname) == hours * H


def test_a_shift_that_spans_the_lost_hour_is_an_hour_shorter():
    """A 24/7 line's night shift on the Sunday the clocks go forward really is
    seven hours of work, not eight, and the people on it went home an hour
    early. Charging OEE for the hour nobody could work is charging for time
    that did not exist."""
    tz = ZoneInfo(NY)
    start = datetime(2026, 3, 8, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    end = datetime(2026, 3, 8, 8, 0, tzinfo=tz).astimezone(timezone.utc)
    assert open_seconds(start, end, ALWAYS, NY) == 7 * H


def test_a_shift_that_spans_the_repeated_hour_is_an_hour_longer():
    tz = ZoneInfo(NY)
    start = datetime(2026, 11, 1, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    end = datetime(2026, 11, 1, 8, 0, tzinfo=tz).astimezone(timezone.utc)
    assert open_seconds(start, end, ALWAYS, NY) == 9 * H


def test_a_quarter_hour_timezone_still_lands_on_the_grid():
    """Nepal is UTC+05:45. Every real offset is a multiple of 15 minutes, which
    is exactly why walking the UTC quarter grid can measure local quarters at
    all — if that stopped being true the arithmetic would silently smear."""
    start, end = _local_day(2026, 6, 10, KATHMANDU)
    assert open_seconds(start, end, NINE_TO_FIVE, KATHMANDU) == 8 * H


# ── The ordinary cases, so the DST fix cannot have broken them ──────────────

def test_a_closed_day_is_zero():
    start, end = _local_day(2026, 6, 13, NY)          # a Saturday
    assert open_seconds(start, end, default_work_hours(), NY) == 0.0


def test_a_working_day_is_its_shift():
    start, end = _local_day(2026, 6, 10, NY)          # a Wednesday
    assert open_seconds(start, end, default_work_hours(), NY) == 8 * H


def test_partial_quarters_at_the_window_edges_are_counted_once():
    """A window starting at 09:07 gets eight minutes of that quarter, not the
    whole one and not none of it."""
    tz = ZoneInfo(NY)
    start = datetime(2026, 6, 10, 9, 7, tzinfo=tz).astimezone(timezone.utc)
    end = datetime(2026, 6, 10, 9, 22, tzinfo=tz).astimezone(timezone.utc)
    assert open_seconds(start, end, NINE_TO_FIVE, NY) == 15 * 60


def test_a_late_opening_quarter_mask_is_honoured():
    """0b1110 opens at :15 — the feature the quarter mask exists for."""
    sched = [[0] * 24 for _ in range(7)]
    for d in range(7):
        sched[d][9] = 0b1110
    start, end = _local_day(2026, 6, 10, NY)
    assert open_seconds(start, end, sched, NY) == 45 * 60


def test_no_schedule_means_no_open_time():
    start, end = _local_day(2026, 6, 10, NY)
    assert open_seconds(start, end, None, NY) == 0.0
    assert open_seconds(start, end, [], NY) == 0.0


def test_a_backwards_window_is_zero_not_negative():
    start, end = _local_day(2026, 6, 10, NY)
    assert open_seconds(end, start, ALWAYS, NY) == 0.0


# ── Shift openings, which reset the line-cycle-time clock ───────────────────

def _local(starts, tzname):
    return [s.astimezone(ZoneInfo(tzname)).strftime("%a %H:%M") for s in starts]


def test_one_opening_per_working_day():
    tz = ZoneInfo(NY)
    a = datetime(2026, 6, 8, 0, 0, tzinfo=tz).astimezone(timezone.utc)     # Monday
    b = datetime(2026, 6, 13, 0, 0, tzinfo=tz).astimezone(timezone.utc)    # Saturday
    assert _local(shift_starts(a, b, default_work_hours(), NY), NY) == [
        "Mon 09:00", "Tue 09:00", "Wed 09:00", "Thu 09:00", "Fri 09:00"]


def test_a_window_beginning_mid_shift_is_not_an_opening():
    """The quarter before the window is inspected for exactly this. Otherwise
    every report would invent an opening at its own start, and the first lot
    after it would be charged nothing."""
    tz = ZoneInfo(NY)
    a = datetime(2026, 6, 10, 11, 0, tzinfo=tz).astimezone(timezone.utc)
    b = datetime(2026, 6, 10, 16, 0, tzinfo=tz).astimezone(timezone.utc)
    assert shift_starts(a, b, default_work_hours(), NY) == []


def test_an_always_open_plant_never_opens():
    """A 24/7 line has no shift boundary, so nothing ever resets the clock —
    which is correct: there is no hour it could not have worked."""
    a, b = _local_day(2026, 6, 10, NY)
    assert shift_starts(a, b, ALWAYS, NY) == []


def test_the_opening_survives_the_clocks_changing():
    """Nine o'clock on the Sunday the clocks change is still nine o'clock, and
    it must be reported once — not skipped, and not twice."""
    tz = ZoneInfo(NY)
    for y, m, d in [(2026, 3, 8), (2026, 11, 1)]:
        a = datetime(y, m, d, 0, 0, tzinfo=tz).astimezone(timezone.utc)
        b = datetime(y, m, d, 23, 0, tzinfo=tz).astimezone(timezone.utc)
        assert _local(shift_starts(a, b, NINE_TO_FIVE, NY), NY) == ["Sun 09:00"], (y, m, d)


def test_openings_come_back_as_utc():
    """Callers compare them against event timestamps, which are UTC-aware."""
    a, b = _local_day(2026, 6, 10, NY)
    for s in shift_starts(a, b, default_work_hours(), NY):
        assert s.tzinfo is not None
        assert s.utcoffset() == timedelta(0)
