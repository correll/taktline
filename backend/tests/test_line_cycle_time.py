"""Line cycle time — the station's actual exit rate.

Cycle time answers *how long does the work take* (Start→Stop, per unit). This
answers *how often does a piece actually leave*, which is the number that moves
when the line is starved, blocked, or waiting for a forklift. The gap between
the two is the waste, in seconds.

The rules being pinned here:

- measured **per piece** — a lot of ten leaving is ten pieces, not one
- the clock starts when work *could* have moved (the shift opening) and
  re-anchors at every departure
- the clock never starts before the station had anything to do with a lot, so a
  line's opening day is not charged for the morning before it existed
- **every shift opening resets it**, so a lot finished after hours is charged to
  the shift that follows rather than to the night — without this, the first
  departure of a Monday carries the whole weekend and the metric is worthless
"""

from datetime import datetime, timedelta, timezone

from app.core.schedule import default_work_hours, shift_starts


# ─── The shift boundaries the metric is anchored to ──────────────────────────

def test_shift_starts_finds_openings_and_skips_the_weekend():
    sched = default_work_hours()          # Mon–Fri 09:00–17:00
    start = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)   # Friday, before open
    opens = shift_starts(start, start + timedelta(days=4), sched, "UTC")
    assert [d.isoformat() for d in opens] == [
        "2026-07-24T09:00:00+00:00",      # Friday
        "2026-07-27T09:00:00+00:00",      # Monday — Sat/Sun have no opening
    ]


def test_a_window_starting_mid_shift_is_not_an_opening():
    """Otherwise every report would invent a shift start at its own left edge."""
    sched = default_work_hours()
    mid = datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc)    # Friday, already open
    opens = shift_starts(mid, mid + timedelta(hours=3), sched, "UTC")
    assert opens == []


def test_a_late_starting_shift_opens_on_the_quarter():
    """Quarter masks exist so a shift can start at :15 — the anchor must too."""
    sched = default_work_hours()
    sched[4][9] = 0b1110                   # Friday 09:00 hour: opens at :15
    start = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
    opens = shift_starts(start, start + timedelta(hours=4), sched, "UTC")
    assert [d.isoformat() for d in opens] == ["2026-07-24T09:15:00+00:00"]


# ─── The metric itself, over a hand-built departure log ──────────────────────

def _line_cycle(departures, opens, first_activity=None):
    """The algorithm under test, in the small: walk departures, re-anchoring to
    the most recent shift opening, and average the per-piece intervals. Mirrors
    sessions._line_cycle_times so the semantics can be pinned without a
    database round-trip per case."""
    # A shift opening before the station had anything to do with a lot is not
    # delay it is answerable for (see sessions._line_cycle_times).
    if first_activity is not None:
        opens = [o for o in opens if o >= first_activity]
    intervals, anchor, oi = [], None, 0
    for ts, qty in departures:
        while oi < len(opens) and opens[oi] <= ts:
            if anchor is None or opens[oi] > anchor:
                anchor = opens[oi]
            oi += 1
        if anchor is not None and ts > anchor:
            intervals.append((ts - anchor).total_seconds() / qty)
        anchor = ts
    return sum(intervals) / len(intervals) if intervals else None


FRI_OPEN = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)
MON_OPEN = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)


def test_first_lot_is_measured_from_the_shift_opening():
    """Nine minutes after the shift opened, one piece leaves → 9 minutes."""
    out = _line_cycle([(FRI_OPEN + timedelta(minutes=9), 1)], [FRI_OPEN])
    assert out == 9 * 60


def test_a_departure_starts_the_clock_for_the_next():
    out = _line_cycle([(FRI_OPEN + timedelta(minutes=10), 1),
                       (FRI_OPEN + timedelta(minutes=16), 1)], [FRI_OPEN])
    assert out == (10 * 60 + 6 * 60) / 2       # 10 min then 6 min


def test_a_lot_of_ten_counts_as_ten_pieces():
    """Moving ten at once is ten pieces leaving; charging the whole interval to
    one piece would make batching look like a slowdown."""
    out = _line_cycle([(FRI_OPEN + timedelta(minutes=20), 10)], [FRI_OPEN])
    assert out == 2 * 60                        # 20 minutes ÷ 10


def test_the_weekend_is_not_counted_against_monday():
    """The regression this exists for: without the shift reset, Monday's first
    lot carries ~64 hours of closed time and the number is nonsense."""
    departures = [(FRI_OPEN + timedelta(minutes=10), 1),         # Friday
                  (MON_OPEN + timedelta(minutes=12), 1)]         # Monday
    out = _line_cycle(departures, [FRI_OPEN, MON_OPEN])
    assert out == (10 * 60 + 12 * 60) / 2
    # Sanity: the naive version would be dominated by the weekend.
    naive = (departures[1][0] - departures[0][0]).total_seconds()
    assert naive > 60 * 60 * 60


def test_work_finished_after_hours_lands_on_the_next_shift():
    """A lot completed at 18:30 but only moved next morning is charged from the
    morning opening — the operator did not spend the night waiting."""
    after_hours_move = MON_OPEN + timedelta(minutes=5)
    out = _line_cycle([(FRI_OPEN + timedelta(hours=9), 1),       # Friday 18:00, after close
                       (after_hours_move, 1)], [FRI_OPEN, MON_OPEN])
    # Second interval is measured from Monday's opening, not from Friday evening.
    assert out == (9 * 3600 + 5 * 60) / 2


def test_no_departures_means_no_number():
    assert _line_cycle([], [FRI_OPEN]) is None


def test_a_departure_before_any_opening_is_skipped_not_guessed():
    """With no anchor there is no honest interval — it starts the clock and
    waits, rather than inventing a start time."""
    out = _line_cycle([(FRI_OPEN - timedelta(hours=2), 1),
                       (FRI_OPEN + timedelta(minutes=30), 1)], [FRI_OPEN])
    assert out == 30 * 60      # only the second departure yields an interval


def test_a_new_line_is_not_charged_for_the_morning_before_it_existed(actor=None):
    """The regression this exists for, found by reading a running simulation's
    own statistics: a company created at 16:30 shipped a piece a minute, and
    every station reported ~1700 s per piece. The first departure was anchored
    to a 09:00 shift opening — seven hours before the line, the stations or the
    lots existed. Time the station could not possibly have shipped in is not
    its delay."""
    born = FRI_OPEN + timedelta(hours=7)          # 16:00, the line's first event
    departures = [(born + timedelta(minutes=1), 1),
                  (born + timedelta(minutes=2), 1),
                  (born + timedelta(minutes=3), 1)]
    out = _line_cycle(departures, [FRI_OPEN], first_activity=born)
    assert out == 60, out                          # a piece a minute, as observed

    # Without the floor the morning dominates and the number is meaningless.
    naive = _line_cycle(departures, [FRI_OPEN])
    assert naive > 20 * 60

    # A station with older history still gets its idle morning counted: the
    # opening is later than its first activity, so nothing is discarded.
    established = _line_cycle([(FRI_OPEN + timedelta(minutes=9), 1)], [FRI_OPEN],
                              first_activity=FRI_OPEN - timedelta(days=1))
    assert established == 9 * 60
