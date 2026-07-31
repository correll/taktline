"""What happens to a running floor when somebody deletes something.

Two hazards, and the product has one of each.

**Orphaned material.** `card.bins` is a JSONB map keyed by station id — the one
reference in the schema with no foreign key, so the database cannot protect it.
Delete a station that still has lots standing on it and those units do not
cascade and do not error: they keep existing, keyed to a station that is gone.
They are invisible on the board, because a deleted station has no column, while
still counting in every total. That is inventory that exists in the system and
nowhere else.

**Blast radius.** Five endpoints destroy things on purpose. Each has to destroy
exactly what it says and nothing else — most importantly, nothing belonging to
another company. A destructive operation is the worst possible place for a
missing `companyId` filter, because the damage is done before anyone looks.
"""

import json
from pathlib import Path

import pytest

from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "battery-remanufacturing.json"


def _st(a: Actor, name: str, **kw) -> str:
    return a.req("POST", "/stations/", {**STATION, "name": name, **kw}).json()["_id"]


def _line(a: Actor):
    """Two stations, a route, a product, and six units standing on the first."""
    one, two = _st(a, "Cutting"), _st(a, "Welding")
    proc = a.req("POST", "/processes/", {"name": "Frames"}).json()["_id"]
    a.req("POST", "/routes/", {"processId": proc, "load": one, "unload": two, "quantity": 1})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Frame", "processId": proc,
                                             "startStationId": one}).json()["_id"]
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "F-1", "totalQuantity": 6,
                                     "bins": {one: {"count": 6}}}).json()
    return {"one": one, "two": two, "proc": proc, "tmpl": tmpl, "card": card}


def _bins(a: Actor):
    return {c["_id"]: c["bins"] for c in a.req("GET", "/cards/").json()}


def _stations(a: Actor):
    return {s["_id"] for s in a.req("GET", "/stations/").json()}


def _orphans(a: Actor):
    """Units keyed to a station that no longer exists."""
    live = _stations(a)
    return {(cid, sid): b["count"]
            for cid, bins in _bins(a).items()
            for sid, b in bins.items() if sid not in live}


# ── Deleting things the floor is still using ────────────────────────────────

def test_deleting_a_station_does_not_strand_units_on_it(actor):
    """Either the delete is refused because material is standing there, or the
    material goes with it. What must not happen is six units left keyed to a
    station id that resolves to nothing — present in every total, absent from
    every column, and impossible to move because the UI cannot draw a source
    for them."""
    a = actor(); bootstrap_admin(a)
    L = _line(a)

    r = a.req("DELETE", f"/stations/{L['one']}")
    if r.status_code < 400:
        assert _orphans(a) == {}, (
            "deleting a station left units keyed to it: "
            f"{_orphans(a)} — invisible on the board, still counted in totals")
    else:
        assert _bins(a)[L["card"]["_id"]] == {L["one"]: {"count": 6}}, \
            "a refused delete still disturbed the floor"


def test_deleting_a_station_a_lot_merely_passed_through_is_fine(actor):
    """The permissive half: a station with no units on it is ordinary
    housekeeping and must stay easy."""
    a = actor(); bootstrap_admin(a)
    L = _line(a)
    a.req("POST", f"/cards/{L['card']['_id']}/advance",
          {"fromStationId": L["one"], "toStationId": L["two"], "quantity": 6})

    assert a.req("DELETE", f"/stations/{L['one']}").status_code in (200, 204), \
        "an empty station could not be removed"
    assert _orphans(a) == {}


@pytest.mark.parametrize("what", ["process", "template"])
def test_deleting_a_process_or_product_leaves_no_dangling_material(actor, what):
    """Cards point at both with `ON DELETE SET NULL`, so the rows survive — but
    a lot with no product is a physical card with nothing printed on it. Either
    the delete is refused while lots exist, or the lots go too."""
    a = actor(); bootstrap_admin(a)
    L = _line(a)
    path = f"/processes/{L['proc']}" if what == "process" else f"/lot-templates/{L['tmpl']}"

    r = a.req("DELETE", path)
    cards = a.req("GET", "/cards/").json()
    if r.status_code >= 400:
        assert len(cards) == 1, "a refused delete still removed lots"
        return
    for c in cards:
        key = "processId" if what == "process" else "lotTemplateId"
        assert c.get(key), \
            f"a lot survived with no {what}: {c['_id'][:8]} is now unlabelled"


def test_a_deleted_lot_leaves_its_history_behind(actor):
    """The audit log deliberately has no FK, so the record of what happened
    outlives the card. Losing it would mean a scrapped lot's history vanishes
    with the evidence of why it was scrapped."""
    a = actor(); bootstrap_admin(a)
    L = _line(a)
    cid = L["card"]["_id"]
    a.req("POST", f"/cards/{cid}/advance",
          {"fromStationId": L["one"], "toStationId": L["two"], "quantity": 2})
    assert a.req("DELETE", f"/cards/{cid}").status_code in (200, 204)

    events = a.req("GET", f"/cards/{cid}/events")
    assert events.status_code == 200
    assert events.json(), "the lot's history died with the lot"


# ── Blast radius ────────────────────────────────────────────────────────────

def _neighbour():
    """A second company running its own line, which nothing below may touch."""
    b = Actor(); bootstrap_admin(b, "Neighbour")
    L = _line(b)
    a_card = L["card"]["_id"]
    s = b.req("POST", "/sessions/", {"stationId": L["one"], "cardId": a_card,
                                     "operatorId": "tablet-09", "quantity": 1})
    if s.status_code < 300:
        b.req("POST", f"/sessions/{s.json()['_id']}/end", {"quantity": 1})
    b.req("POST", "/orders/", {"productTemplateId": L["tmpl"], "quantity": 3,
                               "source": "manual", "externalRef": "NEIGHBOUR-1"})
    return b


def _everything(a: Actor):
    return {p: a.req("GET", p).json() for p in
            ("/stations/", "/routes/", "/processes/", "/lot-templates/",
             "/cards/", "/orders/", "/sessions/stats")}


DESTRUCTIVE = [
    ("reset", "POST", "/admin/reset", {}),
    ("reset statistics", "POST", "/admin/reset-statistics", {}),
    ("import a line", "POST", "/map-io/import", None),          # body filled in below
]


@pytest.mark.parametrize("label,method,path,body", DESTRUCTIVE,
                         ids=[d[0] for d in DESTRUCTIVE])
def test_a_destructive_operation_stops_at_the_company_boundary(actor, label, method, path, body):
    """The worst place for a missing companyId filter. By the time anyone
    notices, the other tenant's floor is gone."""
    neighbour = _neighbour()
    untouched = _everything(neighbour)

    a = actor(); bootstrap_admin(a)
    _line(a)
    if body is None:
        body = json.loads(EXAMPLE.read_text())

    r = a.req(method, path, body)
    assert r.status_code < 400, f"{label} failed outright: {r.text[:200]}"
    assert _everything(neighbour) == untouched, f"{label} reached into another company"


def test_wiping_the_statistics_keeps_the_line_and_the_lots(actor):
    """"Clean up my test data" must never mean "delete my factory". This is the
    distinction between /admin/reset-statistics and /admin/reset, and the two
    sit behind the same icon."""
    a = actor(); bootstrap_admin(a)
    L = _line(a)
    s = a.req("POST", "/sessions/", {"stationId": L["one"], "cardId": L["card"]["_id"],
                                     "operatorId": "tablet-01", "quantity": 2})
    a.req("POST", f"/sessions/{s.json()['_id']}/end", {"quantity": 2})
    before = {p: a.req("GET", p).json() for p in
              ("/stations/", "/routes/", "/processes/", "/lot-templates/", "/cards/")}

    assert a.req("POST", "/admin/reset-statistics", {}).status_code < 400
    after = {p: a.req("GET", p).json() for p in
             ("/stations/", "/routes/", "/processes/", "/lot-templates/", "/cards/")}
    assert after == before, "wiping the statistics changed the line"

    stats = a.req("GET", "/sessions/stats").json()
    rows = stats if isinstance(stats, list) else stats.get("stations", [])
    assert all((r.get("sessionCount") or 0) == 0 for r in rows), "the sessions survived the wipe"


def test_importing_a_line_says_goodbye_to_the_lots_on_the_old_one(actor):
    """Not a bug — `/map-io/import` REPLACES the line, and the lots and sessions
    go with it. Pinned because it is the closest thing the product has to a
    restore, and it is not one: a customer who exports their line, has a bad
    day, and imports it back gets an empty floor. If that ever changes, this
    test should be the thing that notices."""
    a = actor(); bootstrap_admin(a)
    _line(a)
    assert a.req("GET", "/cards/").json(), "fixture produced no lots"

    assert a.req("POST", "/map-io/import", json.loads(EXAMPLE.read_text())).status_code == 200
    assert a.req("GET", "/cards/").json() == [], \
        "import no longer clears the floor — good, but say so in the docs"
