"""The runout rule: run the line that starves first.

Pure tests over hand-built snapshots, like the line doctor's own — the
arithmetic is one division, so what is worth pinning is the *edges*, each of
which is a way to give confident wrong advice: storage never starves, null is
not zero, a fan takes its tightest branch, and a boundary partner is not a
line.
"""

from app.core import analysis, runout
from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _snap(*, stations, routes, wip_sp=None, rates=None, processes=None):
    return analysis.Snapshot(
        stations=[analysis.StationIn(id=i, name=n, is_storage=st, provider=pr)
                  for (i, n, st, pr) in stations],
        routes=[analysis.RouteIn(load=a, unload=b, quantity=1, process=p)
                for (a, b, p) in routes],
        processes=[analysis.ProcessIn(id=p, name=f"Line {p.upper()}")
                   for p in (processes or [])],
        templates=[],
        wip={},
        metrics={sid: analysis.StationMetrics(sessions=5, line_cycle_sec=sec)
                 for sid, sec in (rates or {}).items()},
        wip_station_process=wip_sp or {},
    )


def test_the_line_that_starves_first_has_the_smallest_clock():
    """Two lines through one shared machine. Line A's next station holds 2
    units and eats one every 60 s; line B holds 100 at the same rate. A's
    clock is 120 s, B's 6000 — A first, which is the whole rule."""
    s = _snap(
        stations=[("shared", "Saw", False, None), ("na", "Weld A", False, None),
                  ("nb", "Weld B", False, None)],
        routes=[("shared", "na", "a"), ("shared", "nb", "b")],
        processes=["a", "b"],
        wip_sp={"na": {"a": 2}, "nb": {"b": 100}},
        rates={"na": 60.0, "nb": 60.0},
    )
    lines = runout.station_runout(s, "shared")
    assert lines["a"].runout_sec == 120.0
    assert lines["b"].runout_sec == 6000.0
    assert lines["a"].next_station_name == "Weld A"


def test_an_empty_buffer_is_starving_now_not_unknown():
    s = _snap(stations=[("shared", "Saw", False, None), ("n", "Weld", False, None)],
              routes=[("shared", "n", "a")], processes=["a"],
              wip_sp={}, rates={"n": 60.0})
    assert runout.station_runout(s, "shared")["a"].runout_sec == 0.0


def test_no_measured_rate_means_no_clock():
    """Null is not zero: an unmeasured next station must not read as
    'starving now' — it reads as 'no clock', and the picker sorts it FIFO."""
    s = _snap(stations=[("shared", "Saw", False, None), ("n", "Weld", False, None)],
              routes=[("shared", "n", "a")], processes=["a"],
              wip_sp={"n": {"a": 7}}, rates={})
    line = runout.station_runout(s, "shared")["a"]
    assert line.runout_sec is None
    assert line.buffer_units == 7          # the buffer is still reported


def test_a_storage_branch_never_starves():
    """A warehouse is meant to fill. A line whose only onward branch is a
    shelf gets no clock at all — ranking it urgent because the shelf is empty
    would invert the accumulation warning's logic."""
    s = _snap(stations=[("shared", "Saw", False, None),
                        ("shelf", "FG store", True, None),
                        ("n", "Weld", False, None)],
              routes=[("shared", "shelf", "a"), ("shared", "n", "b")],
              processes=["a", "b"],
              wip_sp={"shelf": {"a": 0}, "n": {"b": 3}},
              rates={"n": 60.0})
    lines = runout.station_runout(s, "shared")
    assert "a" not in lines
    assert lines["b"].runout_sec == 180.0


def test_a_fan_takes_the_branch_that_starves_first():
    s = _snap(stations=[("shared", "Saw", False, None), ("n1", "Weld", False, None),
                        ("n2", "Grind", False, None)],
              routes=[("shared", "n1", "a"), ("shared", "n2", "a")],
              processes=["a"],
              wip_sp={"n1": {"a": 50}, "n2": {"a": 2}},
              rates={"n1": 60.0, "n2": 60.0})
    line = runout.station_runout(s, "shared")["a"]
    assert line.next_station_id == "n2" and line.runout_sec == 120.0


def test_a_boundary_partner_is_not_a_line():
    """An ERP node cannot starve; a handoff link is not a branch."""
    s = _snap(stations=[("shared", "Ship bench", False, None),
                        ("erp", "Odoo", False, "odoo")],
              routes=[("shared", "erp", "a")], processes=["a"],
              wip_sp={}, rates={})
    assert runout.station_runout(s, "shared") == {}


def test_the_buffer_counts_only_the_lines_own_units():
    """Two processes share the downstream bench too. Line A's clock divides
    line A's units — counting the other line's WIP as your buffer reports a
    full shelf while your own material is gone."""
    s = _snap(stations=[("shared", "Saw", False, None), ("n", "Weld", False, None)],
              routes=[("shared", "n", "a"), ("shared", "n", "b")],
              processes=["a", "b"],
              wip_sp={"n": {"a": 1, "b": 99}},
              rates={"n": 60.0})
    lines = runout.station_runout(s, "shared")
    assert lines["a"].runout_sec == 60.0
    assert lines["b"].runout_sec == 5940.0


# ─── Over HTTP ───────────────────────────────────────────────────────────────

def test_the_endpoint_answers_for_any_member(actor):
    a = actor()
    bootstrap_admin(a, "Runout co")
    st = a.req("POST", "/stations/", {**STATION, "name": "Saw"}).json()["_id"]
    body = a.req("GET", f"/analysis/runout/{st}").json()
    assert body["stationId"] == st
    assert body["lines"] == {}             # no routes yet — nothing to starve

    assert a.req("GET", "/analysis/runout/00000000-0000-0000-0000-000000000000"
                 ).status_code == 404
