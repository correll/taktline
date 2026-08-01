"""Undo and redo, judged against the floor rather than a client's memory.

The interesting cases are not "does it put the card back" — they are the ones
where it must REFUSE. On a line with several tablets the lot you moved a minute
ago may since have been merged by somebody at the next bench, and quietly
restoring a snapshot over that would destroy work nobody asked to lose. Better
to say no than to invent a plausible answer about material: the same discipline
that refuses a partial move back down a split branch.
"""

from tests.helpers import Actor, add_member, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _st(a: Actor, name: str, **kw) -> str:
    return a.req("POST", "/stations/", {**STATION, "name": name, **kw}).json()["_id"]


def _line(a: Actor, count=6):
    one, two = _st(a, "Cutting"), _st(a, "Welding")
    proc = a.req("POST", "/processes/", {"name": "Frames"}).json()["_id"]
    a.req("POST", "/routes/", {"processId": proc, "load": one, "unload": two, "quantity": 1})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Frame", "processId": proc,
                                             "startStationId": one}).json()["_id"]
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "F-1", "totalQuantity": count,
                                     "bins": {one: {"count": count}}}).json()
    return one, two, proc, tmpl, card


def _units(a: Actor):
    out: dict = {}
    for c in a.req("GET", "/cards/").json():
        for sid, b in c["bins"].items():
            out[sid] = out.get(sid, 0) + b["count"]
    return out


# ── The ordinary case ───────────────────────────────────────────────────────

def test_a_move_can_be_taken_back(actor):
    a = actor(); bootstrap_admin(a)
    one, two, proc, tmpl, card = _line(a)
    before = _units(a)

    assert a.req("POST", f"/cards/{card['_id']}/move",
                 {"fromStationId": one, "toStationId": two, "quantity": 2}).status_code == 200
    assert _units(a) == {one: 4, two: 2}

    r = a.req("POST", "/undo", {})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Move lot"
    assert _units(a) == before


def test_redo_puts_it_back_again(actor):
    a = actor(); bootstrap_admin(a)
    one, two, proc, tmpl, card = _line(a)
    a.req("POST", f"/cards/{card['_id']}/move",
          {"fromStationId": one, "toStationId": two, "quantity": 2})
    moved = _units(a)

    a.req("POST", "/undo", {})
    assert a.req("POST", "/redo", {}).status_code == 200
    assert _units(a) == moved


def test_undo_walks_back_more_than_one_step(actor):
    a = actor(); bootstrap_admin(a)
    one, two, proc, tmpl, card = _line(a)
    start = _units(a)
    for _ in range(3):
        a.req("POST", f"/cards/{card['_id']}/move",
              {"fromStationId": one, "toStationId": two, "quantity": 1})
    assert _units(a) == {one: 3, two: 3}
    for _ in range(3):
        assert a.req("POST", "/undo", {}).status_code == 200
    assert _units(a) == start


def test_nothing_to_undo_is_said_plainly(actor):
    a = actor(); bootstrap_admin(a)
    _line(a)
    r = a.req("POST", "/undo", {})
    assert r.status_code == 409
    assert "Nothing to undo" in r.text


# ── A merge is undoable, which is the point ─────────────────────────────────

def test_a_merge_can_be_taken_back(actor):
    """The expensive mis-tap: an assembly built from the wrong precursors.
    Undo restores the parts rather than trying to reverse the recipe."""
    a = actor(); bootstrap_admin(a)
    x, y, m = _st(a, "Frames"), _st(a, "Glass"), _st(a, "Glazing")
    proc = a.req("POST", "/processes/", {"name": "Windows"}).json()["_id"]
    for load in (x, y):
        a.req("POST", "/routes/", {"processId": proc, "load": load, "unload": m,
                                   "quantity": 1})
    tm = {}
    for name, station in (("Frame", x), ("Pane", y), ("Window", m)):
        tm[name] = a.req("POST", "/lot-templates/", {
            "name": name, "processId": proc, "startStationId": station}).json()["_id"]
    for name in ("Frame", "Pane"):
        a.req("POST", "/cards/", {"lotTemplateId": tm[name], "processId": proc,
                                  "lotNum": f"{name}-1", "totalQuantity": 2,
                                  "bins": {m: {"count": 2}}})
    before = _units(a)

    res = a.req("POST", f"/merge/{m}", {})
    assert res.status_code in (200, 201), res.text
    assert _units(a) != before

    r = a.req("POST", "/undo", {})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Merge into an assembly"
    assert _units(a) == before
    assert not [c for c in a.req("GET", "/cards/").json()
                if c["lotTemplateId"] == tm["Window"]], "the assembly survived the undo"


# ── The refusals, which are the whole reason this lives on the server ───────

def test_an_undo_is_refused_once_somebody_else_has_moved_those_lots(actor):
    """Two tablets. One moves a lot, the other moves it on, and the first
    presses undo. Restoring the snapshot would silently erase the second
    worker's move — so it is refused, and says why."""
    a = actor(); bootstrap_admin(a)
    one, two, proc, tmpl, card = _line(a)
    other = actor(); add_member(a, other, role="user")

    a.req("POST", f"/cards/{card['_id']}/move",
          {"fromStationId": one, "toStationId": two, "quantity": 2})
    mid = _units(a)

    # The colleague advances the very units the first move produced.
    assert other.req("POST", f"/cards/{card['_id']}/advance",
                     {"fromStationId": one, "toStationId": two,
                      "quantity": 1}).status_code == 200

    r = a.req("POST", "/undo", {})
    assert r.status_code == 409, r.text
    assert "moved on since" in r.text
    assert _units(a) != mid, "the fixture did not actually change the lots"
    assert _units(a) == {one: 3, two: 3}, "a refused undo still changed the floor"


def test_a_stack_is_per_person(actor):
    """An operator pressing undo must not reverse the supervisor's last drag
    from across the room."""
    a = actor(); bootstrap_admin(a)
    one, two, proc, tmpl, card = _line(a)
    other = actor(); add_member(a, other, role="user")

    a.req("POST", f"/cards/{card['_id']}/move",
          {"fromStationId": one, "toStationId": two, "quantity": 2})

    r = other.req("POST", "/undo", {})
    assert r.status_code == 409, "one person undid another's work"
    assert "Nothing to undo" in r.text


def test_doing_something_new_drops_the_redo_branch(actor):
    a = actor(); bootstrap_admin(a)
    one, two, proc, tmpl, card = _line(a)
    a.req("POST", f"/cards/{card['_id']}/move",
          {"fromStationId": one, "toStationId": two, "quantity": 2})
    a.req("POST", "/undo", {})

    a.req("POST", f"/cards/{card['_id']}/move",
          {"fromStationId": one, "toStationId": two, "quantity": 1})
    r = a.req("POST", "/redo", {})
    assert r.status_code == 409 and "Nothing to redo" in r.text


# ── What the buttons read ───────────────────────────────────────────────────

def test_the_buttons_know_what_they_would_do(actor):
    a = actor(); bootstrap_admin(a)
    one, two, proc, tmpl, card = _line(a)
    s = a.req("GET", "/undo/state").json()
    assert s == {"canUndo": False, "canRedo": False, "undoLabel": None, "redoLabel": None}

    a.req("POST", f"/cards/{card['_id']}/move",
          {"fromStationId": one, "toStationId": two, "quantity": 2})
    s = a.req("GET", "/undo/state").json()
    assert s["canUndo"] and s["undoLabel"] == "Move lot" and not s["canRedo"]

    a.req("POST", "/undo", {})
    s = a.req("GET", "/undo/state").json()
    assert s["canRedo"] and s["redoLabel"] == "Move lot" and not s["canUndo"]


def test_an_operator_may_undo_their_own_work(actor):
    """The lowest tier can move lots on the operator view, so it must be able
    to take one back — otherwise a mis-tap needs a super-admin."""
    a = actor(); bootstrap_admin(a)
    one, two, proc, tmpl, card = _line(a)
    op = actor(); add_member(a, op, role="user")

    assert op.req("POST", f"/cards/{card['_id']}/advance",
                  {"fromStationId": one, "toStationId": two, "quantity": 1}).status_code == 200
    r = op.req("POST", "/undo", {})
    assert r.status_code == 200, r.text
    assert _units(a) == {one: 6}


def test_a_read_only_action_records_nothing(actor):
    """Only things that changed the floor go on the stack. A refused move must
    not leave an entry that undoes the move before it."""
    a = actor(); bootstrap_admin(a)
    one, two, proc, tmpl, card = _line(a)
    a.req("POST", f"/cards/{card['_id']}/move",
          {"fromStationId": one, "toStationId": two, "quantity": 2})
    a.req("POST", f"/cards/{card['_id']}/move",
          {"fromStationId": one, "toStationId": two, "quantity": 999})   # refused

    assert a.req("GET", "/undo/state").json()["undoLabel"] == "Move lot"
    assert a.req("POST", "/undo", {}).status_code == 200
    assert _units(a) == {one: 6}
