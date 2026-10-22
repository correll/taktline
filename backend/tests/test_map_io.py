"""Export/import of the line definition — the roundtrip, and the walls.

The file is data, never instructions: strict schema with unknown keys refused,
every id re-minted server-side, enums allow-listed, hostile strings stored as
inert text, and the same graph rules as the editor. A file that fails any rule
leaves the old line untouched, because the import is one transaction.
"""

import json
from pathlib import Path

from tests.helpers import Actor, bootstrap_admin

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "battery-remanufacturing.json"

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _small_line(a: Actor):
    """Cut ─► Weld ═╦═► Tubes(×4, product)  with an Odoo demand link and a
    ShipStation handoff — enough shape to exercise every export field."""
    st = lambda n, **kw: a.req("POST", "/stations/", {**STATION, "name": n, **kw}).json()["_id"]
    cut = st("Cut", color="#1D4ED8", icon="Scissors")
    weld = st("Weld")
    tubes = st("Tubes")
    scrap = st("Scrap", isStorage=True)
    odoo = st("Odoo", integrationProvider="odoo", integrationRole="both")
    ship = st("ShipStation", integrationProvider="shipstation", integrationRole="sink")
    p = a.req("POST", "/processes/", {"name": "Cutting", "desiredTaktSec": 300}).json()["_id"]
    r = lambda l, u: a.req("POST", "/routes/", {"processId": p, "load": l, "unload": u,
                                                "quantity": 1}).json()["_id"]
    r1 = r(cut, weld)
    r2 = r(weld, tubes)
    r3 = r(weld, scrap)
    bar = a.req("POST", "/lot-templates/", {"name": "Bar", "processId": p, "startStationId": cut,
                                            "fields": [{"key": "heat", "label": "Heat no.",
                                                        "type": "text", "options": [],
                                                        "required": True}]}).json()["_id"]
    tube = a.req("POST", "/lot-templates/", {"name": "Tube", "processId": p,
                                             "startStationId": tubes}).json()["_id"]
    assert a.req("PUT", f"/routes/{r2}", {"quantity": 4, "outputTemplateId": tube}).status_code == 200
    assert a.req("POST", "/routes/", {"processId": p, "load": odoo, "unload": cut,
                                      "quantity": 1}).status_code == 201
    assert a.req("POST", "/routes/", {"processId": p, "load": tubes, "unload": ship,
                                      "quantity": 1}).status_code == 201
    return p


def test_export_import_roundtrip_preserves_the_line(actor):
    a = actor(); bootstrap_admin(a)
    _small_line(a)
    doc = a.req("GET", "/map-io/export").json()
    assert doc["kind"] == "taktline-map" and doc["version"] == 1

    b = actor(); bootstrap_admin(b, "Importer Inc")
    r = b.req("POST", "/map-io/import", doc)
    assert r.status_code == 200, r.text
    assert r.json() == {"stations": 6, "processes": 1, "templates": 2,
                        "routes": 5, "replaced": True}

    # The line survived by VALUE — names, weights, products, bindings, takt.
    stations = {s["name"]: s for s in b.req("GET", "/stations/").json()}
    assert stations["Cut"]["color"] == "#1D4ED8" and stations["Cut"]["icon"] == "Scissors"
    assert stations["Scrap"]["isStorage"] is True
    assert stations["Odoo"]["integrationProvider"] == "odoo"
    assert stations["ShipStation"]["integrationRole"] == "sink"
    proc = b.req("GET", "/processes/").json()[0]
    assert proc["name"] == "Cutting" and proc["desiredTaktSec"] == 300
    tmpls = {t["name"]: t for t in b.req("GET", "/lot-templates/").json()}
    assert tmpls["Bar"]["fields"][0]["key"] == "heat"
    routes = b.req("GET", "/routes/").json()
    weld_tubes = next(r for r in routes if r["load"] == stations["Weld"]["_id"]
                      and r["unload"] == stations["Tubes"]["_id"])
    assert weld_tubes["quantity"] == 4
    assert weld_tubes["outputTemplateId"] == tmpls["Tube"]["_id"]

    # …and every id was re-minted: nothing in B matches A's ids.
    a_ids = {s["_id"] for s in a.req("GET", "/stations/").json()}
    assert not (a_ids & {s["_id"] for s in stations.values()})


def test_import_replaces_the_previous_line(actor):
    a = actor(); bootstrap_admin(a)
    _small_line(a)
    doc = a.req("GET", "/map-io/export").json()
    # Build junk on top, then import the export back: only the file's line remains.
    a.req("POST", "/stations/", {**STATION, "name": "Doomed"})
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 200, r.text
    names = {s["name"] for s in a.req("GET", "/stations/").json()}
    assert "Doomed" not in names and "Cut" in names
    assert a.req("GET", "/cards/").json() == []          # lots are state, not map


def test_a_failing_file_leaves_the_old_line_untouched(actor):
    a = actor(); bootstrap_admin(a)
    _small_line(a)
    doc = a.req("GET", "/map-io/export").json()
    doc["routes"].append({"process": doc["processes"][0]["ref"],
                          "load": "no-such-ref", "unload": doc["stations"][0]["ref"],
                          "quantity": 1})
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 422, r.text
    # transaction rolled back: the original line is fully intact
    assert {s["name"] for s in a.req("GET", "/stations/").json()} >= {"Cut", "Weld", "Tubes"}


def test_unknown_keys_are_refused_outright(actor):
    """extra='forbid' is the first wall: there is no field an attacker can add
    that the importer will even parse."""
    a = actor(); bootstrap_admin(a)
    doc = {"kind": "taktline-map", "version": 1, "stations": [],
           "processes": [], "templates": [], "routes": [],
           "__proto__": {"evil": True}}
    assert a.req("POST", "/map-io/import", doc).status_code == 422
    doc2 = {"kind": "taktline-map", "version": 1,
            "stations": [{"ref": "s1", "name": "X", "onLoad": "alert(1)"}],
            "processes": [], "templates": [], "routes": []}
    assert a.req("POST", "/map-io/import", doc2).status_code == 422


def test_hostile_strings_are_stored_as_inert_text(actor):
    """Names are data. The XSS/SQL strings go in, come back verbatim as JSON,
    and nothing anywhere interprets them — same contract as every endpoint."""
    a = actor(); bootstrap_admin(a)
    payload = "<script>alert(1)</script>'; DROP TABLE stations;--"
    doc = {"kind": "taktline-map", "version": 1,
           "stations": [{"ref": "s1", "name": payload}],
           "processes": [{"ref": "p1", "name": payload}],
           "templates": [], "routes": []}
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 200, r.text
    assert [s["name"] for s in a.req("GET", "/stations/").json()] == [payload]
    assert a.req("GET", "/stations/").headers["content-type"].startswith("application/json")


def test_the_graph_rules_hold_for_files_too(actor):
    a = actor(); bootstrap_admin(a)
    base = {"kind": "taktline-map", "version": 1, "templates": []}

    # a cycle
    doc = {**base,
           "stations": [{"ref": "s1", "name": "A"}, {"ref": "s2", "name": "B"}],
           "processes": [{"ref": "p1", "name": "P"}],
           "routes": [{"process": "p1", "load": "s1", "unload": "s2"},
                      {"process": "p1", "load": "s2", "unload": "s1"}]}
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 422 and "cycle" in r.text, r.text

    # a weight where nothing branches
    doc = {**base,
           "stations": [{"ref": "s1", "name": "A"}, {"ref": "s2", "name": "B"}],
           "processes": [{"ref": "p1", "name": "P"}],
           "routes": [{"process": "p1", "load": "s1", "unload": "s2", "quantity": 4}]}
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 422 and "branch" in r.text, r.text

    # a shipper as a source
    doc = {**base, "processes": [], "routes": [],
           "stations": [{"ref": "s1", "name": "SS",
                         "integrationProvider": "shipstation", "integrationRole": "source"}]}
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 422 and "cannot be bound" in r.text, r.text

    # duplicate refs
    doc = {**base, "processes": [], "routes": [],
           "stations": [{"ref": "s1", "name": "A"}, {"ref": "s1", "name": "B"}]}
    assert a.req("POST", "/map-io/import", doc).status_code == 422


def test_import_is_super_admin_only(actor):
    from tests.helpers import add_member
    su = actor(); bootstrap_admin(su)
    member = actor(); add_member(su, member, "admin")
    doc = {"kind": "taktline-map", "version": 1, "stations": [], "processes": [],
           "templates": [], "routes": []}
    assert member.req("POST", "/map-io/import", doc).status_code == 403
    assert member.req("GET", "/map-io/export").status_code == 403


# ─── The shipped example must stay importable and runnable ───────────────────

def test_the_battery_example_imports_and_runs(actor):
    """The repo ships examples/battery-remanufacturing.json. This test keeps it
    honest: it must import cleanly and the imported line must actually run —
    an order pulls a pack, the teardown fans out with the NMC weights, and the
    merge assembles."""
    a = actor(); bootstrap_admin(a)
    doc = json.loads(EXAMPLE.read_text())
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 200, r.text

    stations = {s["name"]: s["_id"] for s in a.req("GET", "/stations/").json()}
    tmpls = {t["name"]: t for t in a.req("GET", "/lot-templates/").json()}
    reman = tmpls["Reman NMC"]

    o = a.req("POST", "/orders", {"productTemplateId": reman["_id"], "quantity": 1,
                                  "source": "manual", "externalRef": "EX-1"})
    assert o.status_code == 201, o.text
    pack = next(c for c in a.req("GET", "/cards/").json()
                if c["orderId"] == o.json()["id"]
                and c["lotTemplateId"] == tmpls["NMC used pack"]["_id"])
    assert pack["bins"] == {stations["Intake"]: {"count": 1}}

    adv = lambda cid, f, t, q: a.req("POST", f"/cards/{cid}/advance",
                                     {"fromStationId": f, "toStationId": t, "quantity": q})
    assert adv(pack["_id"], stations["Intake"], stations["Teardown"], 1).status_code == 200
    assert adv(pack["_id"], stations["Teardown"], stations["Module Test"], 1).status_code == 200
    cards = a.req("GET", "/cards/").json()
    mods = next(c for c in cards if c["lotTemplateId"] == tmpls["NMC module"]["_id"])
    dirty = next(c for c in cards if c["lotTemplateId"] == tmpls["NMC dirty busbar"]["_id"])
    assert mods["bins"][stations["Module Test"]]["count"] == 4
    assert dirty["bins"][stations["Busbar Clean"]]["count"] == 2, \
        "the teardown's yield must survive the wash becoming a merge"

    # The wash: the pull seeded one solution unit per busbar; clean them.
    sol = next(c for c in cards if c["lotTemplateId"] == tmpls["Cleaning solution (NMC)"]["_id"])
    assert sol["bins"][stations["Cleaning solution"]]["count"] == 2
    assert adv(sol["_id"], stations["Cleaning solution"], stations["Busbar Clean"], 2).status_code == 200
    w = a.req("POST", f"/merge/{stations['Busbar Clean']}", {"processId": tmpls["NMC busbar"]["processId"]})
    assert w.status_code == 201, w.text
    cleaned = a.req("GET", f"/cards/{w.json()['createdCardId']}").json()
    assert cleaned["lotTemplateId"] == tmpls["NMC busbar"]["_id"]
    assert cleaned["bins"][stations["Busbar Clean"]]["count"] == 2, \
        "2 dirty + 2 solution wash into 2 cleaned busbars, not 1"

    assert adv(mods["_id"], stations["Module Test"], stations["Reassembly"], 3).status_code == 200
    assert adv(cleaned["_id"], stations["Busbar Clean"], stations["Reassembly"], 2).status_code == 200
    picks = [c["_id"] for c in a.req("GET", "/cards/").json()
             if c["bins"].get(stations["Reassembly"])]
    m = a.req("POST", f"/merge/{stations['Reassembly']}", {"cardIds": picks})
    assert m.status_code == 201, m.text
    made = a.req("GET", f"/cards/{m.json()['createdCardId']}").json()
    assert made["lotTemplateId"] == reman["_id"]


def test_a_high_mix_line_with_many_routes_imports(actor):
    """Fifty product variants of twelve steps each is 600 routes: an ordinary
    high-mix line, and over the old cap of 500. Each variant is its own process
    over shared stations, the way either/or routing is modelled."""
    a = actor(); bootstrap_admin(a)
    n_st, n_proc, steps = 24, 50, 12
    stations = [{"ref": f"s{i}", "name": f"S{i}"} for i in range(n_st)]
    processes = [{"ref": f"p{k}", "name": f"Variant {k}"} for k in range(n_proc)]
    routes = []
    for k in range(n_proc):
        path = sorted({(k * 7 + j * 5) % n_st for j in range(40)})[:steps]
        routes += [{"process": f"p{k}", "load": f"s{x}", "unload": f"s{y}"}
                   for x, y in zip(path, path[1:])]
    assert len(routes) > 500
    doc = {"kind": "taktline-map", "version": 1, "stations": stations,
           "processes": processes, "templates": [], "routes": routes}
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 200, r.text[:300]
    assert len(a.req("GET", "/routes/").json()) == len(routes)
