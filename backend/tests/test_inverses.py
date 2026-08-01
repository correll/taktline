"""Every transformation, undone.

A split and an un-split, a merge and an unmerge, are inverses — that is the
whole claim the domain makes about them. So the sharpest test available is to
do one, undo it, and demand the floor look exactly as it did: same products,
same stations, same counts.

It is sharper than checking either half alone because the two halves are
written by different code, read the weights for opposite reasons, and have
disagreed before — a bare move sent four tubes back as four *bars*, and left
the offcut standing so the next advance minted a second one. A round trip
catches that in one assertion, without anyone having to think of the offcut.

Identity is deliberately NOT part of the comparison: undoing a split mints a
fresh lot rather than resurrecting the consumed row, and that is correct. What
must come back is the *material*.
"""

import json
from pathlib import Path

import pytest

from tests.helpers import Actor, bootstrap_admin

EXAMPLES = sorted((Path(__file__).resolve().parents[2] / "examples").glob("*.json"))

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _material(a: Actor):
    """What stands where, by product. The thing an inverse has to restore."""
    out: dict = {}
    for c in a.req("GET", "/cards/").json():
        for sid, b in c["bins"].items():
            k = (c["lotTemplateId"], sid)
            out[k] = out.get(k, 0) + b["count"]
    return out


def _stock(a: Actor):
    """How much of each product exists, anywhere on the floor."""
    out: dict = {}
    for c in a.req("GET", "/cards/").json():
        for b in c["bins"].values():
            out[c["lotTemplateId"]] = out.get(c["lotTemplateId"], 0) + b["count"]
    return out


def _units(a: Actor):
    out: dict = {}
    for c in a.req("GET", "/cards/").json():
        for sid, b in c["bins"].items():
            out[sid] = out.get(sid, 0) + b["count"]
    return out


def _station(a: Actor, name: str, **kw) -> str:
    return a.req("POST", "/stations/", {**STATION, "name": name, **kw}).json()["_id"]


# ── A split line I control, so the assertions can be exact ──────────────────

def _split_line(a: Actor, weights=(4, 1)):
    """One bar becomes four tubes and an offcut."""
    src, tube, off = _station(a, "Saw"), _station(a, "Tubes"), _station(a, "Offcuts")
    proc = a.req("POST", "/processes/", {"name": "Cutting"}).json()["_id"]
    # Weights are only legal once the graph actually branches, so both routes
    # are drawn first and weighted after — the same order the editor forces.
    made = []
    for target in (tube, off):
        r = a.req("POST", "/routes/", {"processId": proc, "load": src,
                                       "unload": target, "quantity": 1})
        assert r.status_code == 201, r.text
        made.append(r.json())
    for route, w in zip(made, weights):
        r = a.req("PUT", f"/routes/{route['_id']}", {**route, "quantity": w})
        assert r.status_code == 200, r.text
    bar = a.req("POST", "/lot-templates/", {"name": "Bar", "processId": proc,
                                            "startStationId": src}).json()["_id"]
    card = a.req("POST", "/cards/", {"lotTemplateId": bar, "processId": proc,
                                     "lotNum": "BAR-1", "totalQuantity": 3,
                                     "bins": {src: {"count": 3}}}).json()
    return proc, src, tube, off, bar, card


def test_a_split_undone_restores_the_material_exactly(actor):
    a = actor(); bootstrap_admin(a)
    proc, src, tube, off, bar, card = _split_line(a)
    before = _material(a)

    r = a.req("POST", f"/cards/{card['_id']}/advance",
              {"fromStationId": src, "toStationId": tube, "quantity": 1})
    assert r.status_code == 200, r.text
    assert _units(a) == {src: 2, tube: 4, off: 1}, "one bar should yield four tubes and an offcut"

    # Four tubes back down the branch re-form one bar — and take the offcut with
    # them, because the offcut is part of the same transformation.
    tubes = [c for c in a.req("GET", "/cards/").json() if tube in c["bins"]][0]
    r = a.req("POST", f"/cards/{tubes['_id']}/move",
              {"fromStationId": tube, "toStationId": src, "quantity": 4})
    assert r.status_code == 200, r.text
    assert _material(a) == before, "undoing the split did not restore the floor"


def test_a_partial_return_is_refused_rather_than_rounded(actor):
    """Three of four tubes do not re-form three quarters of a bar. Rounding
    here is how a line invents material."""
    a = actor(); bootstrap_admin(a)
    proc, src, tube, off, bar, card = _split_line(a)
    a.req("POST", f"/cards/{card['_id']}/advance",
          {"fromStationId": src, "toStationId": tube, "quantity": 1})
    mid = _material(a)

    tubes = [c for c in a.req("GET", "/cards/").json() if tube in c["bins"]][0]
    r = a.req("POST", f"/cards/{tubes['_id']}/move",
              {"fromStationId": tube, "toStationId": src, "quantity": 3})
    assert r.status_code == 400, r.text
    assert _material(a) == mid, "a refused return still changed the floor"


def test_a_return_of_units_the_lot_does_not_have_is_refused(actor):
    """Regression. `_unsplit_back` consumed the SIBLING branches' twins and
    minted a re-formed source unit without ever checking that the dragged lot
    was carrying anything — `_take_units` clamped at zero, so the card sat
    untouched while other people's material was transmuted. Found by the
    fuzzer's ledger, on two unrelated lines, from opposite ends of the graph."""
    a = actor(); bootstrap_admin(a)
    proc, src, tube, off, bar, card = _split_line(a)
    a.req("POST", f"/cards/{card['_id']}/advance",
          {"fromStationId": src, "toStationId": tube, "quantity": 1})
    before = _material(a)

    # `card` is the BAR lot: it stands at the saw and has nothing on the tube
    # branch. Dragging tubes it does not hold must not consume the offcut.
    r = a.req("POST", f"/cards/{card['_id']}/move",
              {"fromStationId": tube, "toStationId": src, "quantity": 4})
    assert r.status_code == 400, r.text
    assert _material(a) == before, "a lot with no pieces there still re-formed a unit"


# ── A merge line I control ──────────────────────────────────────────────────

def _merge_line(a: Actor, ratios=(3, 2), counts=(6, 4)):
    x, y, m = _station(a, "Frames"), _station(a, "Glass"), _station(a, "Glazing")
    proc = a.req("POST", "/processes/", {"name": "Windows"}).json()["_id"]
    made = []
    for load in (x, y):                   # both feeds first, then the ratios
        r = a.req("POST", "/routes/", {"processId": proc, "load": load,
                                       "unload": m, "quantity": 1})
        assert r.status_code == 201, r.text
        made.append(r.json())
    for route, w in zip(made, ratios):
        r = a.req("PUT", f"/routes/{route['_id']}", {**route, "quantity": w})
        assert r.status_code == 200, r.text
    tm = {}
    for name, station in (("Frame", x), ("Pane", y), ("Window", m)):
        tm[name] = a.req("POST", "/lot-templates/",
                         {"name": name, "processId": proc,
                          "startStationId": station}).json()["_id"]
    for name, station, n in (("Frame", x, counts[0]), ("Pane", y, counts[1])):
        a.req("POST", "/cards/", {"lotTemplateId": tm[name], "processId": proc,
                                  "lotNum": f"{name}-1", "totalQuantity": n,
                                  "bins": {station: {"count": n}}})
    return proc, x, y, m, tm


def _to_bench(a: Actor, bench: str):
    """Carry every lot to the merge station. Precursors are consumed where they
    stand, so a merge only ever sees what is on its own bench."""
    for c in a.req("GET", "/cards/").json():
        for sid in list(c["bins"]):
            if sid != bench:
                r = a.req("POST", f"/cards/{c['_id']}/advance",
                          {"fromStationId": sid, "toStationId": bench,
                           "quantity": c["bins"][sid]["count"]})
                assert r.status_code == 200, r.text


def test_a_merge_consumes_exactly_what_the_preview_promised(actor):
    """The preview is what the worker is shown before they press the button.
    If the merge then takes a different amount, the number on the screen was a
    guess — and the two are computed by different code paths, which is exactly
    how they came to disagree about which process they were in."""
    a = actor(); bootstrap_admin(a)
    proc, x, y, m, tm = _merge_line(a, counts=(7, 5))   # deliberate leftovers
    _to_bench(a, m)

    preview = a.req("GET", f"/merge/{m}").json()
    assert preview["isMergeStation"], preview
    assert preview["assembliesPossible"] == 2, preview
    per = {r["sourceStationId"]: r["requiredPerAssembly"] for r in preview["requirements"]}
    assert per == {x: 3, y: 2}, per

    res = a.req("POST", f"/merge/{m}", {})
    assert res.status_code in (200, 201), res.text
    made = res.json()["assemblies"]
    assert made == preview["assembliesPossible"]
    assert _material(a) == {
        (tm["Frame"], m): 7 - made * per[x],
        (tm["Pane"], m): 5 - made * per[y],
        (tm["Window"], m): made,
    }, "the merge did not consume what the preview promised"


def test_a_merge_undone_restores_the_material_exactly(actor):
    """Precursors come back one station upstream — where they were before they
    were carried to the bench — so the round trip that must close is
    advance-then-merge, undone."""
    a = actor(); bootstrap_admin(a)
    proc, x, y, m, tm = _merge_line(a)
    before = _material(a)                    # parts at their own stations
    _to_bench(a, m)

    made = a.req("POST", f"/merge/{m}", {}).json()["assemblies"]
    asm = [c for c in a.req("GET", "/cards/").json() if c["lotTemplateId"] == tm["Window"]][0]

    r = a.req("POST", f"/cards/{asm['_id']}/unmerge", {"stationId": m, "quantity": made})
    assert r.status_code == 200, r.text
    assert _material(a) == before, "dissolving the assembly did not give the parts back"


# ── The same round trips, over every line the repo ships ────────────────────

@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_every_merge_in_the_example_gives_its_parts_back(actor, example: Path):
    """Breadth over precision: the controlled line above pins the arithmetic,
    this one insists the property survives contact with real topologies —
    split-fed feeds, shared benches, two processes on one station, ratios of 8.

    The bench is stocked from the preview's OWN declaration of what counts as
    each feed's precursor, rather than by flooding the line from the queues.
    Flooding looked more realistic and tested less: it pushed material past the
    benches it was meant to reach and left whether anything could assemble to
    luck, which on all three lines came out as no.
    """
    a = actor(); bootstrap_admin(a)
    assert a.req("POST", "/map-io/import", json.loads(example.read_text())).status_code == 200

    stations = a.req("GET", "/stations/").json()
    partners = {s["_id"] for s in stations if s.get("integrationProvider")}
    names = {s["_id"]: s["name"] for s in stations}
    feeds: dict = {}
    for r in a.req("GET", "/routes/").json():
        if r["load"] in partners or r["unload"] in partners:
            continue
        feeds.setdefault((r["processId"], r["unload"]), set()).add(r["load"])
    merges = sorted({s for (_p, s), ins in feeds.items() if len(ins) >= 2})
    assert merges, f"{example.stem} has no merge to exercise"

    tried = 0
    for station in merges:
        pre = a.req("GET", f"/merge/{station}").json()
        if not pre.get("isMergeStation") or not pre.get("requirements"):
            continue

        # Stock the bench with two assemblies' worth of every declared feed.
        ok = True
        for req in pre["requirements"]:
            tmpl = (req.get("precursorTemplateIds") or [None])[0]
            if tmpl is None:
                ok = False
                break
            n = req["requiredPerAssembly"] * 2
            r = a.req("POST", "/cards/", {
                "lotTemplateId": tmpl, "processId": pre.get("processId"),
                "lotNum": f"RT-{station[:6]}", "totalQuantity": n,
                "bins": {station: {"count": n}}})
            ok = ok and r.status_code == 201
        if not ok:
            continue

        after = a.req("GET", f"/merge/{station}").json()
        if after.get("assembliesPossible", 0) < 1:
            continue

        before = _stock(a)
        res = a.req("POST", f"/merge/{station}", {})
        assert res.status_code in (200, 201), f"{example.stem} @ {names[station]}: {res.text}"
        made, asm_id = res.json()["assemblies"], res.json()["createdCardId"]
        tried += 1

        r = a.req("POST", f"/cards/{asm_id}/unmerge", {"stationId": station, "quantity": made})
        assert r.status_code == 200, f"{example.stem} @ {names[station]}: {r.text}"
        # By product, not by place: an unmerge deliberately rewinds the parts to
        # the stations they were carried from, so what must be identical is how
        # much of each product exists — the ratios the merge consumed at.
        assert _stock(a) == before, \
            f"{example.stem}: unmerging at {names[station]} did not give the parts back"

    assert tried, f"{example.stem}: no merge could be exercised — the test proved nothing"


def test_an_unsplit_takes_the_twin_off_the_branch_it_belongs_to(actor):
    """Regression, found by the fuzzer's ledger on the window line.

    A lot that straddles TWO branches of the same split was chosen to supply
    the twin for one branch and then had the units taken off the other — the
    consumption loop re-derived "which branch is this lot on?" from the card,
    and a card on two branches answers with whichever comes first.

    Units stayed conserved, which is why nothing else noticed: the offcut that
    should have been consumed was still on the shelf and a tube that should
    have survived was gone. Inventory in the wrong place is not a smaller
    problem than inventory in the wrong quantity — it is the one a stock count
    cannot find.
    """
    a = actor(); bootstrap_admin(a)
    proc, src, tube, off, bar, card = _split_line(a, weights=(1, 1))

    # Two bars go out, so each branch holds two pieces across two lots.
    for _ in range(2):
        r = a.req("POST", f"/cards/{card['_id']}/advance",
                  {"fromStationId": src, "toStationId": tube, "quantity": 1})
        assert r.status_code == 200, r.text

    # Give one lot a foot on BOTH branches — the shape that triggers it.
    straddler = next(c for c in a.req("GET", "/cards/").json() if tube in c["bins"])
    mv = a.req("POST", f"/cards/{straddler['_id']}/move",
               {"fromStationId": tube, "toStationId": off, "quantity": 1})
    assert mv.status_code in (200, 400), mv.text
    if mv.status_code == 400:
        pytest.skip("this line will not let a lot straddle two branches")

    before = _units(a)
    assert before.get(tube, 0) >= 1 and before.get(off, 0) >= 2, before

    mover = next(c for c in a.req("GET", "/cards/").json() if tube in c["bins"])
    r = a.req("POST", f"/cards/{mover['_id']}/move",
              {"fromStationId": tube, "toStationId": src, "quantity": 1})
    assert r.status_code == 200, r.text

    after = _units(a)
    # One unit re-formed at the saw, and EACH branch gave up exactly one.
    assert after.get(src, 0) == before.get(src, 0) + 1
    assert after.get(tube, 0) == before.get(tube, 0) - 1, \
        f"the tube branch did not pay its share: {before} -> {after}"
    assert after.get(off, 0) == before.get(off, 0) - 1, \
        f"the offcut branch did not pay its share: {before} -> {after}"
