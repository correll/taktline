"""Work-hours schedule (quarter bitmask) + OEE-against-open-time."""

from datetime import datetime, timezone

from app.core.schedule import default_work_hours, open_seconds
from tests.helpers import bootstrap_admin

MON = datetime(2024, 1, 1, tzinfo=timezone.utc)   # a Monday
SAT = datetime(2024, 1, 6, tzinfo=timezone.utc)   # the Saturday that week

# Quarter masks (bit i = the i-th 15-min quarter of the hour, bit 0 = :00–:15).
FULL   = 0b1111   # 15  whole hour
LATE15 = 0b1110   # 14  opens :15  (drop first quarter)
LATE30 = 0b1100   # 12  opens :30
LATE45 = 0b1000   # 8   opens :45
EARLY45 = 0b0111  # 7   closes :45 (drop last quarter)
EARLY15 = 0b0001  # 1   closes :15


def test_open_seconds_weekday_window():
    sch = default_work_hours()                     # Mon–Fri 9–5
    assert open_seconds(MON.replace(hour=8), MON.replace(hour=18), sch, "UTC") == 8 * 3600
    assert open_seconds(MON.replace(hour=9), MON.replace(hour=17), sch, "UTC") == 8 * 3600
    assert open_seconds(MON.replace(hour=10), MON.replace(hour=12, minute=30), sch, "UTC") == 2.5 * 3600


def test_open_seconds_weekend_closed():
    assert open_seconds(SAT.replace(hour=9), SAT.replace(hour=17), default_work_hours(), "UTC") == 0.0


def test_open_seconds_spans_night():
    # 4pm Monday → 10am Tuesday: open = 4–5pm Mon (1h) + 9–10am Tue (1h) = 2h
    tue10 = MON.replace(day=2, hour=10)
    assert open_seconds(MON.replace(hour=16), tue10, default_work_hours(), "UTC") == 2 * 3600


def test_open_seconds_partial_hour():
    sch = default_work_hours()
    sch[0][8] = LATE30   # Monday 8:00 opens at 8:30 → 30 min that hour
    assert open_seconds(MON.replace(hour=8), MON.replace(hour=9), sch, "UTC") == 1800
    sch[0][8] = LATE45   # opens 8:45 → 15 min
    assert open_seconds(MON.replace(hour=8), MON.replace(hour=9), sch, "UTC") == 900


def test_open_seconds_shift_starts_late():
    # LATE15 opens at :15 — the first 15 min (8:00–8:15) are closed.
    sch = default_work_hours()
    sch[0][8] = LATE15
    assert open_seconds(MON.replace(hour=8), MON.replace(hour=8, minute=15), sch, "UTC") == 0
    assert open_seconds(MON.replace(hour=8), MON.replace(hour=8, minute=30), sch, "UTC") == 900
    assert open_seconds(MON.replace(hour=8, minute=15), MON.replace(hour=9), sch, "UTC") == 45 * 60


def test_open_seconds_shift_ends_early():
    # EARLY45 closes at :45 — the last 15 min (8:45–9:00) are closed.
    sch = default_work_hours()
    sch[0][8] = EARLY45
    assert open_seconds(MON.replace(hour=8), MON.replace(hour=9), sch, "UTC") == 45 * 60
    assert open_seconds(MON.replace(hour=8, minute=45), MON.replace(hour=9), sch, "UTC") == 0
    # EARLY15 is open only 8:00–8:15
    sch[0][8] = EARLY15
    assert open_seconds(MON.replace(hour=8), MON.replace(hour=9), sch, "UTC") == 900
    assert open_seconds(MON.replace(hour=8, minute=15), MON.replace(hour=9), sch, "UTC") == 0


def test_global_settings_workhours_roundtrip(actor):
    a = actor(); bootstrap_admin(a)
    gs = a.req("GET", "/global-settings/").json()
    assert len(gs["workHours"]) == 7 and all(len(r) == 24 for r in gs["workHours"])
    assert gs["workHours"][0][9] == FULL and gs["workHours"][0][3] == 0   # Mon 9 fully open, 3 closed
    assert gs["workHours"][5][9] == 0                                     # Sat closed

    part = [[0] * 24 for _ in range(7)]
    part[0][8] = LATE30                                                   # opens 8:30 on Monday
    r = a.req("PUT", "/global-settings/", {"workHours": part})
    assert r.status_code == 200 and r.json()["workHours"][0][8] == LATE30
    # out-of-range values clamp to 0–15; malformed shape is rejected
    assert a.req("PUT", "/global-settings/", {"workHours": [[99] + [0] * 23] * 7}).json()["workHours"][0][0] == 15
    assert a.req("PUT", "/global-settings/", {"workHours": [[1, 2, 3]]}).status_code == 422
