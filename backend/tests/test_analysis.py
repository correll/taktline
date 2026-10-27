"""The line doctor, tested against lines with planted faults.

The only honest way to know whether advice is any good is to build a line whose
problem you already know and check that the diagnosis names it — and, just as
importantly, that a healthy line produces silence. A checker that reports
something on every input is a horoscope.

The engine takes a plain snapshot, so most of this needs no database at all:
the line is a handful of dataclasses and the assertions are about which rules
fire. The last block goes through the real endpoint on a real line, because a
rule that only works on hand-built fixtures has not been tested against the
shapes the product actually produces.
"""

import json
from pathlib import Path

import pytest

from app.core.analysis import (
    CRITICAL, INSIGHT, WARNING, ProcessIn, RouteIn, Snapshot, StationIn,
    StationMetrics, TemplateIn, analyse,
)
from tests.helpers import Actor, bootstrap_admin

EXAMPLES = sorted((Path(__file__).resolve().parents[2] / "examples").glob("*.json"))


def rules(report) -> set:
    return {f.rule for f in report.findings}


def line(stations, routes, *, processes=(("p1", "Line", None),), templates=(),
         wip=None, metrics=None, ppu=0.0):
    """A line described in one call. `stations` is a list of (id, name, kw)."""
    return Snapshot(
        stations=[StationIn(id=s[0], name=s[1], **(s[2] if len(s) > 2 else {}))
                  for s in stations],
        routes=[RouteIn(load=r[0], unload=r[1], quantity=r[2] if len(r) > 2 else 1,
                        process=r[3] if len(r) > 3 else "p1") for r in routes],
        processes=[ProcessIn(id=p[0], name=p[1], desired_takt_sec=p[2]) for p in processes],
        templates=[TemplateIn(id=t[0], name=t[1], process=t[2], start_station=t[3])
                   for t in templates],
        wip=wip or {},
        metrics=metrics or {},
        pixels_per_unit=ppu,
    )


CHAIN = [("cut", "Cut"), ("sew", "Sew"), ("pack", "Pack")]
CHAIN_ROUTES = [("cut", "sew"), ("sew", "pack")]
CHAIN_TMPL = [("t1", "Shirt", "p1", "cut")]


# ── A healthy line says nothing alarming ────────────────────────────────────

def test_a_sound_line_raises_nothing_serious():
    """The most important test here. A checker that always finds something
    teaches people to ignore it, and then it is worse than absent."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     processes=(("p1", "Shirts", 300.0),)))
    serious = [f for f in r.findings if f.severity in (CRITICAL, WARNING)]
    assert serious == [], [f.rule for f in serious]
    assert r.readiness == "no-data"


def test_it_says_plainly_when_there_is_no_timing_data():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL))
    assert r.readiness == "no-data"
    assert any("timer" in p for p in r.narrative), r.narrative
    # And it must not have invented a bottleneck out of nothing.
    assert not {"bottleneck", "line-imbalance"} & rules(r)


def test_moves_alone_give_a_lead_time():
    """A shop that only moves lots on the board, and times nothing, still has
    a lead time: each lot's own flow time once twenty units have finished.
    It must not wait for the first timer, and it must not pretend to know the
    flow efficiency."""
    snap = line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL)
    snap.wip_avg_by_process = {("cut", "p1"): 4.0, ("sew", "p1"): 6.0}
    snap.exit_rate_by_process = {("pack", "p1"): 1 / 120}
    snap.observed_lead_by_process = {"p1": (3600.0, 40)}
    r = analyse(snap)
    assert r.readiness == "no-data"
    f = next(f for f in r.findings if f.rule == "lead-time")
    assert f.metrics["leadSec"] == 3600 and f.metrics["leadBasis"] == "measured"
    assert "flow-efficiency" not in rules(r)


# ── Topology: findable before anyone presses Start ──────────────────────────

def test_an_empty_line_is_reported_as_unconnected():
    r = analyse(line([("a", "A")], []))
    assert "no-flow" in rules(r)
    assert r.findings[0].severity == CRITICAL


def test_a_line_that_can_never_finish():
    # Everything sends work onward; nothing is a finished-goods end.
    r = analyse(line(CHAIN, CHAIN_ROUTES + [("pack", "cut")], templates=CHAIN_TMPL))
    assert "no-finished-end" in rules(r)


def test_a_station_nothing_flows_through():
    r = analyse(line(CHAIN + [("lonely", "Old press")], CHAIN_ROUTES, templates=CHAIN_TMPL))
    assert "island-station" in rules(r)
    f = next(f for f in r.findings if f.rule == "island-station")
    assert "Old press" in f.detail


def test_a_split_that_delivers_more_than_the_line_consumes():
    """The cut-and-sew case: one lay yields six panels, the bench takes one.
    Nobody is working badly — it is built into the weights."""
    r = analyse(line(
        [("cut", "Spread & cut"), ("panels", "Panels"), ("off", "Offcuts"), ("sew", "Sew")],
        [("cut", "panels", 6), ("cut", "off", 1), ("panels", "sew", 1)],
        templates=[("t1", "Shirt", "p1", "cut")]))
    assert "accumulation" in rules(r)
    f = next(f for f in r.findings if f.rule == "accumulation")
    assert f.waste == "Overproduction"
    assert f.metrics["surplus"] >= 1
    assert "Panels" in f.title


def test_a_branch_to_storage_is_not_an_accumulation():
    """The relief valve the warning exists to recommend. Flagging a line that
    has already taken the advice is how a checker loses credibility."""
    r = analyse(line(
        [("cut", "Cut"), ("panels", "Panels"), ("store", "Spares", {"is_storage": True}),
         ("sew", "Sew")],
        [("cut", "panels", 6), ("panels", "sew", 1), ("panels", "store", 1)],
        templates=[("t1", "Shirt", "p1", "cut")]))
    assert "accumulation" not in rules(r)


def test_the_station_everything_has_to_cross():
    r = analyse(line(
        [("a", "Cut A"), ("b", "Cut B"), ("sew", "Sewing line"), ("pack", "Pack")],
        [("a", "sew"), ("b", "sew"), ("sew", "pack")],
        templates=[("t1", "Shirt", "p1", "a")]))
    f = next((f for f in r.findings if f.rule == "single-point-of-failure"), None)
    assert f and "Sewing line" in f.title


def test_a_missing_takt_is_mentioned_but_not_alarming():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL))
    f = next((f for f in r.findings if f.rule == "no-takt"), None)
    assert f and f.severity == INSIGHT


def floor_chain(lengths, names=("Cut", "Sew", "Press", "Iron", "Fold", "Pack", "Ship")):
    """Stations in a row, one route between neighbours, each `lengths[i]`
    metres long at ten pixels a metre."""
    xs = [0.0]
    for d in lengths:
        xs.append(xs[-1] + d * 10)
    ids = "abcdefgh"[:len(xs)]
    stations = [(ids[i], names[i], {"x": xs[i], "y": 0}) for i in range(len(xs))]
    routes = [(ids[i], ids[i + 1]) for i in range(len(lengths))]
    return stations, routes


def test_one_very_long_move_is_noticed():
    st, rt = floor_chain([10, 10, 10, 10, 460])
    r = analyse(line(st, rt, templates=[("t1", "Shirt", "p1", "a")], ppu=10.0))
    f = next((f for f in r.findings if f.rule == "long-transport"), None)
    assert f and f.waste == "Transport"
    assert set(f.stations) == {"e", "f"}


def test_a_move_beyond_tukeys_fence_is_noticed():
    """Four moves of 10 m put both hinges at 10 m, so the fence is 10 m and a
    25 m move lies beyond it, though it is well under three times the
    median."""
    st, rt = floor_chain([10, 10, 10, 10, 25])
    r = analyse(line(st, rt, templates=[("t1", "Shirt", "p1", "a")], ppu=10.0))
    f = next((f for f in r.findings if f.rule == "long-transport"), None)
    assert f and set(f.stations) == {"e", "f"}
    assert f.metrics["fence"] == 10.0


def test_a_widely_spread_floor_has_no_outlying_move():
    """Moves of 5, 10, 20, 60 and 70 m: the hinges are 10 and 60 m, the fence
    135 m, and no move is beyond it, although 70 m is more than three times
    the 20 m median."""
    st, rt = floor_chain([5, 10, 20, 60, 70])
    r = analyse(line(st, rt, templates=[("t1", "Shirt", "p1", "a")], ppu=10.0))
    assert "long-transport" not in rules(r)


def test_two_processes_sharing_the_long_move_do_not_crash_the_report():
    """Either/or routing is two processes over the same stations, so the same
    long move appears twice with identical length. max() over (distance,
    route) then compared the routes and raised TypeError: the whole report
    was a 500 on exactly the high-mix lines it is most useful for, where each
    routing is its own process."""
    st, rt = floor_chain([10, 10, 10, 10, 460])
    routes = [(x, y, 1, p) for p in ("p1", "p2") for x, y in rt]
    r = analyse(line(st, routes, processes=(("p1", "Route A", None), ("p2", "Route B", None)),
                     templates=[("t1", "Shirt", "p1", "a"), ("t2", "Shirt B", "p2", "a")], ppu=10.0))
    f = next((f for f in r.findings if f.rule == "long-transport"), None)
    assert f and set(f.stations) == {"e", "f"}


# ── Timing ──────────────────────────────────────────────────────────────────

def timed(**per_station):
    return {sid: StationMetrics(**kw) for sid, kw in per_station.items()}


BUSY = dict(sessions=6, units=30, working_sec=600.0)


def test_the_constraint_is_named():
    """The resource with the highest utilisation is the constraint, and
    every line has one: it is named even where no station is busy."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=20, line_cycle_sec=30, oee=0.3),
        sew=dict(**BUSY, cycle_sec=25, line_cycle_sec=30, oee=0.6),
        pack=dict(**BUSY, cycle_sec=20, line_cycle_sec=32, oee=0.4))))
    named = [f for f in r.findings if f.rule == "bottleneck"]
    assert len(named) == 1 and "Sew" in named[0].title and named[0].basis == "load"
    assert named[0].metrics["load"] == 0.6 and named[0].metrics["nextLoad"] == 0.4


def test_the_constraint_leaves_out_the_entry_station():
    """Cut is the busiest station but nothing feeds it: it runs at the release
    pace, so the constraint is the busiest of the rest."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=20, oee=0.95),
        sew=dict(**BUSY, cycle_sec=25, oee=0.5),
        pack=dict(**BUSY, cycle_sec=20, oee=0.6))))
    named = [f for f in r.findings if f.rule == "bottleneck"]
    assert [f.stations for f in named] == [["pack"]]


def test_one_candidate_is_not_enough_to_name_a_constraint():
    """With the entry left out, a two-station line has one candidate and
    nothing to compare it with."""
    r = analyse(line([("cut", "Cut"), ("sew", "Sew")], [("cut", "sew")], templates=CHAIN_TMPL,
                     metrics=timed(cut=dict(**BUSY, cycle_sec=20, oee=0.5),
                                   sew=dict(**BUSY, cycle_sec=25, oee=0.9))))
    assert "bottleneck" not in rules(r)


def test_a_station_that_cannot_hold_the_takt():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     processes=(("p1", "Shirts", 60.0),),
                     metrics=timed(
                         cut=dict(**BUSY, cycle_sec=30),
                         sew=dict(**BUSY, cycle_sec=200),
                         pack=dict(**BUSY, cycle_sec=25))))
    f = next((f for f in r.findings if f.rule == "over-takt"), None)
    assert f and f.severity == CRITICAL and "Sew" in f.title


FED_CHAIN = [("fabric", "Fabric")] + CHAIN
FED_ROUTES = [("fabric", "cut")] + CHAIN_ROUTES
FED_TMPL = [("t1", "Shirt", "p1", "fabric")]


def test_an_unbalanced_line():
    """112 s of work paced by a 90 s step fits in ⌈112 ÷ 90⌉ = 2 stations;
    three are staffed, so a whole station's worth is balance loss."""
    r = analyse(line(FED_CHAIN, FED_ROUTES, templates=FED_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=10),
        sew=dict(**BUSY, cycle_sec=90),
        pack=dict(**BUSY, cycle_sec=12))))
    f = next((f for f in r.findings if f.rule == "line-imbalance"), None)
    assert f and f.metrics["minStations"] == 2 and f.metrics["stations"] == 3


def test_a_lopsided_pair_that_needs_both_stations_is_not_unbalanced():
    """Sew carries 90 s and Pack 12 s: seven times apart, but 102 s of work
    paced by 90 s still needs two stations, so no station is lost to
    balance."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=10),
        sew=dict(**BUSY, cycle_sec=90),
        pack=dict(**BUSY, cycle_sec=12))))
    assert "line-imbalance" not in rules(r)


def test_work_that_is_not_repeatable():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=30, samples=[5, 90, 8, 70, 6, 95, 10]),
        sew=dict(**BUSY, cycle_sec=30),
        pack=dict(**BUSY, cycle_sec=30))))
    f = next((f for f in r.findings if f.rule == "uneven-work"), None)
    assert f and f.metrics["cv"] >= 0.75 and f.metrics["shape"] == "spread"


def test_two_operators_doing_the_same_job_very_differently():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=30,
                 operator_samples={"ann": [20, 22, 19, 21], "bo": [95, 90, 100, 97]}),
        sew=dict(**BUSY, cycle_sec=30),
        pack=dict(**BUSY, cycle_sec=30))))
    f = next((f for f in r.findings if f.rule == "operator-spread"), None)
    assert f and "standard work" in f.detail


def test_a_small_but_consistent_operator_difference_is_a_signal():
    """Ann takes about 20 s a piece and Bo about 30 s, each within half a
    second of their own mean: the gap between them is far outside what the
    variation in either one's work explains, though it is only 1.5×."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=25, operators={"ann": 20.04, "bo": 30.02},
                 operator_samples={"ann": [20, 20.5, 19.5, 20, 20.2],
                                   "bo": [30, 30.5, 29.5, 30, 30.1]}),
        sew=dict(**BUSY, cycle_sec=30),
        pack=dict(**BUSY, cycle_sec=30))))
    f = next((f for f in r.findings if f.rule == "operator-spread"), None)
    assert f and f.stations == ["cut"] and f.metrics["operators"] == 2


def test_operators_within_each_others_variation_are_not_flagged():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=30,
                 operator_samples={"ann": [20, 40, 25, 35], "bo": [30, 22, 38, 27]}),
        sew=dict(**BUSY, cycle_sec=30),
        pack=dict(**BUSY, cycle_sec=30))))
    assert "operator-spread" not in rules(r)


def test_an_operator_with_one_timed_lot_is_not_charted():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=30,
                 operator_samples={"ann": [20, 21, 20, 21], "bo": [95]}),
        sew=dict(**BUSY, cycle_sec=30),
        pack=dict(**BUSY, cycle_sec=30))))
    assert "operator-spread" not in rules(r)


def test_work_piling_up_in_one_place():
    """Forty units at Sew, one leaving every 30 s: by Little's law a unit
    waits 1200 s there, against 90 s of work on the whole line."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     wip={"cut": 2, "sew": 40, "pack": 1},
                     metrics=timed(cut=dict(**BUSY, cycle_sec=30, line_cycle_sec=30),
                                   sew=dict(**BUSY, cycle_sec=30, line_cycle_sec=30),
                                   pack=dict(**BUSY, cycle_sec=30, line_cycle_sec=30))))
    f = next((f for f in r.findings if f.rule == "wip-concentration"), None)
    assert f and f.waste == "Inventory" and f.stations == ["sew"]
    assert "Little's law" in f.detail
    assert f.metrics["waitSec"] == 1200.0 and f.metrics["workSec"] == 90.0


def test_a_short_queue_that_outlasts_the_work_is_named():
    """Four units leaving one a minute wait four minutes: more than the 90 s
    of work a unit receives, though four units is a small pile."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     wip={"sew": 4},
                     metrics=timed(cut=dict(**BUSY, cycle_sec=30, line_cycle_sec=60),
                                   sew=dict(**BUSY, cycle_sec=30, line_cycle_sec=60),
                                   pack=dict(**BUSY, cycle_sec=30, line_cycle_sec=60))))
    f = next((f for f in r.findings if f.rule == "wip-concentration"), None)
    assert f and f.stations == ["sew"] and f.metrics["waitSec"] == 240.0


def test_most_of_the_wip_in_one_place_is_not_a_problem_if_it_drains_fast():
    """Nine of eleven units sit at Sew, but leaving one every 5 s they wait
    45 s — half the work a unit receives."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     wip={"cut": 1, "sew": 9, "pack": 1},
                     metrics=timed(cut=dict(**BUSY, cycle_sec=30, line_cycle_sec=5),
                                   sew=dict(**BUSY, cycle_sec=30, line_cycle_sec=5),
                                   pack=dict(**BUSY, cycle_sec=30, line_cycle_sec=5))))
    assert "wip-concentration" not in rules(r)


def test_a_shelf_full_of_stock_is_not_a_problem():
    """A warehouse is meant to fill up. Reporting it is noise."""
    r = analyse(line(
        [("cut", "Cut"), ("sew", "Sew"), ("store", "Finished goods", {"is_storage": True})],
        [("cut", "sew"), ("sew", "store")], templates=[("t1", "Shirt", "p1", "cut")],
        wip={"cut": 1, "sew": 1, "store": 400},
        metrics=timed(cut=dict(**BUSY, cycle_sec=30), sew=dict(**BUSY, cycle_sec=30))))
    assert "wip-concentration" not in rules(r)


def test_partial_data_is_labelled_as_such():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     metrics=timed(cut=dict(sessions=2, units=4, working_sec=40.0,
                                            cycle_sec=10))))
    assert r.readiness == "partial"
    assert any("not enough" in p or "longer" in p for p in r.narrative), r.narrative


# ── Against the lines the product actually ships ────────────────────────────

@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_every_shipped_example_gets_a_readable_report(actor, example):
    """A rule that only holds for hand-built fixtures has not been tested. These
    are real topologies — split-fed merges, two processes on one bench, an ERP
    boundary — and the report has to survive all of them."""
    a = actor(); bootstrap_admin(a)
    assert a.req("POST", "/map-io/import", json.loads(example.read_text())).status_code == 200

    r = a.req("GET", "/analysis/")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["readiness"] == "no-data"
    assert body["headline"]
    assert body["narrative"]
    for f in body["findings"]:
        assert f["title"] and f["detail"]
        assert f["severity"] in ("critical", "warning", "insight")
        assert f["basis"] == "topology", "no timing data, so nothing may claim otherwise"


def test_finished_goods_on_a_shelf_are_not_work_in_process(actor):
    """Little's law divides the units on the floor by the exit rate. Units
    resting on a storage shelf are finished, not in process; counted, the
    warehouse inflated the lead time of every line that ends in one."""
    import asyncio
    import uuid as _uuid
    from app.core import line_snapshot
    from app.db.connection import SessionLocal

    a = actor(); bootstrap_admin(a)
    st = lambda ref, name, store=False: {
        "ref": ref, "name": name, "description": "",
        "position": {"x": 100, "y": 100, "width": 72, "height": 72}, "color": None,
        "icon": "Box", "isStorage": store, "branchMode": None,
        "integrationProvider": None, "integrationRole": None}
    doc = {"kind": "taktline-map", "version": 1, "name": "Shelf",
           "mapSettings": {"unit": "m", "pixelsPerUnit": 10, "stationSizeUnits": 3},
           "stations": [st("a", "Cut"), st("b", "Pack"), st("s", "Store", True)],
           "processes": [{"ref": "p", "name": "Line", "description": "", "desiredTaktSec": None}],
           "templates": [{"ref": "t", "name": "Widget", "description": "", "process": "p",
                          "startStation": "a", "color": None, "fields": []}],
           "routes": [{"process": "p", "load": "a", "unload": "b", "quantity": 1, "outputTemplate": None},
                      {"process": "p", "load": "b", "unload": "s", "quantity": 1, "outputTemplate": None}]}
    assert a.req("POST", "/map-io/import", doc).status_code == 200
    ids = {s["name"]: s["_id"] for s in a.req("GET", "/stations/").json()}
    tmpl = a.req("GET", "/lot-templates/").json()[0]
    r = a.req("POST", "/cards/", {"lotTemplateId": tmpl["_id"], "processId": tmpl["processId"],
                                  "totalQuantity": 100,
                                  "bins": {ids["Cut"]: {"count": 5}, ids["Store"]: {"count": 95}}})
    assert r.status_code == 201, r.text

    async def snap():
        async with SessionLocal() as session:
            return await line_snapshot.build(session, _uuid.UUID(a.company))
    s = asyncio.run(snap())
    assert s.wip_process == {tmpl["processId"]: 5}


def test_the_snapshot_carries_each_operators_samples_in_recorded_order(actor):
    """The operator chart needs each person's own samples, and the
    individuals chart reads successive lots: both come from the sessions in
    the order they were worked, whatever order the rows were written in."""
    import asyncio
    import uuid as _uuid
    from datetime import timedelta
    from app.core import line_snapshot
    from app.db.connection import SessionLocal
    from app.db.tables import WorkSession
    from app.models.common import utcnow

    a = actor(); bootstrap_admin(a)
    st = lambda ref, name: {
        "ref": ref, "name": name, "description": "",
        "position": {"x": 100, "y": 100, "width": 72, "height": 72}, "color": None,
        "icon": "Box", "isStorage": False, "branchMode": None,
        "integrationProvider": None, "integrationRole": None}
    doc = {"kind": "taktline-map", "version": 1, "name": "Ops",
           "mapSettings": {"unit": "m", "pixelsPerUnit": 10, "stationSizeUnits": 3},
           "stations": [st("a", "Cut"), st("b", "Sew")],
           "processes": [{"ref": "p", "name": "Line", "description": "", "desiredTaktSec": None}],
           "templates": [{"ref": "t", "name": "Widget", "description": "", "process": "p",
                          "startStation": "a", "color": None, "fields": []}],
           "routes": [{"process": "p", "load": "a", "unload": "b", "quantity": 1,
                       "outputTemplate": None}]}
    assert a.req("POST", "/map-io/import", doc).status_code == 200
    sew = next(s_["_id"] for s_ in a.req("GET", "/stations/").json() if s_["name"] == "Sew")
    now = utcnow()
    # Written newest first: (minutes ago, operator, seconds, units)
    rows = [(10, "bo", 90.0, 3), (20, "ann", 40.0, 2), (30, "bo", 60.0, 2), (40, "ann", 30.0, 1)]

    async def go():
        async with SessionLocal() as session:
            for ago, op, dur, qty in rows:
                start = now - timedelta(minutes=ago)
                session.add(WorkSession(
                    companyId=_uuid.UUID(a.company), stationId=_uuid.UUID(sew), operatorId=op,
                    quantity=qty, startedAt=start, endedAt=start + timedelta(seconds=dur),
                    durationSec=dur, closedBy="operator"))
            await session.commit()
        async with SessionLocal() as session:
            return await line_snapshot.build(session, _uuid.UUID(a.company))
    snap = asyncio.run(go())
    m = snap.metrics[sew]
    assert m.operator_samples == {"ann": [30.0, 20.0], "bo": [30.0, 30.0]}
    assert m.samples == [30.0, 30.0, 20.0, 30.0]


def test_a_shipped_example_has_no_fatal_flaw(actor):
    """The examples are what a new user imports to learn from. If the doctor
    calls one broken, either the example or the doctor is wrong."""
    a = actor(); bootstrap_admin(a)
    doc = json.loads((EXAMPLES[0]).read_text())
    assert a.req("POST", "/map-io/import", doc).status_code == 200
    body = a.req("GET", "/analysis/").json()
    fatal = [f for f in body["findings"] if f["severity"] == "critical"]
    assert fatal == [], [f["title"] for f in fatal]


def test_the_report_is_readable_by_an_operator(actor):
    """An operator seeing that their own bench is the constraint is the point
    of the feature, not a leak."""
    from tests.helpers import add_member
    a = actor(); bootstrap_admin(a)
    member = actor(); add_member(a, member, role="user")
    assert member.req("GET", "/analysis/").status_code == 200


# ── The report has to read like prose, not like a data dump ─────────────────

def test_counts_are_spelled_out_but_measurements_are_not():
    """"2 problems" belongs in a spreadsheet. A report is read aloud in a
    production meeting, so small counts are words — while measurements keep
    their numerals, because "forty-one metres" is worse than 41 m to anyone
    standing on a floor."""
    st, rt = floor_chain([10, 10, 10, 10, 460])
    r = analyse(line(st, rt, templates=[("t1", "Shirt", "p1", "a")], ppu=10.0))
    prose = " ".join(r.narrative)
    assert "six work stations" in prose, prose
    assert "one process" in prose, prose
    for bad in ("6 work stations", "1 process", "2 processes"):
        assert bad not in prose, f"{bad!r} should be spelled out: {prose}"

    far = next(f for f in r.findings if f.rule == "long-transport")
    assert any(ch.isdigit() for ch in far.detail), "a distance should stay a numeral"


def test_two_of_something_is_both_not_all_two():
    r = analyse(line(
        [("a", "Cut"), ("b", "Sew"), ("c", "Pack")],
        [("a", "b"), ("b", "c"), ("a", "b", 1, "p2"), ("b", "c", 1, "p2")],
        processes=(("p1", "Crew neck", None), ("p2", "Hooded", None)),
        templates=[("t1", "Shirt", "p1", "a"), ("t2", "Hoodie", "p2", "a")]))
    f = next((f for f in r.findings if f.rule == "single-point-of-failure"), None)
    assert f and "both processes" in f.detail, f.detail if f else "no finding"


def test_a_big_number_keeps_its_numeral():
    """Past twelve, words stop helping."""
    from app.core.analysis import _words
    assert _words(2) == "two" and _words(12) == "twelve"
    assert _words(13) == "13" and _words(1500) == "1,500"


def test_a_finding_only_links_to_the_manual_when_the_manual_explains_it():
    """A "Read more" that lands on a section which does not discuss the finding
    is worse than no link: the reader spends a click discovering that. Every
    structural finding used to point at Core concepts, which describes stations
    and routes and has nothing to say about single points of failure.

    So the link is allowed only for findings whose idea the manual actually
    teaches — the seven wastes, the three timing numbers, and reading the
    statistics."""
    ALLOWED = {"waste", "timing", "statistics"}
    reports = [
        analyse(line([("a", "A")], [])),
        analyse(line(CHAIN + [("lonely", "Old press")], CHAIN_ROUTES, templates=CHAIN_TMPL)),
        analyse(line(
            [("cut", "Cut"), ("panels", "Panels"), ("off", "Off"), ("sew", "Sew")],
            [("cut", "panels", 6), ("cut", "off", 1), ("panels", "sew", 1)],
            templates=[("t1", "Shirt", "p1", "cut")])),
        analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
            cut=dict(**BUSY, cycle_sec=20, line_cycle_sec=22),
            sew=dict(**BUSY, cycle_sec=120, line_cycle_sec=580,
                     samples=[5, 90, 8, 70, 6, 95], operators={"a": 10.0, "b": 90.0}),
            pack=dict(**BUSY, cycle_sec=20, line_cycle_sec=24)))),
    ]
    for r in reports:
        for f in r.findings:
            assert f.manual is None or f.manual in ALLOWED, \
                f"{f.rule} links to '{f.manual}', which does not explain it"



# ── The science upgrades ────────────────────────────────────────────────────
# Rates are normalized to FINISHED-UNIT equivalents. In steady state a line's
# finished-unit throughput equalizes along its length (conservation of flow);
# per-piece throughput does not — a station handling eight pieces per unit
# departs pieces eight times as often. Comparing raw per-piece intervals names
# the end of any split-heavy line the constraint, forever.

def _weighted_merge_line():
    """entry → Prep —×8→ Assembly ←×1— entry2, Assembly → Pack.

    Prep handles eight pieces per finished unit (the ×8 merge feed), so its
    per-piece exit interval is legitimately ~8× shorter than Pack's. A healthy
    day, not a bottleneck.
    """
    stations = [("srcA", "Bar stock"), ("prep", "Prep"), ("srcB", "Housings"),
                ("asm", "Assembly"), ("pack", "Pack")]
    routes = [("srcA", "prep", 1), ("prep", "asm", 8), ("srcB", "asm", 1),
              ("asm", "pack", 1)]
    tmpl = [("t1", "Widget", "p1", "asm")]
    return stations, routes, tmpl


def test_the_constraints_departure_interval_counts_the_pieces_a_unit_needs():
    """Prep handles eight pieces per finished unit, so a piece leaving every
    10 s is a finished unit's worth every 80 s — the number reported."""
    stations, routes, tmpl = _weighted_merge_line()
    r = analyse(line(stations, routes, templates=tmpl, metrics=timed(
        prep=dict(**BUSY, cycle_sec=9, line_cycle_sec=10, oee=0.9),
        asm=dict(**BUSY, cycle_sec=70, line_cycle_sec=80, oee=0.6),
        pack=dict(**BUSY, cycle_sec=70, line_cycle_sec=78, oee=0.6))))
    f = next(f for f in r.findings if f.rule == "bottleneck")
    assert f.stations == ["prep"]
    assert f.metrics["lineCycleSec"] == 80.0 and f.metrics["perUnitPieces"] == 8
    assert "8 pieces at 10s each" in f.detail


def test_the_constraint_counts_changeovers_against_capacity():
    """Pack works less of its open time than Assembly, but spends a third of
    it in changeover: occupied 80% against 60%."""
    stations, routes, tmpl = _weighted_merge_line()
    r = analyse(line(stations, routes, templates=tmpl, metrics=timed(
        prep=dict(**BUSY, cycle_sec=9, line_cycle_sec=10, oee=0.4),
        asm=dict(**BUSY, cycle_sec=70, line_cycle_sec=80, oee=0.6),
        pack=dict(sessions=6, units=30, working_sec=500.0, cycle_sec=70,
                  line_cycle_sec=300, oee=0.5, changeover_sec=300.0))))
    f = next(f for f in r.findings if f.rule == "bottleneck")
    assert "Pack" in f.title and f.metrics["load"] == 0.8


def test_over_takt_counts_the_pieces_a_unit_needs():
    """Eight pieces at 20s each is 160s of work per finished unit. A takt of
    100s is missed even though each piece fits comfortably."""
    stations, routes, tmpl = _weighted_merge_line()
    r = analyse(line(stations, routes, templates=tmpl,
                     processes=(("p1", "Widgets", 100.0),),
                     metrics=timed(prep=dict(**BUSY, cycle_sec=20),
                                   asm=dict(**BUSY, cycle_sec=50),
                                   pack=dict(**BUSY, cycle_sec=40))))
    f = next((f for f in r.findings if f.rule == "over-takt"), None)
    assert f and "Prep" in f.title, [x.title for x in r.findings]
    assert f.metrics["benchesNeeded"] == 2
    assert f.metrics["perUnitWorkSec"] == 160.0


def test_the_constraint_carries_its_evidence():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     wip={"sew": 9, "cut": 1},
                     metrics=timed(
                         cut=dict(**BUSY, cycle_sec=20, line_cycle_sec=30, oee=0.9),
                         sew=dict(**BUSY, cycle_sec=25, line_cycle_sec=300, oee=0.92),
                         pack=dict(**BUSY, cycle_sec=20, line_cycle_sec=32, oee=0.3))))
    f = next(f for f in r.findings if f.rule == "bottleneck")
    # Departure interval, queue in front and the idle successor: reported as
    # numbers, whatever their size.
    assert f.stations == ["sew"]
    assert f.metrics["lineCycleSec"] == 300.0
    assert f.metrics["queuedUnits"] == 9
    assert f.metrics["successorIdle"] == {"pack": 0.7}
    assert "nine units stand at it now" in f.detail
    assert "idle 70% of its open time" in f.detail


VARIED_56 = [20, 90, 30, 85, 25, 86]          # mean 56 s, spread/mean ≈ 0.58
STEADY_56 = [54, 58, 55, 57, 56, 56]          # mean 56 s, spread/mean ≈ 0.02


def test_no_headroom_is_its_own_warning():
    """93% loaded with varied work: by Kingman, even with perfectly regular
    arrivals the queue is (c²/2)·ρ/(1−ρ) ≈ 2.4 times the work."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     processes=(("p1", "Shirts", 60.0),),
                     metrics=timed(cut=dict(**BUSY, cycle_sec=20, samples=VARIED_56),
                                   sew=dict(**BUSY, cycle_sec=56, samples=VARIED_56),
                                   pack=dict(**BUSY, cycle_sec=20))))
    f = next((f for f in r.findings if f.rule == "no-headroom"), None)
    assert f and "Sew" in f.title
    assert f.metrics["utilization"] > 0.9
    assert f.metrics["kingmanFactor"] >= 1
    assert abs(f.metrics["queueSec"] - f.metrics["kingmanFactor"] * 56) < 0.5
    # And a comfortable station does not fire it, varied work or not.
    assert not any(f.rule == "no-headroom" and "Cut" in f.title for f in r.findings)


def test_steady_work_close_to_takt_still_has_headroom():
    """93% loaded but the work hardly varies: the Kingman queue is a small
    fraction of the work, so there is nothing to report."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     processes=(("p1", "Shirts", 60.0),),
                     metrics=timed(cut=dict(**BUSY, cycle_sec=20),
                                   sew=dict(**BUSY, cycle_sec=56, samples=STEADY_56),
                                   pack=dict(**BUSY, cycle_sec=20))))
    assert "no-headroom" not in rules(r)


def test_headroom_needs_six_samples_to_judge():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     processes=(("p1", "Shirts", 60.0),),
                     metrics=timed(cut=dict(**BUSY, cycle_sec=20),
                                   sew=dict(**BUSY, cycle_sec=56, samples=VARIED_56[:5]),
                                   pack=dict(**BUSY, cycle_sec=20))))
    assert "no-headroom" not in rules(r)


def test_very_erratic_work_has_no_headroom_well_below_takt():
    """60% loaded, but with spread/mean ≈ 1.3 the queue already exceeds the
    work: (1.3²/2) × 0.6/0.4 ≈ 1.2."""
    xs = [5, 200, 10, 5, 130, 10]
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     processes=(("p1", "Shirts", 100.0),),
                     metrics=timed(cut=dict(**BUSY, cycle_sec=20),
                                   sew=dict(**BUSY, cycle_sec=60, samples=xs),
                                   pack=dict(**BUSY, cycle_sec=20))))
    f = next((f for f in r.findings if f.rule == "no-headroom"), None)
    assert f and "Sew" in f.title and f.metrics["utilization"] == 0.6


def test_imbalance_reports_balance_efficiency_and_a_concrete_pairing():
    r = analyse(line(
        [("s", "Fabric"), ("a", "Cut"), ("b", "Label"), ("c", "Sew"), ("d", "Pack")],
        [("s", "a"), ("a", "b"), ("b", "c"), ("c", "d")],
        templates=[("t1", "Shirt", "p1", "s")],
        metrics=timed(a=dict(**BUSY, cycle_sec=30), b=dict(**BUSY, cycle_sec=20),
                      c=dict(**BUSY, cycle_sec=90), d=dict(**BUSY, cycle_sec=25))))
    f = next(f for f in r.findings if f.rule == "line-imbalance")
    assert 0 < f.metrics["balanceEfficiency"] < 1
    # Cut (30) + Label (20) = 50s fits under Sew's 90s: a nameable merge of benches.
    assert "Cut" in f.detail and "Label" in f.detail and "one bench" in f.detail


def test_flow_efficiency_is_the_value_stream_headline():
    """Little's law: 20 units at one exit every 60s is 20 minutes of lead
    time; 3 minutes of touch time is a flow efficiency of 15%."""
    snap = line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                metrics=timed(cut=dict(**BUSY, cycle_sec=60),
                              sew=dict(**BUSY, cycle_sec=60),
                              pack=dict(**BUSY, cycle_sec=60, line_cycle_sec=60)))
    snap.wip_process["p1"] = 20
    r = analyse(snap)
    f = next((f for f in r.findings if f.rule == "flow-efficiency"), None)
    assert f is not None
    assert f.metrics["leadSec"] == 1200
    assert f.metrics["touchSec"] == 180
    assert abs(f.metrics["flowEfficiency"] - 0.15) < 0.01
    assert "Little's law" in f.detail


def test_a_shared_station_reports_its_own_streams_departures():
    """Paint serves two streams, so over all departures it leaves twice as
    often as either stream sees. The interval reported for the bracket line is
    the bracket line's own."""
    stations = [("stock", "Stock"), ("saw", "Saw"), ("drill", "Drill"), ("paint", "Paint"),
                ("pack", "Pack")]
    routes = [("stock", "saw"), ("saw", "drill"), ("drill", "paint"), ("paint", "pack")]
    m = lambda lc, oee=0.5: dict(sessions=20, units=200, working_sec=6000.0, cycle_sec=30.0,
                                 line_cycle_sec=lc, oee=oee)
    snap = line(stations, routes, templates=[("t1", "Bracket", "p1", "stock")],
                metrics=timed(saw=m(60.0), drill=m(120.0), paint=m(60.0, 0.8), pack=m(60.0)))
    snap.line_cycle_by_process = {("saw", "p1"): 120.0, ("paint", "p1"): 120.0,
                                  ("pack", "p1"): 120.0, ("drill", "p1"): 120.0}
    f = next(f for f in analyse(snap).findings if f.rule == "bottleneck")
    assert f.stations == ["paint"] and f.metrics["lineCycleSec"] == 120.0


def test_a_line_paced_by_its_orders_still_names_the_station_with_least_slack():
    """Every station leaves at the release pace, so no exit interval stands
    out; the constraint is the station working or broken down for the
    largest share of open time."""
    stations = [("in", "Stock"), ("w1", "Weld 1"), ("w2", "Weld 2"), ("a1", "Assembly")]
    routes = [("in", "w1"), ("w1", "w2"), ("w2", "a1")]
    m = lambda oee, down=0.0: dict(sessions=50, units=1000, working_sec=36000.0 * oee / 0.5,
                                   cycle_sec=40.0, line_cycle_sec=69.0, oee=oee,
                                   downtime_sec=down)
    snap = line(stations, routes, templates=[("t1", "Bracket", "p1", "in")],
                metrics=timed(**{"in": m(0.1), "w1": m(0.55), "w2": m(0.66, down=0.2 * 72000),
                                 "a1": m(0.85)}))
    named = [f for f in analyse(snap).findings if f.rule == "bottleneck"]
    assert len(named) == 1 and named[0].stations == ["w2"] and named[0].basis == "load"


def test_a_station_upstream_of_a_split_is_normalised_by_its_true_share():
    """One bar is cut into four tubes of each kind. A bar leaving every 120 s
    feeds tubes every 30 s: the line is in step. Rounded up to one piece per
    finished unit, the bar would read four times slower than the tubes; its
    departure interval per finished unit is a quarter of 120 s."""
    stations = [("src", "Saw stock"), ("bar", "Bar"), ("cut", "Cut"),
                ("ta", "Tube A"), ("tb", "Tube B")]
    routes = [("src", "bar"), ("bar", "cut"), ("cut", "ta", 4), ("cut", "tb", 4)]
    snap = line(stations, routes, templates=[("t1", "Bar", "p1", "src")],
                metrics=timed(src=dict(**BUSY, cycle_sec=60, line_cycle_sec=120),
                              bar=dict(**BUSY, cycle_sec=60, line_cycle_sec=120),
                              cut=dict(**BUSY, cycle_sec=10, line_cycle_sec=15),
                              ta=dict(**BUSY, cycle_sec=20, line_cycle_sec=30),
                              tb=dict(**BUSY, cycle_sec=20, line_cycle_sec=30)))
    for sid, kw in snap.metrics.items():
        kw.oee = 0.9 if sid == "bar" else 0.5
    named = [f for f in analyse(snap).findings if f.rule == "bottleneck"]
    assert [f.stations for f in named] == [["bar"]]
    assert named[0].metrics["lineCycleSec"] == 30.0     # 120 s × a quarter bar per tube


def test_a_line_that_ends_on_a_shelf_still_reports_its_lead_time():
    """Nothing departs a warehouse, so the exit rate is read where goods
    leave for it. Measured at the shelf itself, every line ending in storage
    reported no lead time."""
    stations = CHAIN + [("store", "Store", {"is_storage": True})]
    snap = line(stations, CHAIN_ROUTES + [("pack", "store")], templates=CHAIN_TMPL,
                metrics=timed(cut=dict(**BUSY, cycle_sec=60),
                              sew=dict(**BUSY, cycle_sec=60),
                              pack=dict(**BUSY, cycle_sec=60, line_cycle_sec=60)))
    snap.wip_process["p1"] = 20
    f = next((f for f in analyse(snap).findings if f.rule == "flow-efficiency"), None)
    assert f is not None
    assert f.metrics["leadSec"] == 1200


def test_a_merge_paced_by_its_slowest_feed_is_named():
    stations = [("x", "Frames"), ("y", "Glass"), ("m", "Glazing"), ("e", "Pack")]
    routes = [("x", "m", 1), ("y", "m", 1), ("m", "e", 1)]
    r = analyse(line(stations, routes, templates=[("t1", "Window", "p1", "m")],
                     metrics=timed(x=dict(**BUSY, cycle_sec=30, line_cycle_sec=40),
                                   y=dict(**BUSY, cycle_sec=30, line_cycle_sec=200),
                                   m=dict(**BUSY, cycle_sec=30, line_cycle_sec=210))))
    f = next((f for f in r.findings if f.rule == "unmatched-feeds"), None)
    assert f and "Glass" in f.title
    assert "matched sets" in f.detail


def test_a_machine_every_value_stream_visits_is_a_monument():
    """Paint is the busiest station of both streams, and so the constraint of
    both — though at 60% it is barely busier than the floor around it."""
    stations = [("a", "Cut A"), ("b", "Cut B"), ("paint", "Paint"), ("out", "Pack")]
    routes = [("a", "paint", 1, "p1"), ("paint", "out", 1, "p1"),
              ("b", "paint", 1, "p2"), ("paint", "out", 1, "p2")]
    r = analyse(line(stations, routes,
                     processes=(("p1", "Crew neck", None), ("p2", "Hooded", None)),
                     templates=[("t1", "Shirt", "p1", "a"), ("t2", "Hoodie", "p2", "b")],
                     metrics=timed(a=dict(**BUSY, cycle_sec=30, oee=0.4),
                                   b=dict(**BUSY, cycle_sec=30, oee=0.45),
                                   paint=dict(**BUSY, cycle_sec=30, oee=0.6),
                                   out=dict(**BUSY, cycle_sec=30, oee=0.55))))
    f = next((f for f in r.findings if f.rule == "shared-monument"), None)
    assert f and "Paint" in f.title
    assert "Crew neck" in f.detail and "Hooded" in f.detail
    assert f.metrics["constraintOf"] == 2


def test_a_shared_station_that_paces_one_stream_is_not_a_monument():
    """Paint is the busiest station on the floor and serves both streams, but
    the refinish stream starts at it, so there it is the entry and the
    stream's constraint is Polish: Paint paces one stream only."""
    stations = [("a", "Cut"), ("paint", "Paint"), ("out", "Pack"), ("y", "Sand"),
                ("z", "Polish")]
    routes = [("a", "paint", 1, "p1"), ("paint", "out", 1, "p1"),
              ("paint", "y", 1, "p2"), ("y", "z", 1, "p2")]
    r = analyse(line(stations, routes,
                     processes=(("p1", "Crew neck", None), ("p2", "Refinish", None)),
                     templates=[("t1", "Shirt", "p1", "a"), ("t2", "Refinish", "p2", "paint")],
                     metrics=timed(a=dict(**BUSY, cycle_sec=30, oee=0.4),
                                   paint=dict(**BUSY, cycle_sec=30, oee=0.9),
                                   out=dict(**BUSY, cycle_sec=30, oee=0.3),
                                   y=dict(**BUSY, cycle_sec=30, oee=0.45),
                                   z=dict(**BUSY, cycle_sec=30, oee=0.5))))
    assert "shared-monument" not in rules(r)
    named = {f.process: f.stations for f in r.findings if f.rule == "bottleneck"}
    assert named == {"p1": ["paint"], "p2": ["z"]}


def test_uneven_work_tells_special_cause_from_common_cause():
    """Shewhart's distinction, because the remedies are opposite: chase the
    events, or write the standard."""
    spiky = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        sew=dict(**BUSY, cycle_sec=30,
                 samples=[10, 11, 10, 9, 10, 11, 300, 10, 9, 10, 11, 10]))))
    f = next(f for f in spiky.findings if f.rule == "uneven-work")
    assert f.metrics["shape"] == "spikes" and f.metrics["aboveLimit"] == 1
    assert "assignable cause" in f.detail

    spread = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        sew=dict(**BUSY, cycle_sec=30, samples=[5, 80, 10, 90, 8, 70, 6, 95]))))
    f = next(f for f in spread.findings if f.rule == "uneven-work")
    assert f.metrics["shape"] == "spread" and f.metrics["cv"] >= 0.75
    assert "standard" in f.detail


def test_a_spread_below_moderate_variability_with_no_point_outside_is_quiet():
    """Spread/mean 0.70 is low variability in Hopp & Spearman's classes, and
    no lot lies above the control limit."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        sew=dict(**BUSY, cycle_sec=30, samples=[5, 60, 15, 75, 10, 65, 20, 70]))))
    assert "uneven-work" not in rules(r)


def test_one_spike_among_steady_lots_is_an_assignable_cause_whatever_the_spread():
    """Lots at 30-33 s and one at 75 s: the spread is small, but the 75 s lot
    is far above the limit the steady lots set."""
    xs = [30, 31, 30, 32, 31, 30, 75, 31, 30, 33, 31, 30]
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        sew=dict(**BUSY, cycle_sec=30, samples=xs))))
    f = next((f for f in r.findings if f.rule == "uneven-work"), None)
    assert f and f.metrics["shape"] == "spikes" and f.metrics["cv"] < 0.6


def test_unevenness_is_judged_per_product():
    """Five lots of each product are too few to chart either; pooled, the
    two products would read as one erratic job."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        sew=dict(**BUSY, cycle_sec=30, samples=[5, 90, 6, 95, 5, 90, 6, 95, 5, 90],
                 samples_by={"t1": [5, 6, 5, 6, 5], "t2": [90, 95, 90, 95, 90]}))))
    assert "uneven-work" not in rules(r)


def test_imbalance_weighs_stations_by_pieces_per_unit():
    """A station doing eight pieces per finished unit is occupied eight times
    its piece time — balance is judged in occupied time, like everything else."""
    stations, routes, tmpl = _weighted_merge_line()
    r = analyse(line(stations, routes, templates=tmpl, metrics=timed(
        prep=dict(**BUSY, cycle_sec=20),   # ×8 → 160s of work per unit
        asm=dict(**BUSY, cycle_sec=50),
        pack=dict(**BUSY, cycle_sec=40))))
    f = next((f for f in r.findings if f.rule == "line-imbalance"), None)
    assert f and "Prep" in f.detail.split("carries")[0], f.detail if f else "no finding"
    assert f.metrics["slowestSec"] == 160.0


def test_a_line_with_more_stations_than_its_work_needs():
    """Takt 300 s; three stations of 60 s each are 180 s of work, which fits in
    ⌈180 ÷ 300⌉ = 1 station."""
    r = analyse(line(FED_CHAIN, FED_ROUTES, templates=FED_TMPL,
                     processes=(("p1", "Shirts", 300.0),),
                     metrics=timed(cut=dict(**BUSY, cycle_sec=60),
                                   sew=dict(**BUSY, cycle_sec=60),
                                   pack=dict(**BUSY, cycle_sec=60))))
    f = next((f for f in r.findings if f.rule == "demand-limited"), None)
    assert f and f.metrics["minStations"] == 1 and f.metrics["stations"] == 3
    assert f.metrics["taktBasis"] == "desired" and f.metrics["taktSec"] == 300.0
    assert sorted(f.stations) == ["cut", "pack", "sew"]


def test_a_line_whose_work_needs_every_station_is_not_over_capacity():
    """Takt 60 s; 150 s of work needs ⌈150 ÷ 60⌉ = 3 stations, and three are
    staffed."""
    r = analyse(line(FED_CHAIN, FED_ROUTES, templates=FED_TMPL,
                     processes=(("p1", "Shirts", 60.0),),
                     metrics=timed(cut=dict(**BUSY, cycle_sec=50),
                                   sew=dict(**BUSY, cycle_sec=50),
                                   pack=dict(**BUSY, cycle_sec=50))))
    assert "demand-limited" not in rules(r)


def test_without_a_takt_the_measured_interval_between_finished_units_is_the_beat():
    """No takt set; one finished unit leaves Pack every 600 s. 300 s of work
    fits in one station of the three."""
    snap = line(FED_CHAIN, FED_ROUTES, templates=FED_TMPL,
                metrics=timed(cut=dict(**BUSY, cycle_sec=100),
                              sew=dict(**BUSY, cycle_sec=100),
                              pack=dict(**BUSY, cycle_sec=100)))
    snap.exit_rate_by_process = {("pack", "p1"): 1 / 600}
    f = next((f for f in analyse(snap).findings if f.rule == "demand-limited"), None)
    assert f and f.metrics["taktBasis"] == "measured" and f.metrics["taktSec"] == 600.0
    assert f.metrics["minStations"] == 1
    # And with finished units leaving every 120 s, all three are needed.
    snap.exit_rate_by_process = {("pack", "p1"): 1 / 120}
    assert "demand-limited" not in rules(analyse(snap))


def test_over_capacity_counts_only_the_stations_a_stream_has_to_itself():
    """Paint is shared with another stream, so this one cannot combine it
    away: Sew, Press and Pack carry 180 s against a 300 s takt and fit in one
    station. Counted in, Paint's 900 s would make it four of four."""
    stations = [("a", "Cut"), ("b", "Sew"), ("c", "Press"), ("paint", "Paint"),
                ("out", "Pack"), ("x", "Other"), ("y", "Other out")]
    routes = [("a", "b", 1, "p1"), ("b", "c", 1, "p1"), ("c", "paint", 1, "p1"),
              ("paint", "out", 1, "p1"), ("x", "paint", 1, "p2"), ("paint", "y", 1, "p2")]
    r = analyse(line(stations, routes,
                     processes=(("p1", "Shirts", 300.0), ("p2", "Other", None)),
                     templates=[("t1", "Shirt", "p1", "a"), ("t2", "Thing", "p2", "x")],
                     metrics=timed(b=dict(**BUSY, cycle_sec=60), c=dict(**BUSY, cycle_sec=60),
                                   paint=dict(**BUSY, cycle_sec=900),
                                   out=dict(**BUSY, cycle_sec=60))))
    f = next((f for f in r.findings if f.rule == "demand-limited" and f.process == "p1"), None)
    assert f and sorted(f.stations) == ["b", "c", "out"]
    assert f.metrics["workSec"] == 180.0 and f.metrics["minStations"] == 1


def test_an_entry_station_is_not_balanced_against_the_line():
    """A press stamping into a supermarket at one second a piece is not work
    anyone could move to an assembler: an entry station runs at the release
    pace, and the constraint rule leaves it out for the same reason. Among
    the stations that remain the line is balanced, so nothing fires."""
    r = analyse(line(
        [("press", "Press"), ("w1", "Weld 1"), ("w2", "Weld 2"), ("a1", "Assembly")],
        [("press", "w1"), ("w1", "w2"), ("w2", "a1")],
        templates=[("t1", "Bracket", "p1", "press")],
        metrics=timed(press=dict(**BUSY, cycle_sec=1), w1=dict(**BUSY, cycle_sec=39),
                      w2=dict(**BUSY, cycle_sec=46), a1=dict(**BUSY, cycle_sec=62))))
    assert "line-imbalance" not in rules(r)


def test_wip_concentration_reads_the_average_not_the_moment():
    """A live count is a snapshot: forty units at Sew right now, on a line
    whose average at Sew is three, is a moment, not a standing pile."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     wip={"cut": 2, "sew": 40, "pack": 1},
                     metrics=timed(cut=dict(**BUSY, cycle_sec=30, line_cycle_sec=10, wip_avg=5.0),
                                   sew=dict(**BUSY, cycle_sec=30, line_cycle_sec=10, wip_avg=4.0),
                                   pack=dict(**BUSY, cycle_sec=30, line_cycle_sec=10,
                                             wip_avg=5.0))))
    assert "wip-concentration" not in rules(r)
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     wip={"cut": 2, "sew": 3, "pack": 1},
                     metrics=timed(cut=dict(**BUSY, cycle_sec=30, line_cycle_sec=10, wip_avg=2.0),
                                   sew=dict(**BUSY, cycle_sec=30, line_cycle_sec=10, wip_avg=30.0),
                                   pack=dict(**BUSY, cycle_sec=30, line_cycle_sec=10,
                                             wip_avg=1.0))))
    f = next((f for f in r.findings if f.rule == "wip-concentration"), None)
    assert f and "Sew" in f.title and f.metrics["basis"] == "average"


def test_no_rule_diagnoses_why_a_station_waits():
    """Units standing at a station may be the lot in hand, and a station idle
    because it is fast looks just like one starved by its feed; the record
    cannot tell these apart, so the report does not pretend to."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, wip={"sew": 6},
                     metrics=timed(cut=dict(**BUSY, cycle_sec=30, oee=0.8),
                                   sew=dict(**BUSY, cycle_sec=60, line_cycle_sec=200, oee=0.2),
                                   pack=dict(**BUSY, cycle_sec=30, oee=0.8))))
    assert not {"waiting-gap", "starved-station"} & rules(r)


def test_a_station_making_two_products_is_not_uneven():
    """Two products with different work contents at one station look erratic
    when pooled; judged per product they are steady."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        sew=dict(**BUSY, cycle_sec=30, samples=[10, 11, 10, 60, 62, 61, 10, 59, 11, 60, 10, 61],
                 samples_by={"t1": [10, 11, 10, 10, 11, 10], "t2": [60, 62, 61, 59, 60, 61]}))))
    assert "uneven-work" not in rules(r)


def test_a_broad_spread_is_chance_variation_even_with_outliers():
    """A wide, skewed spread throws up lots three times the median too; with
    no steady majority they are not assignable causes."""
    xs = [20, 35, 50, 80, 25, 120, 40, 200, 30, 60, 45, 150]
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        sew=dict(**BUSY, cycle_sec=60, samples=xs))))
    f = next(f for f in r.findings if f.rule == "uneven-work")
    assert f.metrics["shape"] == "spread"


def test_a_long_departure_interval_alone_does_not_make_a_constraint():
    """Where work arrives in bursts a lightly loaded station can show long
    gaps between departures; the constraint is the station with the highest
    utilisation."""
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=20, line_cycle_sec=30, oee=0.85),
        sew=dict(**BUSY, cycle_sec=25, line_cycle_sec=60, oee=0.2),
        pack=dict(**BUSY, cycle_sec=20, line_cycle_sec=32, oee=0.5))))
    named = [f for f in r.findings if f.rule == "bottleneck"]
    assert not any("Sew" in f.title for f in named)
