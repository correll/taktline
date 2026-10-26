"""A station worked by a crew is measured against the crew's time.

Working time adds up across operators, so the share of open time a station
worked has to count the operators too. Against open time alone, any station
where several people work at once read 100% busy all day, and the line
doctor's load corroboration could not tell its busiest crew from a bench that
idles half the shift. The crew is read from the record — each operator signs
in on their own device — and a station worked by one person at a time is
measured exactly as before.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.schedule import default_work_hours, open_seconds
from app.routers import cards as cards_router
from app.routers import sessions as sessions_router
from app.routers.sessions import crew_open_seconds
from tests.helpers import bootstrap_admin
from tests.test_stoppages import _line, _lot, _start

GRID = default_work_hours()                       # Monday to Friday, 09:00-17:00
MON = datetime(2027, 1, 4, tzinfo=timezone.utc)


def at(day, h, m=0):
    return MON + timedelta(days=day, hours=h, minutes=m)


def test_one_operator_is_measured_against_open_time_as_before():
    s = [(at(0, 9), at(0, 11), "ann"), (at(0, 13), at(0, 16), "ann"), (at(1, 9), at(1, 17), "ann")]
    a, b = at(0, 9), at(1, 17)
    assert crew_open_seconds(s, a, b, GRID, "UTC") == pytest.approx(open_seconds(a, b, GRID, "UTC"))


def test_a_handover_at_one_bench_counts_one_operator():
    s = [(at(0, 9), at(0, 13), "ann"), (at(0, 13), at(0, 17), "bob")]
    assert crew_open_seconds(s, at(0, 9), at(0, 17), GRID, "UTC") == pytest.approx(8 * 3600)


def test_two_operators_at_once_count_twice_with_their_idle_gaps():
    s = [(at(0, 9), at(0, 10), "ann"), (at(0, 15), at(0, 17), "ann"),     # present 9-17
         (at(0, 9), at(0, 13), "bob")]                                      # present 9-13
    assert crew_open_seconds(s, at(0, 9), at(0, 17), GRID, "UTC") == pytest.approx((8 + 4) * 3600)


def test_presence_is_read_per_opening_not_across_the_night():
    s = [(at(0, 9), at(0, 10), "ann"), (at(1, 16), at(1, 17), "ann"), (at(0, 9), at(1, 17), "bob")]
    # Ann was there 9-10 on Monday and 16-17 on Tuesday, not through Monday night
    assert crew_open_seconds(s, at(0, 9), at(1, 17), GRID, "UTC") == pytest.approx((16 + 2) * 3600)


class Clock:
    def __init__(self):
        self.t = at(0, 10)

    def __call__(self):
        return self.t

    def tick(self, minutes):
        self.t += timedelta(minutes=minutes)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(sessions_router, "utcnow", c)
    monkeypatch.setattr(cards_router, "utcnow", c)
    return c


def _end(a, sid, n):
    assert a.req("POST", f"/sessions/{sid}/end", {"quantity": n}).status_code == 200


def test_a_crew_that_idles_a_third_of_the_hour_reads_two_thirds_busy(actor, clock):
    a = actor(); bootstrap_admin(a)
    ids, tmpl = _line(a)
    lots = [_lot(a, ids, tmpl, n=2) for _ in range(4)]
    # Ann and Bob at Cut together: each works 0-20 and 40-60 minutes of the hour
    s1, s2 = _start(a, ids, lots[0], n=2, op="ann"), _start(a, ids, lots[1], n=2, op="bob")
    clock.tick(20)
    _end(a, s1, 2), _end(a, s2, 2)
    clock.tick(20)
    s3, s4 = _start(a, ids, lots[2], n=2, op="ann"), _start(a, ids, lots[3], n=2, op="bob")
    clock.tick(20)
    _end(a, s3, 2), _end(a, s4, 2)
    table = {r["stationId"]: r for r in a.req("GET", "/sessions/stats").json()}[ids["Cut"]]
    one = a.req("GET", f"/sessions/stats/{ids['Cut']}").json()
    # 80 operator-minutes of work in 120 operator-minutes present; against the
    # hour alone it read 100%, the same as a crew that never stopped
    assert table["oee"] == pytest.approx(80 / 120, abs=1e-6)
    assert one["oee"] == pytest.approx(80 / 120, abs=1e-6)
