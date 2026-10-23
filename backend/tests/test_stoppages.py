"""Stoppages, and work timers that tell the truth when operators forget.

Three design decisions:

* A Pause keeps a breakdown out of cycle time and records it as downtime. A
  timer left running through repairs read a fifth over the work content, and
  the station's uptime was nowhere to be found.
* A lot that leaves a station closes any session still open on it there. One
  forgotten Stop in twenty inflated cycle time by a quarter at stations with
  slack, and could hide the constraint behind them.
* A session closed only by the operator's next Start is not a reading of the
  work, and cycle time is read without it.

The clock is controlled, so durations are exact.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.routers import cards as cards_router
from app.routers import sessions as sessions_router
from tests.helpers import bootstrap_admin


class Clock:
    def __init__(self):
        self.t = datetime(2027, 1, 4, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def tick(self, seconds):
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(sessions_router, "utcnow", c)
    monkeypatch.setattr(cards_router, "utcnow", c)
    return c


def _station(ref, name, store=False):
    return {"ref": ref, "name": name, "description": "",
            "position": {"x": 100, "y": 100, "width": 72, "height": 72}, "color": None,
            "icon": "Box", "isStorage": store, "branchMode": None,
            "integrationProvider": None, "integrationRole": None}


def _line(a):
    doc = {"kind": "taktline-map", "version": 1, "name": "Two benches",
           "mapSettings": {"unit": "m", "pixelsPerUnit": 10, "stationSizeUnits": 3},
           "stations": [_station("a", "Cut"), _station("b", "Pack"), _station("s", "Store", True)],
           "processes": [{"ref": "p", "name": "Line", "description": "", "desiredTaktSec": None}],
           "templates": [{"ref": "t", "name": "Widget", "description": "", "process": "p",
                          "startStation": "a", "color": None, "fields": []}],
           "routes": [{"process": "p", "load": "a", "unload": "b", "quantity": 1, "outputTemplate": None},
                      {"process": "p", "load": "b", "unload": "s", "quantity": 1, "outputTemplate": None}]}
    assert a.req("POST", "/map-io/import", doc).status_code == 200
    ids = {s["name"]: s["_id"] for s in a.req("GET", "/stations/").json()}
    tmpl = a.req("GET", "/lot-templates/").json()[0]
    return ids, tmpl


def _lot(a, ids, tmpl, n=10):
    r = a.req("POST", "/cards/", {"lotTemplateId": tmpl["_id"], "processId": tmpl["processId"],
                                  "totalQuantity": n, "bins": {ids["Cut"]: {"count": n}}})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _start(a, ids, card, n=10, op="ann", station="Cut"):
    r = a.req("POST", "/sessions/", {"stationId": ids[station], "cardId": card,
                                     "operatorId": op, "quantity": n})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _session(a, sid):
    return next(s for s in a.req("GET", "/sessions/").json() if s["_id"] == sid)


def test_a_pause_keeps_a_breakdown_out_of_cycle_time_and_records_it(actor, clock):
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})
    ids, tmpl = _line(a)
    card = _lot(a, ids, tmpl)
    sid = _start(a, ids, card)
    clock.tick(300)
    assert a.req("POST", f"/sessions/{sid}/pause", {"reason": "breakdown"}).status_code == 200
    clock.tick(1200)
    assert a.req("POST", f"/sessions/{sid}/resume").status_code == 200
    clock.tick(300)
    s = a.req("POST", f"/sessions/{sid}/end", {"quantity": 10}).json()
    assert s["durationSec"] == 600 and s["pausedSec"] == 1200 and s["closedBy"] == "operator"
    stops = a.req("GET", "/stoppages/", ).json()
    assert [(x["reason"], x["durationSec"]) for x in stops] == [("breakdown", 1200)]
    stats = {r["stationId"]: r for r in a.req("GET", "/sessions/stats").json()}[ids["Cut"]]
    assert stats["cycleTimeSec"] == 60
    assert stats["downtimeSec"] == 1200 and stats["breakdowns"] == 1
    assert abs(stats["uptime"] - 600 / 1800) < 1e-9


def test_ending_a_paused_session_ends_the_stoppage_with_it(actor, clock):
    a = actor(); bootstrap_admin(a)
    ids, tmpl = _line(a)
    sid = _start(a, ids, _lot(a, ids, tmpl))
    clock.tick(100)
    a.req("POST", f"/sessions/{sid}/pause", {"reason": "changeover"})
    a.req("POST", f"/sessions/{sid}/pause", {"reason": "changeover"})   # a double tap
    clock.tick(50)
    s = a.req("POST", f"/sessions/{sid}/end", {}).json()
    assert s["durationSec"] == 100 and s["pausedSec"] == 50
    stops = a.req("GET", "/stoppages/").json()
    assert len(stops) == 1 and stops[0]["endedAt"] is not None


def test_a_stop_without_a_session_is_recorded_too(actor, clock):
    a = actor(); bootstrap_admin(a)
    ids, _ = _line(a)
    st = a.req("POST", "/stoppages/", {"stationId": ids["Pack"], "reason": "changeover"}).json()
    clock.tick(600)
    done = a.req("POST", f"/stoppages/{st['_id']}/end").json()
    assert done["durationSec"] == 600


def test_a_lot_that_leaves_closes_the_timer_left_running_on_it(actor, clock):
    a = actor(); bootstrap_admin(a)
    ids, tmpl = _line(a)
    card = _lot(a, ids, tmpl)
    sid = _start(a, ids, card)
    clock.tick(400)
    # Stop forgotten; part of the lot moves on, so work may still be going on.
    a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Cut"],
                                             "toStationId": ids["Pack"], "quantity": 4})
    assert _session(a, sid)["endedAt"] is None
    clock.tick(200)
    a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Cut"],
                                             "toStationId": ids["Pack"], "quantity": 6})
    s = _session(a, sid)
    assert s["closedBy"] == "move" and s["durationSec"] == 600


def test_a_session_closed_by_the_next_start_is_not_a_reading(actor, clock):
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})
    ids, tmpl = _line(a)
    for _ in range(3):                                  # three honest sessions, 60 s/unit
        sid = _start(a, ids, _lot(a, ids, tmpl))
        clock.tick(600)
        a.req("POST", f"/sessions/{sid}/end", {})
    _start(a, ids, _lot(a, ids, tmpl))                  # forgotten...
    clock.tick(5000)
    later = _start(a, ids, _lot(a, ids, tmpl))          # ...until the next Start
    forgotten = [s for s in a.req("GET", "/sessions/").json() if s["closedBy"] == "next_start"]
    assert len(forgotten) == 1 and forgotten[0]["durationSec"] == 5000
    clock.tick(600)
    a.req("POST", f"/sessions/{later}/end", {})
    stats = {r["stationId"]: r for r in a.req("GET", "/sessions/stats").json()}[ids["Cut"]]
    assert stats["cycleTimeSec"] == 60
    assert stats["unstoppedSessions"] == 1
    # Nor is it working time: its ten units are charged at 60 s each, so the
    # station worked 3000 of the 7400 s, not all of them.
    assert abs(stats["oee"] - 3000 / 7400) < 1e-6


def test_a_stoppage_counts_only_the_plants_open_time(actor, clock):
    """A changeover begun just before the shift ends and closed the next
    morning took minutes of the plant's time, not the night."""
    a = actor(); bootstrap_admin(a)
    hours = [[15 if 6 <= h < 22 else 0 for h in range(24)] for _ in range(7)]
    a.req("PUT", "/global-settings/", {"workHours": hours})
    ids, tmpl = _line(a)
    sid = _start(a, ids, _lot(a, ids, tmpl))
    clock.t = clock.t.replace(hour=21, minute=55)
    st = a.req("POST", "/stoppages/", {"stationId": ids["Cut"], "reason": "changeover"}).json()
    clock.t = clock.t + timedelta(hours=8, minutes=10)      # 06:05 next morning
    a.req("POST", f"/stoppages/{st['_id']}/end")
    a.req("POST", f"/sessions/{sid}/end", {})
    stats = {r["stationId"]: r for r in a.req("GET", "/sessions/stats").json()}[ids["Cut"]]
    assert stats["changeoverSec"] == 600


def test_average_wip_is_rebuilt_from_the_history(actor, clock):
    """Ten units sit at Cut for the first half of an open hour and at Pack for
    the second: each averaged five, whatever the board shows at the end."""
    a = actor(); bootstrap_admin(a)
    # Open all week, so the average is over plain elapsed time.
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})
    ids, tmpl = _line(a)
    card = _lot(a, ids, tmpl)
    clock.tick(1800)
    a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Cut"],
                                             "toStationId": ids["Pack"], "quantity": 10})
    clock.tick(1800)
    a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Pack"],
                                             "toStationId": ids["Store"], "quantity": 4})
    from app.core import flow
    import asyncio, uuid
    from app.db.connection import SessionLocal

    async def avg():
        async with SessionLocal() as s:
            start = clock.t - timedelta(seconds=3600)
            return await flow.average_wip(s, uuid.UUID(a.company), start, clock.t,
                                          [[15] * 24 for _ in range(7)], "UTC")
    got = asyncio.run(avg())
    assert abs(got[ids["Cut"]] - 5) < 1e-6 and abs(got[ids["Pack"]] - 5) < 1e-6


def test_a_station_where_work_only_waits_is_in_the_statistics(actor, clock):
    """No sessions and no departures, but units standing there: on a slow
    line that queue is the one that matters, and it must have a row."""
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})
    ids, tmpl = _line(a)
    _lot(a, ids, tmpl)
    clock.tick(3600)
    rows = {r["stationId"]: r for r in a.req("GET", "/sessions/stats").json()}
    assert ids["Cut"] in rows and abs(rows[ids["Cut"]]["wipAvg"] - 10) < 1e-6
