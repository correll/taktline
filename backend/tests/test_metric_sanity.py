"""The numbers people make decisions from.

A plant manager reads this page and moves a person, buys a machine, or leaves a
bottleneck alone. So a wrong number is not a display bug — it is a wrong
decision about a real factory, taken confidently.

Two properties, and the second is the one that gets forgotten.

**Bounds.** OEE is a fraction of open time, so it lives in [0, 1]. Durations do
not run backwards. A cycle time of zero seconds is not a fast station, it is
arithmetic that got away.

**Null is not zero.** `oee: 0` reads as *this station is idle, go and look at
it*. `oee: null` reads as *nobody has run a timer here*. They send someone to
different places. Any metric that cannot be computed must be absent, never
defaulted to a number that means something specific and false.
"""

import random

import pytest

from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _st(a: Actor, name: str, **kw) -> str:
    return a.req("POST", "/stations/", {**STATION, "name": name, **kw}).json()["_id"]


def _line(a: Actor, n_stations=4):
    ids = [_st(a, f"S{i}") for i in range(n_stations)]
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    for x, y in zip(ids, ids[1:]):
        a.req("POST", "/routes/", {"processId": proc, "load": x, "unload": y, "quantity": 1})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Widget", "processId": proc,
                                             "startStationId": ids[0]}).json()["_id"]
    return ids, proc, tmpl


def _rows(a: Actor, query: str = ""):
    stats = a.req("GET", f"/sessions/stats{query}").json()
    return stats if isinstance(stats, list) else stats.get("stations", stats)


def _check(row, where=""):
    """Every bound a reported metric has to satisfy, in one place."""
    oee = row.get("oee")
    assert oee is None or 0.0 <= oee <= 1.0, f"OEE {oee} out of range {where}"

    for key in ("totalWorkingSec", "totalUnits", "sessionCount"):
        v = row.get(key)
        assert v is None or v >= 0, f"{key} is negative ({v}) {where}"

    for key in ("cycleTimeSec", "lineCycleTimeSec"):
        v = row.get(key)
        assert v is None or v > 0, \
            f"{key} is {v} {where} — zero is not a fast station, it is bad arithmetic"

    # Null is not zero: a cycle time only exists if units were worked.
    if row.get("cycleTimeSec") is not None:
        assert (row.get("totalUnits") or 0) > 0, \
            f"a cycle time was reported for zero units {where}"


# ── The happy path still has to hold ────────────────────────────────────────

def test_a_worked_station_reports_sane_numbers(actor):
    a = actor(); bootstrap_admin(a)
    ids, proc, tmpl = _line(a)
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "W-1", "totalQuantity": 10,
                                     "bins": {ids[0]: {"count": 10}}}).json()
    s = a.req("POST", "/sessions/", {"stationId": ids[0], "cardId": card["_id"],
                                     "operatorId": "t1", "quantity": 5})
    a.req("POST", f"/sessions/{s.json()['_id']}/end", {"quantity": 5})

    rows = _rows(a)
    assert rows, "no stations reported at all"
    for r in rows:
        _check(r, f"at {r.get('stationId')}")


def test_a_station_nobody_has_worked_reports_nothing_not_zero(actor):
    """The distinction that sends someone to the wrong end of the building."""
    a = actor(); bootstrap_admin(a)
    ids, proc, tmpl = _line(a)

    for r in _rows(a):
        assert r.get("oee") is None, \
            f"an unworked station reported OEE {r['oee']} — that reads as 'idle machine'"
        assert r.get("cycleTimeSec") is None
        assert (r.get("sessionCount") or 0) == 0


def test_a_session_of_zero_units_never_divides_by_them(actor):
    """Cycle time is working time ÷ units. A lot worked to zero units is a
    scrapped lot, not an infinitely fast one."""
    a = actor(); bootstrap_admin(a)
    ids, proc, tmpl = _line(a)
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "W-0", "totalQuantity": 4,
                                     "bins": {ids[0]: {"count": 4}}}).json()
    s = a.req("POST", "/sessions/", {"stationId": ids[0], "cardId": card["_id"],
                                     "operatorId": "t1", "quantity": 1})
    a.req("POST", f"/sessions/{s.json()['_id']}/end", {"quantity": 0})

    for r in _rows(a):
        _check(r, "after a zero-unit session")


# ── The clock belongs to the server ─────────────────────────────────────────

def test_a_tablet_cannot_supply_its_own_clock(actor):
    """Sessions are timed server-side: `SessionCreate` and `SessionEnd` carry no
    timestamps at all, so a tablet with a wrong clock — consumer hardware, on a
    factory network, quite often wrong — cannot post a session that ended
    before it began. That is a design property worth pinning: the day someone
    adds `startedAt` to the body for a convenient backfill, a negative duration
    becomes possible and it poisons every average it lands in."""
    a = actor(); bootstrap_admin(a)
    ids, proc, tmpl = _line(a)
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "W-2", "totalQuantity": 2,
                                     "bins": {ids[0]: {"count": 2}}}).json()

    r = a.req("POST", "/sessions/", {
        "stationId": ids[0], "cardId": card["_id"], "operatorId": "t1", "quantity": 1,
        "startedAt": "2999-01-01T00:00:00Z", "endedAt": "1999-01-01T00:00:00Z",
        "durationSec": -600})
    assert r.status_code < 400, r.text
    sid = r.json()["_id"]
    a.req("POST", f"/sessions/{sid}/end", {"quantity": 1, "durationSec": -600})

    sessions = a.req("GET", "/sessions/").json()
    for s in sessions:
        d = s.get("durationSec")
        assert d is None or d >= 0, f"a client supplied a negative duration: {d}"
        if s.get("startedAt") and s.get("endedAt"):
            assert s["endedAt"] >= s["startedAt"], "a session ended before it began"
    for row in _rows(a):
        _check(row, "after a hostile clock")


# ── Whatever the floor looks like ───────────────────────────────────────────

@pytest.mark.parametrize("seed", [11, 4242])
def test_no_arrangement_of_work_produces_an_impossible_number(actor, seed):
    """The bounds have to hold for shapes nobody wrote a fixture for: sessions
    left open, lots scrapped mid-session, work recorded at a warehouse, more
    units claimed than the lot holds."""
    a = actor(); bootstrap_admin(a)
    ids, proc, tmpl = _line(a, n_stations=5)
    a.req("PUT", f"/stations/{ids[-1]}", {**STATION, "name": "Store", "isStorage": True})
    rng = random.Random(seed)

    cards = []
    for i in range(6):
        c = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                      "lotNum": f"R-{i}", "totalQuantity": rng.randint(1, 9),
                                      "bins": {ids[0]: {"count": rng.randint(1, 9)}}})
        if c.status_code < 300:
            cards.append(c.json())

    for _ in range(40):
        if not cards:
            break
        c = rng.choice(cards)
        station = rng.choice(ids)
        op = rng.random()
        if op < 0.45:
            s = a.req("POST", "/sessions/", {"stationId": station, "cardId": c["_id"],
                                             "operatorId": f"t{rng.randint(1, 3)}",
                                             "quantity": rng.choice([0, 1, 5, 999])})
            if s.status_code < 300 and rng.random() < 0.75:      # sometimes left open
                a.req("POST", f"/sessions/{s.json()['_id']}/end",
                      {"quantity": rng.choice([0, 1, 5, 999])})
        elif op < 0.8:
            frm = rng.choice(list(c["bins"])) if c["bins"] else station
            a.req("POST", f"/cards/{c['_id']}/advance",
                  {"fromStationId": frm, "toStationId": station,
                   "quantity": rng.randint(1, 4)})
            c["bins"] = next((x["bins"] for x in a.req("GET", "/cards/").json()
                              if x["_id"] == c["_id"]), {})
        else:
            a.req("DELETE", f"/cards/{c['_id']}")
            cards = [x for x in cards if x["_id"] != c["_id"]]

    for window in ("", "?window=1h", "?window=1d", "?window=1w", "?window=1m"):
        for row in _rows(a, window):
            _check(row, f"seed={seed} window={window or 'all'}")

    for sid in ids:
        detail = a.req("GET", f"/sessions/stats/{sid}")
        assert detail.status_code == 200, detail.text
        _check(detail.json(), f"seed={seed} station detail")
