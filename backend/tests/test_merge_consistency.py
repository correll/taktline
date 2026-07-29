"""Merge/unmerge conservation: cycling lots into an assembly and back must never
create or destroy units, even under concurrent duplicate requests (the React
StrictMode double-fire that minted duplicate lots)."""

import threading

from tests.helpers import bootstrap_admin, add_member


# ─── Setup helpers ────────────────────────────────────────────────────────────

def _mk_station(a, name, x):
    r = a.req("POST", "/stations/", {"name": name, "position": {"x": x, "y": 100, "width": 60, "height": 60}})
    assert r.status_code == 201, r.text
    return r.json()


def _setup_line(a):
    """Tutorial line: Steel ×1 + Motor ×3 → Assembly → Testing → Warehouse."""
    steel = _mk_station(a, "Steel", 100)
    motor = _mk_station(a, "Motor", 200)
    asm   = _mk_station(a, "Assembly", 300)
    test  = _mk_station(a, "Testing", 400)
    wh    = _mk_station(a, "Warehouse", 500)
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()
    for load, unload, q in [(steel, asm, 1), (motor, asm, 3), (asm, test, 1), (test, wh, 1)]:
        r = a.req("POST", "/routes/", {"processId": proc["_id"], "load": load["_id"],
                                       "unload": unload["_id"], "quantity": q})
        assert r.status_code == 201, r.text
    return steel, motor, asm, test, wh


def _units_by_station(a):
    """station id → total units across all cards (the conservation quantity)."""
    m: dict = {}
    for c in a.req("GET", "/cards/").json():
        for sid, b in c["bins"].items():
            m[sid] = m.get(sid, 0) + b["count"]
    return m


def _move_all_to(a, station_id):
    for c in a.req("GET", "/cards/").json():
        for sid, b in list(c["bins"].items()):
            if sid != station_id and b["count"] > 0:
                r = a.req("POST", f"/cards/{c['_id']}/move",
                          {"fromStationId": sid, "toStationId": station_id, "quantity": b["count"]})
                assert r.status_code == 200, r.text


# ─── Conservation through merge → unmerge cycles ──────────────────────────────

def test_merge_unmerge_cycle_conserves_units(actor):
    a = actor(); bootstrap_admin(a)
    steel, motor, asm, _, wh = _setup_line(a)

    # Pull one finished unit from the warehouse → Steel×1 @ Steel, Motor×3 @ Motor.
    r = a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})
    assert r.status_code == 201, r.text
    baseline = _units_by_station(a)
    assert baseline == {steel["_id"]: 1, motor["_id"]: 3}

    for cycle in range(3):   # the user's repro was repeating this loop
        # Move precursors into the assembly and merge them.
        _move_all_to(a, asm["_id"])
        r = a.req("POST", f"/merge/{asm['_id']}")
        assert r.status_code == 201, r.text
        assert r.json()["assemblies"] == 1
        assert _units_by_station(a) == {asm["_id"]: 1}, f"cycle {cycle}"
        cards = a.req("GET", "/cards/").json()
        assert len(cards) == 1, f"cycle {cycle}: consumed precursors must be gone"

        # A second merge with nothing left must refuse, not mint another assembly.
        assert a.req("POST", f"/merge/{asm['_id']}").status_code == 400

        # Drag the assembly back → unmerge → exactly the original precursors.
        r = a.req("POST", f"/cards/{r.json()['createdCardId']}/unmerge",
                  {"stationId": asm["_id"], "quantity": 1})
        assert r.status_code == 200, r.text
        assert _units_by_station(a) == baseline, f"cycle {cycle}: units must be conserved"
        assert len(a.req("GET", "/cards/").json()) == 2, f"cycle {cycle}: no extra lots"


def test_unmerge_non_assembly_rejected(actor):
    """A precursor sitting at the merge station is not unmergeable — the lot
    board relies on this 400 to fall back to a plain move."""
    a = actor(); bootstrap_admin(a)
    _, motor, asm, _, wh = _setup_line(a)
    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})
    _move_all_to(a, asm["_id"])
    motor_card = next(c for c in a.req("GET", "/cards/").json()
                      if c["bins"].get(asm["_id"], {}).get("count") == 3)
    r = a.req("POST", f"/cards/{motor_card['_id']}/unmerge",
              {"stationId": asm["_id"], "quantity": 3})
    assert r.status_code == 400 and "not assembled" in r.json()["detail"]


def test_system_created_cards_get_lot_codes(actor):
    """Pull and merge mint cards with generated lot codes (e.g. "E4096A");
    splitting a lot apart (unmerge) keeps its identity — every piece inherits
    the assembly's code instead of being re-coded. Users may also define the
    code themselves when creating a lot."""
    a = actor(); bootstrap_admin(a)
    steel, _, asm, _, wh = _setup_line(a)

    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})
    codes = [c["lotNum"] for c in a.req("GET", "/cards/").json()]
    assert all(c and len(c) == 6 and c == c.upper() for c in codes)      # generated codes
    assert len(set(codes)) == 2                                          # distinct per card

    _move_all_to(a, asm["_id"])
    r = a.req("POST", f"/merge/{asm['_id']}")
    assembly = a.req("GET", f"/cards/{r.json()['createdCardId']}").json()
    assert assembly["lotNum"] and len(assembly["lotNum"]) == 6           # assembly gets a code

    a.req("POST", f"/cards/{assembly['_id']}/unmerge", {"stationId": asm["_id"], "quantity": 1})
    pieces = [c["lotNum"] for c in a.req("GET", "/cards/").json()]
    assert pieces == [assembly["lotNum"]] * 2                            # pieces keep the code

    # User-defined code on direct creation; blank → generated.
    tmpl = next(t for t in a.req("GET", "/lot-templates/").json()
                if t["startStationId"] == steel["_id"])
    r = a.req("POST", "/cards/", {"lotTemplateId": tmpl["_id"], "processId": tmpl["processId"],
                                  "lotNum": "RAW-042", "totalQuantity": 1,
                                  "bins": {steel["_id"]: {"count": 1}}})
    assert r.status_code == 201 and r.json()["lotNum"] == "RAW-042"
    r = a.req("POST", "/cards/", {"lotTemplateId": tmpl["_id"], "processId": tmpl["processId"],
                                  "totalQuantity": 1, "bins": {steel["_id"]: {"count": 1}}})
    assert r.status_code == 201 and len(r.json()["lotNum"]) == 6


def test_manual_merge_consumes_only_selected(actor):
    """Merging is deliberate: with cardIds only the worker-selected lot cards
    are consumed; without it (AUTO) any available precursors are used."""
    a = actor(); bootstrap_admin(a)
    steel, motor, asm, _, wh = _setup_line(a)
    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})   # two pulls → two
    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})   # cards per branch
    _move_all_to(a, asm["_id"])
    cards = a.req("GET", "/cards/").json()
    steels = [c for c in cards if c["bins"][asm["_id"]]["count"] == 1]
    motors = [c for c in cards if c["bins"][asm["_id"]]["count"] == 3]
    assert len(steels) == 2 and len(motors) == 2

    # Only a Steel card selected → the Motor branch has nothing → refuse.
    r = a.req("POST", f"/merge/{asm['_id']}", {"cardIds": [steels[0]["_id"]]})
    assert r.status_code == 400 and "selected" in r.json()["detail"]

    # One Steel + one Motor selected → exactly one assembly; the others untouched.
    r = a.req("POST", f"/merge/{asm['_id']}", {"cardIds": [steels[0]["_id"], motors[0]["_id"]]})
    assert r.status_code == 201 and r.json()["assemblies"] == 1
    after = {c["_id"]: c for c in a.req("GET", "/cards/").json()}
    assert steels[0]["_id"] not in after and motors[0]["_id"] not in after
    assert after[steels[1]["_id"]]["bins"][asm["_id"]]["count"] == 1
    assert after[motors[1]["_id"]]["bins"][asm["_id"]]["count"] == 3
    assert _units_by_station(a) == {asm["_id"]: 1 + 1 + 3}   # assembly + leftovers


def test_member_can_merge(actor):
    """Merging is the first step of working at a merge station, so operators
    (members) may trigger it — pull and unmerge remain admin-only."""
    a = actor(); bootstrap_admin(a)
    m = actor(); add_member(a, m, role="user")
    _, _, asm, _, wh = _setup_line(a)
    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})
    _move_all_to(a, asm["_id"])

    r = m.req("POST", f"/merge/{asm['_id']}")
    assert r.status_code == 201, r.text
    assert r.json()["assemblies"] == 1
    # …but the member still cannot pull or unmerge.
    assert m.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1}).status_code == 403
    assert m.req("POST", f"/cards/{r.json()['createdCardId']}/unmerge",
                 {"stationId": asm["_id"], "quantity": 1}).status_code == 403


# ─── Concurrency: duplicate requests must not duplicate lots ──────────────────

def _race(clients, fn):
    """Fire fn(client) from one thread per client, as simultaneously as possible."""
    barrier = threading.Barrier(len(clients))
    results, threads = [], []

    def run(c):
        barrier.wait()
        results.append(fn(c))

    for c in clients:
        t = threading.Thread(target=run, args=(c,))
        threads.append(t); t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_merge_creates_one_assembly(actor):
    """Two simultaneous merges (StrictMode double-fire) must yield exactly ONE
    assembly — before the per-station lock, both consumed the same precursors
    and each minted an assembly card."""
    a = actor(); bootstrap_admin(a)
    b = actor(); add_member(a, b, role="admin")
    _, _, asm, _, wh = _setup_line(a)
    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})
    _move_all_to(a, asm["_id"])

    codes = sorted(_race([a, b], lambda c: c.req("POST", f"/merge/{asm['_id']}").status_code))
    assert codes[0] == 201 and codes[1] in (400, 409), codes
    assert _units_by_station(a) == {asm["_id"]: 1}
    assert len(a.req("GET", "/cards/").json()) == 1


def test_concurrent_unmerge_dissolves_once(actor):
    """Two simultaneous unmerges of the same assembly must mint ONE set of
    precursors, not two."""
    a = actor(); bootstrap_admin(a)
    b = actor(); add_member(a, b, role="super_admin")
    steel, motor, asm, _, wh = _setup_line(a)
    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})
    _move_all_to(a, asm["_id"])
    card_id = a.req("POST", f"/merge/{asm['_id']}").json()["createdCardId"]

    codes = sorted(_race([a, b], lambda c: c.req(
        "POST", f"/cards/{card_id}/unmerge", {"stationId": asm["_id"], "quantity": 1}
    ).status_code))
    assert codes[0] == 200 and codes[1] in (400, 404), codes
    assert _units_by_station(a) == {steel["_id"]: 1, motor["_id"]: 3}
    assert len(a.req("GET", "/cards/").json()) == 2


def test_concurrent_move_applies_once(actor):
    """Two simultaneous identical moves of a full bin: only one may succeed —
    otherwise the same physical units land downstream twice."""
    a = actor(); bootstrap_admin(a)
    b = actor(); add_member(a, b, role="super_admin")   # move is super-admin only
    steel, _, asm, _, wh = _setup_line(a)
    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})
    steel_card = next(c for c in a.req("GET", "/cards/").json()
                      if c["bins"].get(steel["_id"], {}).get("count") == 1)

    codes = sorted(_race([a, b], lambda c: c.req(
        "POST", f"/cards/{steel_card['_id']}/move",
        {"fromStationId": steel["_id"], "toStationId": asm["_id"], "quantity": 1},
    ).status_code))
    assert codes == [200, 400], codes
    units = _units_by_station(a)
    assert units[asm["_id"]] == 1 and steel["_id"] not in units


# ─── A precursor is not this station's finished work ──────────────────────────

def test_status_does_not_survive_a_move(actor):
    """`status` is the work state at the station the lot was worked at, not a
    property of the lot. Carried along, a precursor finished upstream arrives at
    the merge still marked 'done' — and the Operator view greets the worker with
    a finished-work screen offering to move it downstream, for a lot nobody has
    touched there and an assembly that does not exist yet."""
    a = actor(); bootstrap_admin(a)
    steel, motor, asm, _, wh = _setup_line(a)
    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})

    card = next(c for c in a.req("GET", "/cards/").json() if c["bins"].get(steel["_id"]))
    assert a.req("PATCH", f"/cards/{card['_id']}/status", {"status": "done"}).json()["status"] == "done"

    moved = a.req("POST", f"/cards/{card['_id']}/advance",
                  {"fromStationId": steel["_id"], "toStationId": asm["_id"], "quantity": 1})
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "idle"
    assert a.req("GET", f"/cards/{card['_id']}").json()["status"] == "idle"


def test_precursor_cannot_be_advanced_out_of_a_merge_station(actor):
    """Pushing an unmerged precursor downstream books a motor as a finished
    e-bike and strands the parts it should have been merged with. The Operator
    view hides precursors from the picker, but /advance is also the public
    scan-to-advance API — a scanner pointed at a precursor label must not walk
    through the gate."""
    a = actor(); bootstrap_admin(a)
    steel, motor, asm, test, wh = _setup_line(a)
    proc = a.req("GET", "/processes/").json()[0]
    # Declaring a product at the merge is what makes it an assembly point rather
    # than a shared resource two lines happen to feed.
    a.req("POST", "/lot-templates/", {"name": "E-Bike", "processId": proc["_id"],
                                      "startStationId": asm["_id"]})
    a.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1})
    _move_all_to(a, asm["_id"])          # precursors staged at the merge, unmerged

    for c in a.req("GET", "/cards/").json():
        r = a.req("POST", f"/cards/{c['_id']}/advance",
                  {"fromStationId": asm["_id"], "toStationId": test["_id"], "quantity": 1})
        assert r.status_code == 409, f"precursor escaped the merge: {r.status_code} {r.text}"
        assert "merge" in r.json()["detail"].lower()

    # The assembly minted by the merge advances normally.
    assert a.req("POST", f"/merge/{asm['_id']}").status_code == 201
    assembly = next(c for c in a.req("GET", "/cards/").json() if c["bins"].get(asm["_id"]))
    r = a.req("POST", f"/cards/{assembly['_id']}/advance",
              {"fromStationId": asm["_id"], "toStationId": test["_id"], "quantity": 1})
    assert r.status_code == 200, r.text
    assert r.json()["bins"][test["_id"]]["count"] == 1


def test_a_shared_location_is_two_processes_not_one_merge(actor):
    """A paint booth two lines send work through is the case people reach for
    to argue "two feeds is not always a merge". It is not a counter-example —
    it is two *processes* sharing a physical location, and each of them has a
    single feed into it.

    Modelled that way (which is how alternative routing is modelled throughout),
    work passes through the booth on both lines and nothing is treated as a
    precursor. Modelled as one process with two feeds it would be a merge, and
    correctly so, because that is what a merge is.
    """
    a = actor(); bootstrap_admin(a)
    line_a = _mk_station(a, "Line A", 100)
    line_b = _mk_station(a, "Line B", 200)
    booth  = _mk_station(a, "Paint booth", 300)
    ship   = _mk_station(a, "Shipping", 400)

    made = {}
    for name, source in (("Paint A", line_a), ("Paint B", line_b)):
        proc = a.req("POST", "/processes/", {"name": name}).json()
        for load, unload in [(source, booth), (booth, ship)]:
            r = a.req("POST", "/routes/", {"processId": proc["_id"], "load": load["_id"],
                                           "unload": unload["_id"], "quantity": 1})
            assert r.status_code == 201, r.text
        tmpl = a.req("POST", "/lot-templates/", {"name": f"Panel {name[-1]}",
                                                 "processId": proc["_id"],
                                                 "startStationId": source["_id"]}).json()
        made[name] = (proc, tmpl, source)

    # Both lines run through the shared booth without either being held.
    for name, (proc, tmpl, source) in made.items():
        card = a.req("POST", "/cards/", {"lotTemplateId": tmpl["_id"], "processId": proc["_id"],
                                         "totalQuantity": 1,
                                         "bins": {source["_id"]: {"count": 1}}}).json()
        assert a.req("POST", f"/cards/{card['_id']}/advance",
                     {"fromStationId": source["_id"], "toStationId": booth["_id"],
                      "quantity": 1}).status_code == 200, name
        r = a.req("POST", f"/cards/{card['_id']}/advance",
                  {"fromStationId": booth["_id"], "toStationId": ship["_id"], "quantity": 1})
        assert r.status_code == 200, f"{name} blocked at the shared booth: {r.text}"
        assert r.json()["bins"][ship["_id"]]["count"] == 1


def test_two_feeds_inside_one_process_is_a_merge_even_before_the_product_exists(actor):
    """The hole the old escape hatch left: the gate used to require that a
    product template already start at the station, excused as protecting the
    shared booth. It protected nothing — process scoping does that — and it
    meant that on a line whose assembly had not been named yet, every precursor
    could walk straight out of the station meant to consume it."""
    a = actor(); bootstrap_admin(a)
    cell_a = _mk_station(a, "Cell A", 100)
    cell_b = _mk_station(a, "Cell B", 200)
    asm    = _mk_station(a, "Assembly", 300)
    test   = _mk_station(a, "Testing", 400)
    proc = a.req("POST", "/processes/", {"name": "One line"}).json()
    for load, unload in [(cell_a, asm), (cell_b, asm), (asm, test)]:
        a.req("POST", "/routes/", {"processId": proc["_id"], "load": load["_id"],
                                   "unload": unload["_id"], "quantity": 1})
    # Deliberately NO template starting at Assembly — the product is not named yet.
    motor = a.req("POST", "/lot-templates/", {"name": "Motor", "processId": proc["_id"],
                                              "startStationId": cell_a["_id"]}).json()
    a.req("POST", "/lot-templates/", {"name": "Frame", "processId": proc["_id"],
                                      "startStationId": cell_b["_id"]})
    card = a.req("POST", "/cards/", {"lotTemplateId": motor["_id"], "processId": proc["_id"],
                                     "totalQuantity": 1, "bins": {asm["_id"]: {"count": 1}}}).json()

    for endpoint in ("advance", "move"):
        r = a.req("POST", f"/cards/{card['_id']}/{endpoint}",
                  {"fromStationId": asm["_id"], "toStationId": test["_id"], "quantity": 1})
        assert r.status_code == 409, f"{endpoint} let an unmerged precursor through: {r.text}"
