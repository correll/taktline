"""Two tablets, one lot, at the same instant.

The code is full of `with_for_update` and one-transaction-per-request, and
until now nothing exercised any of it: every other test sends one request at a
time, which is the one condition under which a missing lock looks fine. The
simulator hammered eight tablets at the real server and that is where the
races showed — but a simulator is not a regression test, and a race that comes
back will come back quietly.

Each test here fires N genuinely parallel requests (separate threads, separate
event loops, therefore separate database connections and separate
transactions) and asserts the property that must survive them: the *outcome*
is one of the legal serial outcomes. Not "no error" — a race usually returns
200 twice and corrupts the floor.

A passing run is weak evidence on its own, since a race can hide. A failing
run is strong evidence, and these fail loudly when the lock is removed, which
is what they exist for.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _station(a: Actor, name: str, **kw) -> str:
    return a.req("POST", "/stations/", {**STATION, "name": name, **kw}).json()["_id"]


def _units(a: Actor):
    out: dict = {}
    for c in a.req("GET", "/cards/").json():
        for sid, b in c["bins"].items():
            out[sid] = out.get(sid, 0) + b["count"]
    return out


def _race(n: int, call):
    """Fire `call(i)` from n real threads at once.

    Threads rather than an async gather: each TestClient request gets its own
    portal and therefore its own event loop and connection, which is what makes
    these separate transactions competing in Postgres rather than one task
    politely awaiting another.
    """
    with ThreadPoolExecutor(max_workers=n) as pool:
        return [f.result() for f in [pool.submit(call, i) for i in range(n)]]


# ── A merge bench two tablets reach for at once ─────────────────────────────

def _merge_line(a: Actor, per_feed=3):
    x, y, m = _station(a, "Frames"), _station(a, "Glass"), _station(a, "Glazing")
    proc = a.req("POST", "/processes/", {"name": "Windows"}).json()["_id"]
    for load in (x, y):
        assert a.req("POST", "/routes/", {"processId": proc, "load": load,
                                          "unload": m, "quantity": 1}).status_code == 201
    tm = {}
    for name, station in (("Frame", x), ("Pane", y), ("Window", m)):
        tm[name] = a.req("POST", "/lot-templates/",
                         {"name": name, "processId": proc,
                          "startStationId": station}).json()["_id"]
    # Exactly enough for ONE assembly, standing on the bench.
    for name in ("Frame", "Pane"):
        a.req("POST", "/cards/", {"lotTemplateId": tm[name], "processId": proc,
                                  "lotNum": f"{name}-1", "totalQuantity": 1,
                                  "bins": {m: {"count": 1}}})
    return proc, x, y, m, tm


def test_two_tablets_merging_at_once_make_one_assembly(actor):
    """There is one assembly's worth of parts on the bench. Two workers press
    MERGE together. One must win: two assemblies from one set of parts is
    inventory invented at the moment two people happened to tap at once."""
    a = actor(); bootstrap_admin(a)
    proc, x, y, m, tm = _merge_line(a)

    results = _race(4, lambda _i: actor())
    for r in results:
        r.tc.cookies.update(a.tc.cookies)
        r.company = a.company
    codes = _race(4, lambda i: results[i].req("POST", f"/merge/{m}", {}).status_code)

    made = [c for c in a.req("GET", "/cards/").json()
            if c["lotTemplateId"] == tm["Window"]]
    total = sum(b["count"] for c in made for b in c["bins"].values())
    assert total == 1, f"{total} assemblies from one set of parts (codes {codes})"
    assert _units(a) == {m: 1}, f"parts left over or duplicated: {_units(a)}"


# ── One lot, two people advancing it ────────────────────────────────────────

def _chain(a: Actor, count=4):
    one, two = _station(a, "Cutting"), _station(a, "Welding")
    proc = a.req("POST", "/processes/", {"name": "Frames"}).json()["_id"]
    a.req("POST", "/routes/", {"processId": proc, "load": one, "unload": two,
                               "quantity": 1})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Frame", "processId": proc,
                                             "startStationId": one}).json()["_id"]
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "F-1", "totalQuantity": count,
                                     "bins": {one: {"count": count}}}).json()
    return one, two, card


def test_the_same_advance_fired_twice_moves_the_units_once(actor):
    """A double-fired drag, a StrictMode effect, a scanner reading the same
    label twice. Four units exist; four must arrive."""
    a = actor(); bootstrap_admin(a)
    one, two, card = _chain(a, count=4)

    clients = [actor() for _ in range(5)]
    for c in clients:
        c.tc.cookies.update(a.tc.cookies)
        c.company = a.company
    _race(5, lambda i: clients[i].req(
        "POST", f"/cards/{card['_id']}/advance",
        {"fromStationId": one, "toStationId": two, "quantity": 4}).status_code)

    assert _units(a) == {two: 4}, f"units were duplicated or lost: {_units(a)}"


def test_racing_advances_of_one_unit_each_never_exceed_the_stock(actor):
    """Five tablets each grab one unit from a bin holding two. Three of them
    have to be told no — the bin is not a fountain."""
    a = actor(); bootstrap_admin(a)
    one, two, card = _chain(a, count=2)

    clients = [actor() for _ in range(5)]
    for c in clients:
        c.tc.cookies.update(a.tc.cookies)
        c.company = a.company
    codes = _race(5, lambda i: clients[i].req(
        "POST", f"/cards/{card['_id']}/advance",
        {"fromStationId": one, "toStationId": two, "quantity": 1}).status_code)

    moved = _units(a).get(two, 0)
    assert moved == 2, f"{moved} units arrived from a bin of 2 (codes {codes})"
    assert sum(_units(a).values()) == 2, f"total changed: {_units(a)}"


# ── A merge racing a move of the very parts it is consuming ─────────────────

def test_a_merge_and_a_move_of_its_parts_cannot_both_win(actor):
    """The merge plans against what it saw, then consumes. If a move takes the
    parts in between, the merge must fail rather than assemble from units that
    are no longer there — the 409 that path raises exists for exactly this."""
    a = actor(); bootstrap_admin(a)
    proc, x, y, m, tm = _merge_line(a)
    elsewhere = _station(a, "Rework")

    frame = [c for c in a.req("GET", "/cards/").json()
             if c["lotTemplateId"] == tm["Frame"]][0]

    merger, mover = actor(), actor()
    for c in (merger, mover):
        c.tc.cookies.update(a.tc.cookies)
        c.company = a.company

    def go(i):
        if i == 0:
            return ("merge", merger.req("POST", f"/merge/{m}", {}).status_code)
        return ("move", mover.req("POST", f"/cards/{frame['_id']}/move",
                                  {"fromStationId": m, "toStationId": elsewhere,
                                   "quantity": 1}).status_code)

    dict(_race(2, go))
    stock = _units(a)
    windows = sum(b["count"] for c in a.req("GET", "/cards/").json()
                  for b in c["bins"].values() if c["lotTemplateId"] == tm["Window"])

    # Either the merge won (one window, nothing at Rework) or the move won (no
    # window, the frame at Rework). Never both, and never a window built from a
    # frame that also arrived at Rework.
    assert (windows == 1 and elsewhere not in stock) or \
           (windows == 0 and stock.get(elsewhere) == 1), \
        f"the merge and the move both took the same frame: windows={windows} {stock}"


# ── Order release is idempotent even when redelivered simultaneously ────────

def test_a_webhook_redelivered_at_the_same_instant_releases_once(actor):
    """An ERP retrying a webhook is the normal case, and two deliveries can
    land together. Idempotency that only holds when the calls are sequential is
    not idempotency — it is luck, and the symptom is a doubled production run."""
    a = actor(); bootstrap_admin(a)
    one, two, card = _chain(a)
    tmpl = a.req("GET", "/lot-templates/").json()[0]["_id"]

    clients = [actor() for _ in range(4)]
    for c in clients:
        c.tc.cookies.update(a.tc.cookies)
        c.company = a.company
    body = {"productTemplateId": tmpl, "quantity": 5, "source": "odoo",
            "externalRef": "MO/00042"}
    codes = _race(4, lambda i: clients[i].req("POST", "/orders/", body).status_code)

    orders = [o for o in a.req("GET", "/orders/").json()
              if o["externalRef"] == "MO/00042"]
    assert len(orders) == 1, f"{len(orders)} orders from one reference (codes {codes})"
    assert sorted(codes).count(201) <= 1, f"more than one release reported: {codes}"


# ── One login, one lot: a work session starts while the lot moves ───────────

def test_session_start_and_advance_on_one_lot_never_deadlock(actor):
    """A tablet starts work on a lot at one bench while another part of the same
    lot is advanced between two others. Both requests come from the same login
    (a shared station login is common). They used to take the same two row
    locks in opposite orders: advance locked the card FOR UPDATE and only then
    flushed the login session's lastSeenAt; a session start flushed lastSeenAt
    first and then inserted a row whose foreign key waits on the card. Postgres
    broke the cycle by failing one request with a 500. Shift changes produce
    exactly this mix."""
    a = actor(); bootstrap_admin(a)
    s1, s2, s3 = _station(a, "Weld"), _station(a, "Assemble"), _station(a, "Test")
    proc = a.req("POST", "/processes/", {"name": "Brackets"}).json()["_id"]
    for load, unload in ((s1, s2), (s2, s3)):
        assert a.req("POST", "/routes/", {"processId": proc, "load": load,
                                          "unload": unload, "quantity": 1}).status_code == 201
    tm = a.req("POST", "/lot-templates/", {"name": "Bracket", "processId": proc,
                                           "startStationId": s1}).json()["_id"]
    rounds, n = 12, 8
    card = a.req("POST", "/cards/", {"lotTemplateId": tm, "processId": proc, "lotNum": "L-1",
                                     "totalQuantity": rounds * n,
                                     "bins": {s1: {"count": rounds * n}}}).json()["_id"]
    clients = _race(n, lambda _i: actor())
    for c in clients:
        c.tc.cookies.update(a.tc.cookies)
        c.company = a.company

    def call(i):
        c = clients[i]
        if i % 2:
            return c.req("POST", f"/cards/{card}/advance",
                         {"fromStationId": s1, "toStationId": s2, "quantity": 1}).status_code
        return c.req("POST", "/sessions/", {"stationId": s3, "cardId": card,
                                            "operatorId": f"op{i}", "quantity": 1}).status_code

    codes = [code for _ in range(rounds) for code in _race(n, call)]
    assert all(code in (200, 201) for code in codes), sorted(set(codes))
    moved = rounds * (n // 2)
    assert _units(a).get(s2) == moved          # every advance landed exactly once
