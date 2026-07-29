"""A choice station: the split's shape with the opposite meaning.

Two or more outgoing routes normally make a station a split — advancing a lot
out of it mints a piece on every branch. Declaring the station a **choice**
(`station.branchMode = 'choice'`) turns the same shape into either/or routing:
every lot leaves 1:1 down the one branch the worker names. Nothing is minted,
nothing is relabelled, and nothing recombines on the way back.

What this file pins:

- advancing out of a choice station moves 1:1 to the named branch — same card,
  same product, units conserved — for every branch
- moving back onto a choice station is a plain move, not an un-split
- a weight on a route out of a choice station is refused unless the target is
  a merge (that weight belongs to the merge); declaring a branch product is
  always refused
- declaring an existing split a choice strips the split-only meaning from its
  routes: branch products go, stale branch weights reset, merge-feed weights
  survive
- a pull through a choice diamond SUMS demand — each unit goes down one branch,
  so two branches needing one each order two, where a split diamond orders one
- the export carries the declaration and an imported file restores it
"""

from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _st(a, name, **kw):
    r = a.req("POST", "/stations/", {**STATION, "name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _proc(a, name):
    r = a.req("POST", "/processes/", {"name": name})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _route(a, proc, load, unload, **kw):
    r = a.req("POST", "/routes/", {"processId": proc, "load": load,
                                   "unload": unload, "quantity": 1, **kw})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _tmpl(a, name, proc, station):
    r = a.req("POST", "/lot-templates/", {"name": name, "processId": proc,
                                          "startStationId": station})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _cards(a):
    return a.req("GET", "/cards/").json()


def _advance(a, card_id, frm, to, qty):
    return a.req("POST", f"/cards/{card_id}/advance",
                 {"fromStationId": frm, "toStationId": to, "quantity": qty})


class Rig:
    pass


def _fork_line(a: Actor, mode=None) -> Rig:
    """queue → fork → {left, right}; a source product starts at the queue."""
    g = Rig()
    g.queue = _st(a, "Queue")
    g.fork  = _st(a, "Fork", **({"branchMode": mode} if mode else {}))
    g.left  = _st(a, "Left")
    g.right = _st(a, "Right")
    g.p     = _proc(a, "Line")
    _route(a, g.p, g.queue, g.fork)
    g.r_left  = _route(a, g.p, g.fork, g.left)
    g.r_right = _route(a, g.p, g.fork, g.right)
    g.tmpl = _tmpl(a, "Widget", g.p, g.queue)
    r = a.req("POST", "/cards/", {"lotTemplateId": g.tmpl, "processId": g.p,
                                  "totalQuantity": 4,
                                  "bins": {g.queue: {"count": 4}}})
    assert r.status_code == 201, r.text
    g.card = r.json()["_id"]
    assert _advance(a, g.card, g.queue, g.fork, 4).status_code == 200
    return g


def test_choice_station_moves_one_to_one_to_the_named_branch(actor):
    a = actor(); bootstrap_admin(a)
    g = _fork_line(a, mode="choice")
    before = {c["_id"] for c in _cards(a)}

    assert _advance(a, g.card, g.fork, g.left, 1).status_code == 200
    assert _advance(a, g.card, g.fork, g.right, 3).status_code == 200

    assert {c["_id"] for c in _cards(a)} == before, "a choice minted cards"
    fresh = a.req("GET", f"/cards/{g.card}").json()
    assert fresh["lotTemplateId"] == g.tmpl, "a choice relabelled the lot"
    assert fresh["bins"] == {g.left: {"count": 1}, g.right: {"count": 3}}, fresh["bins"]


def test_the_same_shape_without_the_declaration_still_splits(actor):
    a = actor(); bootstrap_admin(a)
    g = _fork_line(a)                                # no branchMode → split
    assert _advance(a, g.card, g.fork, g.left, 4).status_code == 200
    cards = _cards(a)
    assert len(cards) == 2, "a split mints one lot per branch"
    assert sorted(list(c["bins"].keys())[0] for c in cards) == sorted([g.left, g.right])


def test_moving_back_onto_a_choice_station_is_a_plain_move(actor):
    a = actor(); bootstrap_admin(a)
    g = _fork_line(a, mode="choice")
    assert _advance(a, g.card, g.fork, g.left, 4).status_code == 200
    # A partial move back would be refused at a split (it un-splits whole units
    # and needs the twins); at a choice it is just a move.
    r = a.req("POST", f"/cards/{g.card}/move",
              {"fromStationId": g.left, "toStationId": g.fork, "quantity": 3})
    assert r.status_code == 200, r.text
    fresh = a.req("GET", f"/cards/{g.card}").json()
    assert fresh["bins"] == {g.fork: {"count": 3}, g.left: {"count": 1}}, fresh["bins"]


def test_split_only_meanings_are_refused_on_a_choice_station(actor):
    a = actor(); bootstrap_admin(a)
    g = _fork_line(a, mode="choice")
    # A branch weight is a split's meaning (1 unit becomes N pieces).
    r = a.req("PUT", f"/routes/{g.r_left}", {"quantity": 3})
    assert r.status_code == 400, r.text
    # So is a declared branch product.
    r = a.req("PUT", f"/routes/{g.r_left}", {"outputTemplateId": g.tmpl})
    assert r.status_code == 400 and "choice station routes lots unchanged" in r.text
    # And the declaration itself is validated.
    r = a.req("PUT", f"/stations/{g.fork}", {"branchMode": "sometimes"})
    assert r.status_code == 400, r.text


def test_declaring_a_split_a_choice_strips_split_semantics(actor):
    a = actor(); bootstrap_admin(a)
    g = _fork_line(a)                                # a real split first
    piece = _tmpl(a, "Piece", g.p, g.left)
    a.req("PUT", f"/routes/{g.r_left}", {"quantity": 4, "outputTemplateId": piece})
    # Give the right branch a merge target so its weight must SURVIVE the flip.
    g.sink  = _st(a, "Sink")
    g.other = _st(a, "Other")
    _route(a, g.p, g.right, g.sink)
    _route(a, g.p, g.other, g.sink)                  # sink is now a merge
    r_rs = a.req("GET", "/routes/").json()
    right_sink = next(x["_id"] for x in r_rs if x["load"] == g.right and x["unload"] == g.sink)
    assert a.req("PUT", f"/routes/{right_sink}", {"quantity": 5}).status_code == 200

    assert a.req("PUT", f"/stations/{g.fork}", {"branchMode": "choice"}).status_code == 200

    routes = {x["_id"]: x for x in a.req("GET", "/routes/").json()}
    assert routes[g.r_left]["quantity"] == 1, "stale branch weight survived the flip"
    assert routes[g.r_left]["outputTemplateId"] is None, "branch product survived the flip"
    assert routes[right_sink]["quantity"] == 5, "a merge feed's weight belongs to the merge"


def test_a_choice_diamond_pulls_the_sum_not_the_max(actor):
    """source → chooser → {left, right} → assembly. Each unit goes down ONE
    branch, so one assembly (consuming one from each side) needs TWO units at
    the source. A split diamond orders one — that is the whole difference."""
    a = actor(); bootstrap_admin(a)
    g = Rig()
    g.src   = _st(a, "Source")
    g.choose = _st(a, "Chooser", branchMode="choice")
    g.left  = _st(a, "Left")
    g.right = _st(a, "Right")
    g.asm   = _st(a, "Assembly")
    g.p     = _proc(a, "Diamond")
    _route(a, g.p, g.src, g.choose)
    _route(a, g.p, g.choose, g.left)
    _route(a, g.p, g.choose, g.right)
    _route(a, g.p, g.left, g.asm)
    _route(a, g.p, g.right, g.asm)
    _tmpl(a, "Raw", g.p, g.src)
    _tmpl(a, "Prepped L", g.p, g.left)
    _tmpl(a, "Prepped R", g.p, g.right)
    _tmpl(a, "Assembled", g.p, g.asm)

    r = a.req("POST", f"/merge/{g.asm}/pull", {"quantity": 1})
    assert r.status_code == 201, r.text
    seeded = [c for c in _cards(a) if c["bins"].get(g.src)]
    assert sum(c["bins"][g.src]["count"] for c in seeded) == 2, \
        "a choice diamond must order one unit per branch, not the max"


def test_export_and_import_carry_the_declaration(actor):
    a = actor(); bootstrap_admin(a)
    _fork_line(a, mode="choice")
    doc = a.req("GET", "/map-io/export").json()
    fork = next(s for s in doc["stations"] if s["name"] == "Fork")
    assert fork["branchMode"] == "choice"

    b = actor(); bootstrap_admin(b)
    assert b.req("POST", "/map-io/import", doc).status_code == 200
    stations = b.req("GET", "/stations/").json()
    assert next(s for s in stations if s["name"] == "Fork")["branchMode"] == "choice"
