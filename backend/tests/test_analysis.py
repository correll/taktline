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
    assert not {"bottleneck", "waiting-gap", "line-imbalance"} & rules(r)


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


def test_one_very_long_move_is_noticed():
    r = analyse(line(
        [("a", "Cut", {"x": 0, "y": 0}), ("b", "Sew", {"x": 100, "y": 0}),
         ("c", "Press", {"x": 200, "y": 0}), ("d", "Pack", {"x": 5000, "y": 0})],
        [("a", "b"), ("b", "c"), ("c", "d")],
        templates=[("t1", "Shirt", "p1", "a")], ppu=10.0))
    f = next((f for f in r.findings if f.rule == "long-transport"), None)
    assert f and f.waste == "Transport"


# ── Timing ──────────────────────────────────────────────────────────────────

def timed(**per_station):
    return {sid: StationMetrics(**kw) for sid, kw in per_station.items()}


BUSY = dict(sessions=6, units=30, working_sec=600.0)


def test_the_constraint_is_named():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=20, line_cycle_sec=30, oee=0.6),
        sew=dict(**BUSY, cycle_sec=25, line_cycle_sec=300, oee=0.6),
        pack=dict(**BUSY, cycle_sec=20, line_cycle_sec=32, oee=0.6))))
    f = next((f for f in r.findings if f.rule == "bottleneck"), None)
    assert f and "Sew" in f.title


def test_the_gap_between_working_and_leaving_is_the_waste():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=20, line_cycle_sec=22),
        sew=dict(**BUSY, cycle_sec=120, line_cycle_sec=580),
        pack=dict(**BUSY, cycle_sec=20, line_cycle_sec=24))))
    f = next((f for f in r.findings if f.rule == "waiting-gap"), None)
    assert f and f.waste == "Waiting"
    assert f.metrics["gapSec"] > 400


def test_a_station_that_cannot_hold_the_takt():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     processes=(("p1", "Shirts", 60.0),),
                     metrics=timed(
                         cut=dict(**BUSY, cycle_sec=30),
                         sew=dict(**BUSY, cycle_sec=200),
                         pack=dict(**BUSY, cycle_sec=25))))
    f = next((f for f in r.findings if f.rule == "over-takt"), None)
    assert f and f.severity == CRITICAL and "Sew" in f.title


def test_an_unbalanced_line():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=10),
        sew=dict(**BUSY, cycle_sec=90),
        pack=dict(**BUSY, cycle_sec=12))))
    f = next((f for f in r.findings if f.rule == "line-imbalance"), None)
    assert f and f.metrics["ratio"] >= 2


def test_work_that_is_not_repeatable():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=30, samples=[5, 90, 8, 70, 6, 95, 10]),
        sew=dict(**BUSY, cycle_sec=30),
        pack=dict(**BUSY, cycle_sec=30))))
    f = next((f for f in r.findings if f.rule == "uneven-work"), None)
    assert f and f.metrics["cv"] >= 0.6


def test_two_operators_doing_the_same_job_very_differently():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL, metrics=timed(
        cut=dict(**BUSY, cycle_sec=30, operators={"ann": 20.0, "bo": 95.0}),
        sew=dict(**BUSY, cycle_sec=30),
        pack=dict(**BUSY, cycle_sec=30))))
    f = next((f for f in r.findings if f.rule == "operator-spread"), None)
    assert f and "standard work" in f.detail


def test_work_piling_up_in_one_place():
    r = analyse(line(CHAIN, CHAIN_ROUTES, templates=CHAIN_TMPL,
                     wip={"cut": 2, "sew": 40, "pack": 1},
                     metrics=timed(cut=dict(**BUSY, cycle_sec=30),
                                   sew=dict(**BUSY, cycle_sec=30),
                                   pack=dict(**BUSY, cycle_sec=30))))
    f = next((f for f in r.findings if f.rule == "wip-concentration"), None)
    assert f and f.waste == "Inventory"
    assert "Little's law" in f.detail


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
