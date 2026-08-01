"""Undo and redo for the graph editor.

**Lots are deliberately out of scope, and that is the important design fact.**
A lot card records a physical fact — where the material actually is. Undoing a
move does not carry the material back down the shop, so the board would start
lying about the floor, which is the one thing it exists not to do. Drawing the
line is different: a mis-clicked delete destroys work with no physical
counterpart, and putting it back is simply correct.

The interesting cases below are the refusals. Two people can be editing the
same line from different rooms, and quietly restoring a snapshot over somebody
else's redraw would lose their work without telling them.
"""

from tests.helpers import Actor, add_member, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _st(a: Actor, name: str, **kw):
    r = a.req("POST", "/stations/", {**STATION, "name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _names(a: Actor):
    return sorted(s["name"] for s in a.req("GET", "/stations/").json())


def _routes(a: Actor):
    return sorted((r["load"], r["unload"]) for r in a.req("GET", "/routes/").json())


def _line(a: Actor):
    one, two = _st(a, "Cutting"), _st(a, "Welding")
    proc = a.req("POST", "/processes/", {"name": "Frames"}).json()["_id"]
    return one, two, proc


# ── Stations ────────────────────────────────────────────────────────────────

def test_adding_a_station_can_be_taken_back(actor):
    a = actor(); bootstrap_admin(a)
    _st(a, "Cutting")
    assert _names(a) == ["Cutting"]

    _st(a, "Oops")
    assert _names(a) == ["Cutting", "Oops"]

    r = a.req("POST", "/undo", {})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Add Oops"
    assert _names(a) == ["Cutting"]


def test_deleting_a_station_can_be_taken_back(actor):
    """The one that matters. A mis-clicked delete on the floor plan is the
    whole reason this exists."""
    a = actor(); bootstrap_admin(a)
    one = _st(a, "Cutting"); _st(a, "Welding")

    assert a.req("DELETE", f"/stations/{one}").status_code in (200, 204)
    assert _names(a) == ["Welding"]

    r = a.req("POST", "/undo", {})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Delete Cutting"
    assert _names(a) == ["Cutting", "Welding"]
    # Back under its own id, so anything still pointing at it resolves.
    assert any(s["_id"] == one for s in a.req("GET", "/stations/").json())


def test_renaming_a_station_can_be_taken_back(actor):
    a = actor(); bootstrap_admin(a)
    one = _st(a, "Cutting")
    a.req("PUT", f"/stations/{one}", {**STATION, "name": "Cuttign"})
    assert _names(a) == ["Cuttign"]

    assert a.req("POST", "/undo", {}).status_code == 200
    assert _names(a) == ["Cutting"]


def test_moving_a_station_on_the_floor_plan_can_be_taken_back(actor):
    a = actor(); bootstrap_admin(a)
    one = _st(a, "Cutting")
    a.req("PUT", f"/stations/{one}", {**STATION, "name": "Cutting",
                                      "position": {"x": 900, "y": 700, "width": 60, "height": 60}})
    assert a.req("GET", f"/stations/{one}").json()["position"]["x"] == 900

    assert a.req("POST", "/undo", {}).status_code == 200
    assert a.req("GET", f"/stations/{one}").json()["position"]["x"] == 1


# ── Routes ──────────────────────────────────────────────────────────────────

def test_drawing_a_route_can_be_taken_back(actor):
    a = actor(); bootstrap_admin(a)
    one, two, proc = _line(a)
    assert a.req("POST", "/routes/", {"processId": proc, "load": one,
                                      "unload": two, "quantity": 1}).status_code == 201
    assert _routes(a) == [(one, two)]

    r = a.req("POST", "/undo", {})
    assert r.status_code == 200 and r.json()["label"] == "Draw a route"
    assert _routes(a) == []


def test_deleting_a_route_can_be_taken_back(actor):
    a = actor(); bootstrap_admin(a)
    one, two, proc = _line(a)
    rid = a.req("POST", "/routes/", {"processId": proc, "load": one,
                                     "unload": two, "quantity": 1}).json()["_id"]
    assert a.req("DELETE", f"/routes/{rid}").status_code in (200, 204)
    assert _routes(a) == []

    assert a.req("POST", "/undo", {}).status_code == 200
    assert _routes(a) == [(one, two)]


def test_undoing_a_station_brings_its_routes_with_it(actor):
    """Deleting a station cascades its routes away. The undo has to put both
    back, and in an order the foreign keys accept — routes cannot exist before
    the station they end at."""
    a = actor(); bootstrap_admin(a)
    one, two, proc = _line(a)
    a.req("POST", "/routes/", {"processId": proc, "load": one, "unload": two, "quantity": 1})

    assert a.req("DELETE", f"/stations/{two}").status_code in (200, 204)
    assert _routes(a) == []

    r = a.req("POST", "/undo", {})
    assert r.status_code == 200, r.text
    assert _names(a) == ["Cutting", "Welding"]
    assert _routes(a) == [(one, two)], "the route did not come back with its station"


def test_undo_walks_back_several_edits(actor):
    a = actor(); bootstrap_admin(a)
    _st(a, "A"); _st(a, "B"); _st(a, "C")
    assert _names(a) == ["A", "B", "C"]
    for _ in range(2):
        assert a.req("POST", "/undo", {}).status_code == 200
    assert _names(a) == ["A"]


def test_redo_puts_the_edit_back(actor):
    a = actor(); bootstrap_admin(a)
    _st(a, "A"); _st(a, "B")
    a.req("POST", "/undo", {})
    assert _names(a) == ["A"]
    assert a.req("POST", "/redo", {}).status_code == 200
    assert _names(a) == ["A", "B"]


# ── The refusals ────────────────────────────────────────────────────────────

def test_an_undo_is_refused_once_somebody_else_has_changed_it(actor):
    """Two admins, one line. The second renames the station the first just
    added; the first presses undo. Deleting it now would take the rename with
    it, so it is refused and says why."""
    a = actor(); bootstrap_admin(a)
    other = actor(); add_member(a, other, role="super_admin")

    one = _st(a, "Cutting")
    assert other.req("PUT", f"/stations/{one}",
                     {**STATION, "name": "Cutting cell"}).status_code == 200

    r = a.req("POST", "/undo", {})
    assert r.status_code == 409, r.text
    assert "moved on since" in r.text
    assert _names(a) == ["Cutting cell"], "a refused undo still changed the line"


def test_a_stack_is_per_person(actor):
    a = actor(); bootstrap_admin(a)
    other = actor(); add_member(a, other, role="super_admin")
    _st(a, "Cutting")

    r = other.req("POST", "/undo", {})
    assert r.status_code == 409 and "Nothing to undo" in r.text
    assert _names(a) == ["Cutting"]


def test_nothing_to_undo_is_said_plainly(actor):
    a = actor(); bootstrap_admin(a)
    r = a.req("POST", "/undo", {})
    assert r.status_code == 409 and "Nothing to undo" in r.text


def test_doing_something_new_drops_the_redo_branch(actor):
    a = actor(); bootstrap_admin(a)
    _st(a, "A"); _st(a, "B")
    a.req("POST", "/undo", {})
    _st(a, "C")

    r = a.req("POST", "/redo", {})
    assert r.status_code == 409 and "Nothing to redo" in r.text


def test_a_refused_edit_records_nothing(actor):
    """Only edits that changed the line go on the stack, or an undo would skip
    past the last real one."""
    a = actor(); bootstrap_admin(a)
    _st(a, "Cutting")
    # A route to a station that does not exist: refused, and must leave the
    # stack pointing at the last thing that really happened.
    a.req("POST", "/routes/", {"processId": "00000000-0000-0000-0000-000000000000",
                               "load": "00000000-0000-0000-0000-000000000000",
                               "unload": "00000000-0000-0000-0000-000000000001",
                               "quantity": 1})

    assert a.req("GET", "/undo/state").json()["undoLabel"] == "Add Cutting"
    assert a.req("POST", "/undo", {}).status_code == 200
    assert _names(a) == []


# ── What the buttons read ───────────────────────────────────────────────────

def test_the_buttons_know_what_they_would_do(actor):
    a = actor(); bootstrap_admin(a)
    assert a.req("GET", "/undo/state").json() == {
        "canUndo": False, "canRedo": False, "undoLabel": None, "redoLabel": None}

    _st(a, "Cutting")
    s = a.req("GET", "/undo/state").json()
    assert s["canUndo"] and s["undoLabel"] == "Add Cutting" and not s["canRedo"]

    a.req("POST", "/undo", {})
    s = a.req("GET", "/undo/state").json()
    assert s["canRedo"] and s["redoLabel"] == "Add Cutting" and not s["canUndo"]


def test_lot_movements_are_not_undoable(actor):
    """The scope decision, pinned. Moving a lot is a record of something that
    physically happened; undoing it in software would make the board disagree
    with the shop, and the board's only job is to agree with the shop."""
    a = actor(); bootstrap_admin(a)
    one, two, proc = _line(a)
    a.req("POST", "/routes/", {"processId": proc, "load": one, "unload": two, "quantity": 1})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Frame", "processId": proc,
                                             "startStationId": one}).json()["_id"]
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "F-1", "totalQuantity": 4,
                                     "bins": {one: {"count": 4}}}).json()
    # Undoing the setup would tear the line down, so compare the stack across
    # the move instead: the top of it must not have changed.
    top = a.req("GET", "/undo/state").json()["undoLabel"]

    assert a.req("POST", f"/cards/{card['_id']}/advance",
                 {"fromStationId": one, "toStationId": two,
                  "quantity": 2}).status_code == 200
    assert a.req("GET", "/undo/state").json()["undoLabel"] == top, \
        "a lot movement was recorded as undoable"
