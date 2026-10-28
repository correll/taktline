"""The what-if model, against lines whose answer is known by arithmetic.

Deterministic work times make the expected lead times exact, so these check
the queueing, the merge and the ranking rather than the dice. The endpoint
test at the end drives a real line through the API and checks that the model
reproduces the lead time the line actually had.
"""
from datetime import timedelta

import pytest

from app.core.whatif import (ArrivalIn, Assumptions, Change, LineModel, Scenario, StationModel,
                             automation_candidates, run)
from tests.test_stoppages import Clock, _line, _lot, _start, clock  # noqa: F401
from tests.helpers import bootstrap_admin


def _chain(rates: dict, arrivals: list, horizon: float, fail=None) -> LineModel:
    """Stations s0 -> s1 -> ... -> end, one process 'p'."""
    names = list(rates) + ["end"]
    st = {n: StationModel(id=n, name=n, rates=[r]) for n, r in rates.items()}
    if fail:
        for n, (rate, repair) in fail.items():
            st[n].fail_rate, st[n].repairs = rate, [repair]
    routing = {("p", a): [(b, 1.0, "move")] for a, b in zip(names, names[1:])}
    return LineModel(stations=st, routing=routing, merges={}, merge_lot={},
                     endpoints={("p", "end")}, arrivals=arrivals, horizon=horizon)


# ── Assumptions the record can replace ─────────────────────────────────────

def test_a_buffer_too_large_to_fill_changes_nothing():
    """The model with an assumption that never binds is the model without it,
    to the last digit: the replacements are a separate path, not a rewrite."""
    arr = [ArrivalIn(t=300.0 * k, qty=5, process="p", station="a") for k in range(60)]
    m = _chain({"a": 50.0, "b": 70.0}, arr, 20000, fail={"b": (1 / 4000, 600.0)})
    plain = run(m, [Scenario("tpm", [Change("b", breakdowns=False)])], replications=4)
    m.assumptions = Assumptions(buffers={"b": 10 ** 9})
    bounded = run(m, [Scenario("tpm", [Change("b", breakdowns=False)])], replications=4)
    assert bounded == plain


def test_one_operator_for_two_stations_works_one_lot_at_a_time():
    """Two lots at once, 30 s at a then 40 s at b. Staffed independently they
    finish at 70 and 110 s (mean 90). One operator for both, first come first
    served: a lot1 0-30, a lot2 30-60, b lot1 60-100, b lot2 100-140 (mean 120)."""
    arr = [ArrivalIn(t=0.0, qty=1, process="p", station="a") for _ in range(2)]
    m = _chain({"a": 30.0, "b": 40.0}, arr, 1000)
    assert run(m, [], replications=1)["baseline"]["leadTimeSec"] == pytest.approx(90)
    m.assumptions = Assumptions(shared=[(["a", "b"], 1)])
    assert run(m, [], replications=1)["baseline"]["leadTimeSec"] == pytest.approx(120)


def test_a_crew_that_shrinks_over_the_day_is_read_from_the_schedule():
    """Two servers until 1000 s, one after: two 100 s lots arriving at 1010 s
    are worked one after the other (lead 100 and 200), not side by side."""
    arr = [ArrivalIn(t=1010.0, qty=1, process="p", station="a") for _ in range(2)]
    m = _chain({"a": 100.0}, arr, 3000)
    m.stations["a"].servers = 2
    assert run(m, [], replications=1)["baseline"]["leadTimeSec"] == pytest.approx(100)
    m.assumptions = Assumptions(staffing={"a": [(0.0, 2), (1000.0, 1)]})
    assert run(m, [], replications=1)["baseline"]["leadTimeSec"] == pytest.approx(150)


def test_a_full_buffer_holds_the_station_feeding_it():
    """Station a feeds both b (slow, room for one lot) and c. With b full, a
    keeps its finished lot and cannot start the next one, so the other value
    stream through a waits too: the line's lead time grows."""
    st = {"a": StationModel(id="a", name="a", rates=[10.0]),
          "b": StationModel(id="b", name="b", rates=[200.0]),
          "c": StationModel(id="c", name="c", rates=[10.0])}
    routing = {("p1", "a"): [("b", 1.0, "move")], ("p1", "b"): [("end", 1.0, "move")],
               ("p2", "a"): [("c", 1.0, "move")], ("p2", "c"): [("end", 1.0, "move")]}
    arr = []
    for k in range(10):
        arr.append(ArrivalIn(t=100.0 * k, qty=1, process="p1", station="a"))
        arr.append(ArrivalIn(t=100.0 * k + 1, qty=1, process="p2", station="a"))
    m = LineModel(stations=st, routing=routing, merges={}, merge_lot={},
                  endpoints={("p1", "end"), ("p2", "end")}, arrivals=arr, horizon=5000)
    free = run(m, [], replications=1)["baseline"]["leadTimeSec"]
    m.assumptions = Assumptions(buffers={"b": 1})
    held = run(m, [], replications=1)["baseline"]["leadTimeSec"]
    assert held > free * 1.5, (free, held)


def test_breakdowns_on_the_calendar_strike_an_idle_station():
    """A station that works 10 s an hour meets almost no breakdowns per
    working second, but on the calendar it is down a third of the time (one
    every hour, half an hour to repair), and a lot that arrives then waits."""
    arr = [ArrivalIn(t=3600.0 * k + 1234.5, qty=1, process="p", station="a") for k in range(400)]
    m = _chain({"a": 10.0}, arr, 400 * 3600, fail={"a": (1 / 3600, 1800.0)})
    work_clock = run(m, [], replications=3)["baseline"]["leadTimeSec"]
    m.assumptions = Assumptions(open_failures={"a": 1 / 3600})
    calendar = run(m, [], replications=3)["baseline"]["leadTimeSec"]
    assert work_clock < 20
    assert calendar > 150, calendar
    # removing the breakdowns removes the waiting, whichever clock they ran on
    res = run(m, [Scenario("tpm", [Change("a", breakdowns=False)])], replications=3)
    assert res["scenarios"][0]["leadTimeSec"] == pytest.approx(10)


def test_an_unloaded_station_contributes_exactly_its_work():
    arr = [ArrivalIn(t=1200.0 * k, qty=10, process="p", station="a") for k in range(20)]
    m = _chain({"a": 60.0}, arr, 24000)
    res = run(m, [Scenario("robot", [Change("a", speed=0.5)])], replications=3)
    assert res["baseline"]["leadTimeSec"] == pytest.approx(600)
    assert res["scenarios"][0]["gainSec"] == pytest.approx(300)


def test_a_robot_at_the_overloaded_station_wins_and_the_ranking_says_so():
    # 'a' needs 600 s per lot against a lot every 550 s: a queue builds there.
    # 'b' has slack. The same robot saves far more at 'a'.
    arr = [ArrivalIn(t=550.0 * k, qty=10, process="p", station="a") for k in range(40)]
    m = _chain({"a": 60.0, "b": 20.0}, arr, 22000)
    res = automation_candidates(m, speed=0.75, cv=None, replications=3)
    order = [r["name"] for r in res["scenarios"]]
    assert order == ["a", "b"]
    assert res["scenarios"][0]["gainSec"] > 10 * res["scenarios"][1]["gainSec"]


def test_breakdowns_accrue_on_working_time():
    # One failure per 600 working seconds, a 300 s repair: a lot of 600 s
    # meets about one. A process twice as fast meets about half as many.
    arr = [ArrivalIn(t=5000.0 * k, qty=10, process="p", station="a") for k in range(200)]
    m = _chain({"a": 60.0}, arr, 1_000_000, fail={"a": (1 / 600, 300.0)})
    res = run(m, [Scenario("fast", [Change("a", speed=0.5)]),
                  Scenario("fast, no breakdowns", [Change("a", speed=0.5, breakdowns=False)])],
              replications=4)
    base, fast, clean = (res["baseline"]["leadTimeSec"], res["scenarios"][0]["leadTimeSec"],
                         res["scenarios"][1]["leadTimeSec"])
    assert base == pytest.approx(900, rel=0.1)
    assert fast == pytest.approx(450, rel=0.1)
    assert clean == pytest.approx(300)


def test_a_merge_waits_for_its_matched_set():
    # Frames arrive one at a time, panels two at a time; an assembly takes one
    # frame and two panels and then 100 s of work.
    st = {"asm": StationModel(id="asm", name="Assembly", rates=[100.0])}
    m = LineModel(
        stations=st,
        routing={("p", "asm"): [("end", 1.0, "move")]},
        merges={("p", "asm"): {"frames": 1, "panels": 2}}, merge_lot={("p", "asm"): 1},
        endpoints={("p", "end")},
        arrivals=[ArrivalIn(t=1000.0 * k, qty=1, process="p", station="asm", feed="frames")
                  for k in range(10)]
        + [ArrivalIn(t=1000.0 * k + 500, qty=2, process="p", station="asm", feed="panels")
           for k in range(10)],
        horizon=10000)
    res = run(m, [Scenario("same")], replications=2)
    # An assembly's parts entered at k*1000 (one frame) and k*1000+500 (two
    # panels): a unit-weighted entry of k*1000+333. It is assembled when the
    # panels arrive and worked for 100 s, so it leaves at k*1000+600.
    assert res["baseline"]["leadTimeSec"] == pytest.approx(600 - 1000 / 3)


def test_the_model_reproduces_the_lead_time_the_line_had(actor, clock, monkeypatch):  # noqa: F811
    """A lot of ten every 20 minutes through Cut (6 s/unit) and Pack (3 s/unit);
    the observed lead time is the 90 s of work, and the model, built from
    the sessions and moves alone, says the same."""
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})
    ids, tmpl = _line(a)
    # An entry queue in front of Cut, so releases are recorded as moves.
    for k in range(6):
        card = _lot(a, ids, tmpl)
        sid = _start(a, ids, card)
        clock.tick(60)
        a.req("POST", f"/sessions/{sid}/end", {})
        a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Cut"],
                                                 "toStationId": ids["Pack"], "quantity": 10})
        sid = _start(a, ids, card, station="Pack", op="bob")
        clock.tick(30)
        a.req("POST", f"/sessions/{sid}/end", {})
        a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Pack"],
                                                 "toStationId": ids["Store"], "quantity": 10})
        clock.tick(1110)
    from app.routers import analysis as analysis_router
    monkeypatch.setattr(analysis_router, "utcnow", clock)
    r = a.req("POST", "/analysis/what-if", {"scenarios": [
        {"name": "faster pack", "changes": [{"stationId": ids["Pack"], "speedFactor": 0.5}]}],
        "replications": 3, "days": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    cal = body["calibration"]
    assert cal["observedLeadTimeHours"] == pytest.approx(30 / 3600, abs=2e-5)
    assert cal["modelLeadTimeHours"] == pytest.approx(30 / 3600, abs=2e-5)
    assert body["scenarios"][0]["gainHours"] == pytest.approx(15 / 3600, abs=2e-5)
    ranked = a.req("POST", "/analysis/automation", {"replications": 3, "days": 1,
                                                    "cv": None}).json()
    assert ranked["scenarios"][0]["name"] == "Pack"

    # What the record says about the idealisations, and replacing them.
    ev = a.req("GET", "/analysis/assumptions?days=1")
    assert ev.status_code == 200, ev.text
    ev = ev.json()
    assert ev["staffing"]["Pack"]["max"] == 1 and ev["buffers"]["Pack"]["maxLots"] >= 1
    assert any(set(p["stations"]) == {"Cut", "Pack"} for p in ev["sharedCrew"])
    same = a.req("POST", "/analysis/what-if", {"scenarios": [
        {"name": "faster pack", "changes": [{"stationId": ids["Pack"], "speedFactor": 0.5}]}],
        "replications": 3, "days": 1, "assumptions": {}}).json()
    assert same == body                       # nothing named, nothing replaced
    staffed = a.req("POST", "/analysis/what-if", {"scenarios": [
        {"name": "faster pack", "changes": [{"stationId": ids["Pack"], "speedFactor": 0.5}]}],
        "replications": 3, "days": 1,
        "assumptions": {"recordedStaffing": [ids["Pack"]], "buffers": {ids["Pack"]: 0}}})
    assert staffed.status_code == 200, staffed.text
    bad = a.req("POST", "/analysis/what-if", {"scenarios": [{"name": "x", "changes": []}],
                                              "replications": 3, "days": 1,
                                              "assumptions": {"openHourBreakdowns": ["nope"]}})
    assert bad.status_code == 404




def test_units_on_the_floor_when_the_record_begins_do_not_shorten_lead_times(actor, clock, monkeypatch):  # noqa: F811
    """Half of a lot of twenty enters before the record begins (the history
    was reset) and finishes inside it. First in, first out, it would take the
    entry time of the half behind it, and that half's hour would read as
    half an hour. It queues first with no entry time instead: the lead time
    is the hour the second half actually took."""
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})
    ids, tmpl = _line(a)
    card = _lot(a, ids, tmpl, n=20)
    move = lambda f, t: a.req("POST", f"/cards/{card}/advance", {
        "fromStationId": ids[f], "toStationId": ids[t], "quantity": 10})
    move("Cut", "Pack")
    clock.tick(600)
    assert a.req("POST", "/admin/reset-statistics", {}).status_code < 400
    clock.tick(3000)
    move("Cut", "Pack")                       # the half the record sees enter
    for _ in range(2):
        sid = _start(a, ids, card, station="Pack", op="bob")
        clock.tick(1800)
        a.req("POST", f"/sessions/{sid}/end", {})
        move("Pack", "Store")
    from app.routers import analysis as analysis_router
    monkeypatch.setattr(analysis_router, "utcnow", clock)
    r = a.req("POST", "/analysis/what-if", {"scenarios": [
        {"name": "faster pack", "changes": [{"stationId": ids["Pack"], "speedFactor": 0.5}]}],
        "replications": 2, "days": 1})
    assert r.status_code == 200, r.text
    assert r.json()["calibration"]["observedLeadTimeHours"] == pytest.approx(1.0, abs=1e-3)


def test_a_timer_the_move_closed_stays_with_its_own_visit(actor, clock, monkeypatch):  # noqa: F811
    """Ten units of a lot are worked at Pack and moved on with Stop forgotten,
    so the move closes the timer, a moment after the departure is recorded.
    Then the other ten arrive and are worked properly. Each visit took 60 s a
    unit; filed under the second visit, the first timer would merge the two
    into one sample spanning the wait between them."""
    from app.routers import cards as cards_router
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})
    ids, tmpl = _line(a)
    card = _lot(a, ids, tmpl, n=20)

    def ticking():                      # every read of the clock moves it on 1 ms
        clock.tick(0.001)
        return clock.t
    monkeypatch.setattr(cards_router, "utcnow", ticking)
    move = lambda f, t: a.req("POST", f"/cards/{card}/advance", {
        "fromStationId": ids[f], "toStationId": ids[t], "quantity": 10})
    move("Cut", "Pack")
    _start(a, ids, card, station="Pack", op="bob")
    clock.tick(600)
    move("Pack", "Store")               # Stop forgotten: the move closes it
    clock.tick(3000)
    move("Cut", "Pack")
    sid = _start(a, ids, card, station="Pack", op="bob")
    clock.tick(600)
    a.req("POST", f"/sessions/{sid}/end", {})
    move("Pack", "Store")
    import asyncio, uuid
    from app.core import whatif_data
    from app.db.connection import SessionLocal

    async def rates():
        async with SessionLocal() as s:
            m, _ = await whatif_data.build_model(s, uuid.UUID(a.company), clock.t - timedelta(days=1),
                                                 clock.t, [[15] * 24 for _ in range(7)], "UTC")
            return m.stations[ids["Pack"]].rates
    got = asyncio.run(rates())
    assert len(got) == 2 and all(abs(r - 60) < 1 for r in got), got


def test_a_timer_forgotten_at_a_shift_change_is_not_a_second_server(actor, clock, monkeypatch):  # noqa: F811
    """Ann forgets to stop her last lot; Bob, on the next shift, starts his
    own at the same bench while hers still runs, and her timer ends only when
    the lot leaves. The two timers overlap, but the bench never had two
    people: the model keeps one server, and her timer is not a reading."""
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})
    ids, tmpl = _line(a)
    for _ in range(6):                                  # stopped timers, one at a time
        card = _lot(a, ids, tmpl)
        sid = _start(a, ids, card, op="ann")
        clock.tick(600)
        a.req("POST", f"/sessions/{sid}/end", {})
        a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Cut"],
                                                 "toStationId": ids["Pack"], "quantity": 10})
    late = _lot(a, ids, tmpl)
    _start(a, ids, late, op="ann")                      # never stopped
    clock.tick(600)
    nxt = _lot(a, ids, tmpl)
    sid = _start(a, ids, nxt, op="bob")                 # the next shift
    clock.tick(600)
    a.req("POST", f"/sessions/{sid}/end", {})
    for c in (late, nxt):
        a.req("POST", f"/cards/{c}/advance", {"fromStationId": ids["Cut"],
                                              "toStationId": ids["Pack"], "quantity": 10})
    import asyncio, uuid
    from app.core import whatif_data
    from app.db.connection import SessionLocal

    async def model():
        async with SessionLocal() as s:
            m, _ = await whatif_data.build_model(s, uuid.UUID(a.company), clock.t - timedelta(days=1),
                                                 clock.t, [[15] * 24 for _ in range(7)], "UTC")
            return m.stations[ids["Cut"]]
    cut = asyncio.run(model())
    assert cut.servers == 1
    assert all(abs(r - 60) < 1 for r in cut.rates), cut.rates


def test_moves_alone_give_each_lot_its_flow_time(actor, clock):  # noqa: F811
    """Nobody times anything; lots are only moved. Each still has a flow time
    from leaving Cut to reaching the store, and it is the one the record
    shows: 600 s at Pack."""
    a = actor(); bootstrap_admin(a)
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})
    ids, tmpl = _line(a)
    for _ in range(3):
        card = _lot(a, ids, tmpl)
        a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Cut"],
                                                 "toStationId": ids["Pack"], "quantity": 10})
        clock.tick(600)
        a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Pack"],
                                                 "toStationId": ids["Store"], "quantity": 10})
        clock.tick(300)
    import asyncio, uuid
    from app.core import whatif_data
    from app.db.connection import SessionLocal

    async def lead():
        async with SessionLocal() as s:
            m, _ = await whatif_data.build_model(s, uuid.UUID(a.company), clock.t - timedelta(days=1),
                                                 clock.t, [[15] * 24 for _ in range(7)], "UTC")
            return m.observed_lead_sec, m.observed_n
    sec, n = asyncio.run(lead())
    assert n == 30 and abs(sec - 600) < 1e-6



def test_each_lot_is_counted_in_its_own_value_stream_where_streams_share_every_route(actor, clock):  # noqa: F811
    """Two value streams drawn over the same benches: no route belongs to one
    of them alone, so the routes a lot took cannot say which stream it is in.
    The lot card can, and its flow time must be counted there; otherwise the
    stream reports no measured lead time at all, however many lots finished."""
    a = actor(); bootstrap_admin(a)
    hours = [[15] * 24 for _ in range(7)]
    a.req("PUT", "/global-settings/", {"workHours": hours})
    ids, tmpl = _line(a)
    proc2 = a.req("POST", "/processes/", {"name": "Second line"}).json()["_id"]
    for load, unload in (("Cut", "Pack"), ("Pack", "Store")):
        r = a.req("POST", "/routes/", {"processId": proc2, "load": ids[load],
                                       "unload": ids[unload], "quantity": 1})
        assert r.status_code in (200, 201), r.text
    for _ in range(3):
        card = _lot(a, ids, tmpl)
        a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Cut"],
                                                 "toStationId": ids["Pack"], "quantity": 10})
        clock.tick(600)
        a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Pack"],
                                                 "toStationId": ids["Store"], "quantity": 10})
        clock.tick(300)
    import asyncio, uuid
    from app.core import whatif_data
    from app.db.connection import SessionLocal

    async def by_process():
        async with SessionLocal() as s:
            m, _ = await whatif_data.build_model(s, uuid.UUID(a.company), clock.t - timedelta(days=1),
                                                 clock.t, hours, "UTC")
            return m.observed_by_process
    obs = asyncio.run(by_process())
    assert set(obs) == {tmpl["processId"]}
    sec, n = obs[tmpl["processId"]]
    assert n == 30 and abs(sec - 600) < 1e-6


def test_an_arrival_enters_the_value_stream_its_card_names(actor, clock):  # noqa: F811
    """Two value streams leave the same release queue by the same route and
    part later. An arrival placed by its route alone went to whichever stream
    came first, and every lot of the other was routed through stations it never
    visits; the lot card names its stream."""
    from tests.test_stoppages import _station
    a = actor(); bootstrap_admin(a)
    hours = [[15] * 24 for _ in range(7)]
    a.req("PUT", "/global-settings/", {"workHours": hours})
    doc = {"kind": "taktline-map", "version": 1, "name": "Shared release",
           "mapSettings": {"unit": "m", "pixelsPerUnit": 10, "stationSizeUnits": 3},
           "stations": [_station("q", "Release"), _station("a", "Cut"), _station("b", "Pack"),
                        _station("s", "Store", True)],
           "processes": [{"ref": "p1", "name": "Long", "description": "", "desiredTaktSec": None},
                         {"ref": "p2", "name": "Short", "description": "", "desiredTaktSec": None}],
           "templates": [{"ref": "t1", "name": "Long part", "description": "", "process": "p1",
                          "startStation": "q", "color": None, "fields": []},
                         {"ref": "t2", "name": "Short part", "description": "", "process": "p2",
                          "startStation": "q", "color": None, "fields": []}],
           "routes": [{"process": "p1", "load": "q", "unload": "a", "quantity": 1, "outputTemplate": None},
                      {"process": "p1", "load": "a", "unload": "b", "quantity": 1, "outputTemplate": None},
                      {"process": "p1", "load": "b", "unload": "s", "quantity": 1, "outputTemplate": None},
                      {"process": "p2", "load": "q", "unload": "a", "quantity": 1, "outputTemplate": None},
                      {"process": "p2", "load": "a", "unload": "s", "quantity": 1, "outputTemplate": None}]}
    assert a.req("POST", "/map-io/import", doc).status_code == 200
    ids = {s["name"]: s["_id"] for s in a.req("GET", "/stations/").json()}
    tm = {t["name"]: t for t in a.req("GET", "/lot-templates/").json()}
    for name in ("Long part", "Short part", "Short part"):
        t = tm[name]
        card = a.req("POST", "/cards/", {"lotTemplateId": t["_id"], "processId": t["processId"],
                                         "totalQuantity": 1, "bins": {ids["Release"]: {"count": 1}}}).json()["_id"]
        a.req("POST", f"/cards/{card}/advance", {"fromStationId": ids["Release"],
                                                 "toStationId": ids["Cut"], "quantity": 1})
        clock.tick(60)
    import asyncio, uuid
    from app.core import whatif_data
    from app.db.connection import SessionLocal

    async def arrivals():
        async with SessionLocal() as s:
            m, _ = await whatif_data.build_model(s, uuid.UUID(a.company), clock.t - timedelta(days=1),
                                                 clock.t, hours, "UTC")
            return [x.process for x in m.arrivals]
    got = asyncio.run(arrivals())
    assert sorted(got) == sorted([tm["Long part"]["processId"]] + [tm["Short part"]["processId"]] * 2)

def test_wip_and_spread_follow_littles_law_and_the_variability():
    """Lots of ten every 1200 s through 600 s of work: each unit waits 600 s,
    the spread is zero, and halving the work halves the WIP."""
    arr = [ArrivalIn(t=1200.0 * k, qty=10, process="p", station="a") for k in range(20)]
    m = _chain({"a": 60.0}, arr, 24000)
    res = run(m, [Scenario("robot", [Change("a", speed=0.5)])], replications=2)
    b, s = res["baseline"], res["scenarios"][0]
    assert b["leadSpreadSec"] == pytest.approx(0)
    assert b["wip"] == pytest.approx(600 * 200 / 24000)
    assert s["wipReduction"] == pytest.approx(b["wip"] / 2, rel=0.02)
