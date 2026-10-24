"""Breaks, and three ways the what-if model reads the record as the floor ran.

* Breaks are entered once, as minutes of the day, and are neither available
  time nor work: OEE's denominator leaves them out, a timer left running over
  one does not charge it to cycle time, and the model's clock skips them.
* A breakdown that outlasts a break is one repair, not two.
* A changeover follows a change of product, not a coin toss per lot.
"""
import asyncio
import uuid as _uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.schedule import FULL_HOUR, Schedule, open_intervals, open_seconds
from app.core.whatif import ArrivalIn, LineModel, Scenario, StationModel, run
from tests.helpers import bootstrap_admin
from tests.test_stoppages import Clock, _line, _lot, _start, clock  # noqa: F401

ALL_OPEN = [[FULL_HOUR] * 24 for _ in range(7)]
TEN_TO_QUARTER_PAST = [[600, 615]]            # 10:00-10:15


def test_breaks_are_not_open_time():
    grid = [[FULL_HOUR if (d < 5 and 6 <= h < 22) else 0 for h in range(24)] for d in range(7)]
    with_breaks = Schedule(grid, [[480, 490], [720, 730], [960, 970], [1200, 1210]])
    a = datetime(2027, 1, 4, tzinfo=timezone.utc)          # a Monday
    b = a + timedelta(days=1)
    assert open_seconds(a, b, grid) == 16 * 3600
    assert open_seconds(a, b, with_breaks) == 16 * 3600 - 40 * 60
    assert len(open_intervals(a, b, with_breaks)) == 5
    # A break outside the open hours takes nothing off.
    night = Schedule(grid, [[60, 120]])
    assert open_seconds(a, b, night) == 16 * 3600


def test_breaks_are_validated_and_kept(actor):
    a = actor(); bootstrap_admin(a)
    r = a.req("PUT", "/global-settings/", {"breaks": [[730, 720]]})
    assert r.status_code == 422
    r = a.req("PUT", "/global-settings/", {"breaks": [[720, 730], [480, 490], [485, 495]]})
    assert r.status_code == 200, r.text
    assert r.json()["breaks"] == [[480, 495], [720, 730]]       # sorted, overlaps merged


def test_a_timer_left_running_over_a_break_does_not_charge_it(actor, clock):  # noqa: F811
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": ALL_OPEN, "breaks": TEN_TO_QUARTER_PAST})
    ids, tmpl = _line(a)
    card = _lot(a, ids, tmpl)
    clock.t = datetime(2027, 1, 4, 9, 55, tzinfo=timezone.utc)
    sid = _start(a, ids, card)
    clock.tick(25 * 60)                                      # until 10:20
    r = a.req("POST", f"/sessions/{sid}/end", {})
    assert r.status_code == 200, r.text
    assert r.json()["durationSec"] == pytest.approx(10 * 60)  # 25 min less the break


def test_a_pause_during_a_break_is_not_taken_off_twice(actor, clock):  # noqa: F811
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": ALL_OPEN, "breaks": TEN_TO_QUARTER_PAST})
    ids, tmpl = _line(a)
    card = _lot(a, ids, tmpl)
    clock.t = datetime(2027, 1, 4, 9, 55, tzinfo=timezone.utc)
    sid = _start(a, ids, card)
    clock.tick(10 * 60)                                      # 10:05: the machine stops
    a.req("POST", f"/sessions/{sid}/pause", {"reason": "breakdown"})
    clock.tick(15 * 60)                                      # 10:20: repaired
    a.req("POST", f"/sessions/{sid}/resume")
    clock.tick(5 * 60)
    r = a.req("POST", f"/sessions/{sid}/end", {})
    # 30 min elapsed: 15 paused, and of the break only 10:00-10:05 was not.
    assert r.json()["durationSec"] == pytest.approx(10 * 60)


def _model(a):
    from app.core.whatif_data import build_model
    from app.db.connection import SessionLocal
    from app.routers.sessions import _work_schedule

    async def go():
        async with SessionLocal() as session:
            cid = _uuid.UUID(a.company)
            sched, tz = await _work_schedule(session, cid)
            since = datetime(2027, 1, 4, 0, tzinfo=timezone.utc)
            return await build_model(session, cid, since, since + timedelta(days=2), sched, tz)
    return asyncio.run(go())


def test_a_breakdown_that_outlasts_the_timer_is_one_repair(actor, clock):  # noqa: F811
    """The operator stops the timer at the shift change while the welder is
    down, and the next shift starts a timer on a welder that is still down:
    two stoppages on record, one repair on the floor."""
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": ALL_OPEN})
    ids, tmpl = _line(a)
    card = _lot(a, ids, tmpl)
    sid = _start(a, ids, card)
    clock.tick(5 * 60)
    a.req("POST", f"/sessions/{sid}/pause", {"reason": "breakdown"})
    clock.tick(10 * 60)
    a.req("POST", f"/sessions/{sid}/end", {"quantity": 4})   # closes the pause with it
    clock.tick(10 * 60)
    sid2 = _start(a, ids, card, n=6, op="bea")
    a.req("POST", f"/sessions/{sid2}/pause", {"reason": "breakdown"})
    clock.tick(20 * 60)
    a.req("POST", f"/sessions/{sid2}/resume")
    clock.tick(5 * 60)
    a.req("POST", f"/sessions/{sid2}/end", {})
    m, _ = _model(a)
    cut = m.stations[ids["Cut"]]
    assert cut.repairs == [pytest.approx(30 * 60)]


def _one_station(product_seq, co_on_change, co_prob=1.0, gap=10_000.0):
    st = {"a": StationModel(id="a", name="a", rates=[10.0], changeovers=[600.0],
                            co_prob=co_prob, co_on_change=co_on_change)}
    arr = [ArrivalIn(t=gap * k, qty=1, process="p", station="a", product=pr)
           for k, pr in enumerate(product_seq)]
    return LineModel(stations=st, routing={("p", "a"): [("end", 1.0, "move")]}, merges={},
                     merge_lot={}, endpoints={("p", "end")}, arrivals=arr,
                     horizon=gap * len(product_seq))


def test_a_changeover_follows_a_change_of_product():
    m = _one_station(["L", "L", "L", "R", "R", "R"], co_on_change=True)
    res = run(m, [Scenario("same")], replications=2)
    # One change of product in six lots: one 600 s changeover.
    assert res["baseline"]["leadTimeSec"] == pytest.approx(10 + 600 / 6)
