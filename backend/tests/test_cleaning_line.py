"""The wash: a split branch that lands on a merge, exercised hard.

The battery example gained a cleaning-solution feed into Busbar Clean, which
makes that station a merge whose other feed is a branch of the Teardown split.
One number sits on that edge and could mean two things; the rule pinned here is
**the split owns the weight**: one pack yields 2 dirty busbars whatever happens
downstream, and the wash consumes ONE dirty piece (plus solution per its own
feed weight) per cleaned busbar. Every subsystem must read it the same way —
split, merge, pull, unmerge, unsplit — or material appears and vanishes at the
seam. The rest of this file is operator abuse: the stupid moves must bounce,
and whatever bounces must leave the line byte-for-byte unchanged.
"""

import json
from pathlib import Path

from tests.helpers import Actor, bootstrap_admin

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "battery-remanufacturing.json"


class Line:
    pass


def _import_line(a: Actor) -> Line:
    doc = json.loads(EXAMPLE.read_text())
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 200, r.text
    g = Line()
    g.st = {s["name"]: s["_id"] for s in a.req("GET", "/stations/").json()}
    g.tm = {t["name"]: t for t in a.req("GET", "/lot-templates/").json()}
    g.pr = {p["name"]: p["_id"] for p in a.req("GET", "/processes/").json()}
    return g


def _cards(a):
    return a.req("GET", "/cards/").json()


def _snapshot(a):
    """Canonical full state of every lot — the equality basis for 'a refused
    operation changed nothing'."""
    return sorted(
        (c["_id"], c["lotTemplateId"], c["lotNum"], c["totalQuantity"],
         json.dumps(c["bins"], sort_keys=True), c["status"])
        for c in _cards(a))


def _totals(a, g):
    out: dict = {}
    for c in _cards(a):
        n = sum(b["count"] for b in c["bins"].values())
        out[c["lotTemplateId"]] = out.get(c["lotTemplateId"], 0) + n
    return out


def _adv(a, cid, frm, to, qty):
    return a.req("POST", f"/cards/{cid}/advance",
                 {"fromStationId": frm, "toStationId": to, "quantity": qty})


def _order(a, g, line, ref):
    r = a.req("POST", "/orders", {"productTemplateId": g.tm[f"Reman {line}"]["_id"],
                                  "quantity": 1, "source": "manual", "externalRef": ref})
    assert r.status_code == 201, r.text
    return r.json()


def _find(a, g, tmpl_name, at=None, lot=None):
    for c in _cards(a):
        if c["lotTemplateId"] != g.tm[tmpl_name]["_id"]:
            continue
        if lot is not None and c["lotNum"] != lot:
            continue
        if at is not None and not c["bins"].get(at):
            continue
        return c
    return None


def _teardown(a, g, line, ref):
    pack = _find(a, g, f"{line} used pack", lot=ref)
    assert _adv(a, pack["_id"], g.st["Intake"], g.st["Teardown"], 1).status_code == 200
    assert _adv(a, pack["_id"], g.st["Teardown"], g.st["Module Test"], 1).status_code == 200


# ─── The weight keeps meaning yield ───────────────────────────────────────────

def test_the_pull_orders_solution_alongside_the_pack(actor):
    """One reman NMC needs 2 cleaned busbars; each wash takes 1 dirty + 1
    solution; one pack yields 2 dirty. So the pull seeds exactly ONE pack and
    TWO units of solution — reading the yield as consumption used to order
    double packs here."""
    a = actor(); bootstrap_admin(a)
    g = _import_line(a)
    _order(a, g, "NMC", "N1")
    assert _find(a, g, "NMC used pack", lot="N1")["bins"] == {g.st["Intake"]: {"count": 1}}
    sol = _find(a, g, "Cleaning solution (NMC)")
    assert sol and sol["bins"] == {g.st["Cleaning solution"]: {"count": 2}}, sol

    _order(a, g, "LFP", "L1")
    assert _find(a, g, "LFP used pack", lot="L1")["bins"] == {g.st["Intake"]: {"count": 1}}
    sol = _find(a, g, "Cleaning solution (LFP)")
    assert sol and sol["bins"] == {g.st["Cleaning solution"]: {"count": 1}}, sol


def test_teardown_yield_survives_the_wash_being_a_merge(actor):
    a = actor(); bootstrap_admin(a)
    g = _import_line(a)
    _order(a, g, "NMC", "N1")
    _teardown(a, g, "NMC", "N1")
    assert _find(a, g, "NMC module", lot="N1")["bins"][g.st["Module Test"]]["count"] == 4
    dirty = _find(a, g, "NMC dirty busbar", lot="N1")
    assert dirty["bins"][g.st["Busbar Clean"]]["count"] == 2, \
        "one pack yields two busbars, merge downstream or not"


def test_the_wash_washes_one_to_one(actor):
    """2 dirty + 2 solution → 2 cleaned busbars. Not one — the ×2 on the
    teardown branch is the split's yield, not the wash's appetite."""
    a = actor(); bootstrap_admin(a)
    g = _import_line(a)
    _order(a, g, "NMC", "N1")
    _teardown(a, g, "NMC", "N1")
    sol = _find(a, g, "Cleaning solution (NMC)")
    assert _adv(a, sol["_id"], g.st["Cleaning solution"], g.st["Busbar Clean"], 2).status_code == 200

    p = a.req("GET", f"/merge/{g.st['Busbar Clean']}?processId={g.pr['NMC']}").json()
    assert all(r["requiredPerAssembly"] == 1 for r in p["requirements"]), p["requirements"]
    assert p["assembliesPossible"] == 2

    m = a.req("POST", f"/merge/{g.st['Busbar Clean']}", {"processId": g.pr["NMC"]})
    assert m.status_code == 201, m.text
    cleaned = a.req("GET", f"/cards/{m.json()['createdCardId']}").json()
    assert cleaned["lotTemplateId"] == g.tm["NMC busbar"]["_id"]
    assert cleaned["bins"] == {g.st["Busbar Clean"]: {"count": 2}}
    # And the dirty pieces + solution are gone — consumed, not relabelled.
    assert _find(a, g, "NMC dirty busbar") is None
    assert _find(a, g, "Cleaning solution (NMC)") is None


def test_a_whole_order_runs_the_gauntlet(actor):
    """Order → pull → teardown → wash → reassembly → QA, per chemistry, with
    per-product conservation checked at every stage."""
    a = actor(); bootstrap_admin(a)
    g = _import_line(a)
    for line, mods_need, bus_need, sol_need in (("NMC", 3, 2, 2), ("LFP", 6, 1, 1)):
        _order(a, g, line, f"{line}-GO")
        _teardown(a, g, line, f"{line}-GO")
        sol = _find(a, g, f"Cleaning solution ({line})")
        assert _adv(a, sol["_id"], g.st["Cleaning solution"], g.st["Busbar Clean"], sol_need).status_code == 200
        m = a.req("POST", f"/merge/{g.st['Busbar Clean']}", {"processId": g.pr[line]})
        assert m.status_code == 201, m.text
        cleaned = a.req("GET", f"/cards/{m.json()['createdCardId']}").json()
        assert cleaned["bins"][g.st["Busbar Clean"]]["count"] == bus_need

        mods = _find(a, g, f"{line} module", lot=f"{line}-GO")
        assert _adv(a, mods["_id"], g.st["Module Test"], g.st["Reassembly"], mods_need).status_code == 200
        assert _adv(a, cleaned["_id"], g.st["Busbar Clean"], g.st["Reassembly"], bus_need).status_code == 200
        m = a.req("POST", f"/merge/{g.st['Reassembly']}", {"processId": g.pr[line]})
        assert m.status_code == 201, m.text
        made = a.req("GET", f"/cards/{m.json()['createdCardId']}").json()
        assert made["lotTemplateId"] == g.tm[f"Reman {line}"]["_id"]
        assert made["lotNum"] == f"{line}-GO"
        assert _adv(a, made["_id"], g.st["Reassembly"], g.st["QA"], 1).status_code == 200


# ─── Undo works through the seam ──────────────────────────────────────────────

def test_unmerging_a_wash_returns_dirty_and_solution(actor):
    a = actor(); bootstrap_admin(a)
    g = _import_line(a)
    _order(a, g, "NMC", "N1")
    _teardown(a, g, "NMC", "N1")
    sol = _find(a, g, "Cleaning solution (NMC)")
    _adv(a, sol["_id"], g.st["Cleaning solution"], g.st["Busbar Clean"], 2)
    m = a.req("POST", f"/merge/{g.st['Busbar Clean']}", {"processId": g.pr["NMC"]})
    cleaned_id = m.json()["createdCardId"]

    r = a.req("POST", f"/cards/{cleaned_id}/unmerge",
              {"stationId": g.st["Busbar Clean"], "quantity": 1})
    assert r.status_code == 200, r.text
    made = [a.req("GET", f"/cards/{cid}").json() for cid in r.json()["createdCardIds"]]
    by_tmpl = {c["lotTemplateId"]: c for c in made}
    dirty = by_tmpl[g.tm["NMC dirty busbar"]["_id"]]
    assert sum(b["count"] for b in dirty["bins"].values()) == 1, \
        "unmerge must mirror the wash's consumption (1 dirty), not the split's yield (2)"
    solution = by_tmpl[g.tm["Cleaning solution (NMC)"]["_id"]]
    assert sum(b["count"] for b in solution["bins"].values()) == 1


def test_unsplit_re_forms_the_pack_through_the_wash_branch(actor):
    """Dragging the modules back onto Teardown must consume the dirty-busbar
    twins in the yield ratio and re-form ONE pack — the 1:1-into-merges rule
    used to leave the ratio impossible to satisfy."""
    a = actor(); bootstrap_admin(a)
    g = _import_line(a)
    _order(a, g, "NMC", "N1")
    _teardown(a, g, "NMC", "N1")
    mods = _find(a, g, "NMC module", lot="N1")
    r = a.req("POST", f"/cards/{mods['_id']}/move",
              {"fromStationId": g.st["Module Test"], "toStationId": g.st["Teardown"], "quantity": 4})
    assert r.status_code == 200, r.text
    assert _find(a, g, "NMC module") is None
    assert _find(a, g, "NMC dirty busbar") is None, "the twins must go back together"
    reformed = [c for c in _cards(a) if c["bins"].get(g.st["Teardown"])]
    assert len(reformed) == 1 and reformed[0]["bins"][g.st["Teardown"]]["count"] == 1


# ─── Stupidity is refused, and refusal changes nothing ────────────────────────

def test_nothing_stupid_sticks(actor):
    """Every illegal gesture must bounce AND leave the whole line untouched —
    a 4xx that half-applied is worse than the mistake it refused."""
    a = actor(); bootstrap_admin(a)
    g = _import_line(a)
    _order(a, g, "NMC", "N1")
    _teardown(a, g, "NMC", "N1")
    sol = _find(a, g, "Cleaning solution (NMC)")
    _adv(a, sol["_id"], g.st["Cleaning solution"], g.st["Busbar Clean"], 2)
    dirty = _find(a, g, "NMC dirty busbar")
    mods = _find(a, g, "NMC module")

    before = _snapshot(a)
    attempts = [
        # dirty pieces may not skip the wash — forward, by advance or by drag
        ("POST", f"/cards/{dirty['_id']}/advance",
         {"fromStationId": g.st["Busbar Clean"], "toStationId": g.st["Reassembly"], "quantity": 1}),
        ("POST", f"/cards/{dirty['_id']}/move",
         {"fromStationId": g.st["Busbar Clean"], "toStationId": g.st["Reassembly"], "quantity": 1}),
        # solution is a precursor at the wash too
        ("POST", f"/cards/{sol['_id']}/advance",
         {"fromStationId": g.st["Busbar Clean"], "toStationId": g.st["Reassembly"], "quantity": 1}),
        # a partial un-split is refused, not rounded
        ("POST", f"/cards/{mods['_id']}/move",
         {"fromStationId": g.st["Module Test"], "toStationId": g.st["Teardown"], "quantity": 3}),
        # more units than exist
        ("POST", f"/cards/{mods['_id']}/advance",
         {"fromStationId": g.st["Module Test"], "toStationId": g.st["Reassembly"], "quantity": 99}),
        # advancing along a route that does not exist
        ("POST", f"/cards/{mods['_id']}/advance",
         {"fromStationId": g.st["Module Test"], "toStationId": g.st["QA"], "quantity": 1}),
        # units may never land on a partner's node
        ("POST", f"/cards/{mods['_id']}/move",
         {"fromStationId": g.st["Module Test"], "toStationId": g.st["Odoo"], "quantity": 1}),
        # unmerging something that is not an assembly here
        ("POST", f"/cards/{dirty['_id']}/unmerge",
         {"stationId": g.st["Busbar Clean"], "quantity": 1}),
        # merging with a selection that cannot make one assembly
        ("POST", f"/merge/{g.st['Busbar Clean']}", {"cardIds": [dirty["_id"]]}),
        # pulling a process that does not feed the station
        ("POST", f"/merge/{g.st['Busbar Clean']}/pull",
         {"quantity": 1, "processId": "00000000-0000-0000-0000-000000000000"}),
    ]
    for method, path, body in attempts:
        r = a.req(method, path, body)
        assert 400 <= r.status_code < 500, f"{path} was allowed: {r.text}"
        assert _snapshot(a) == before, f"{path} bounced but changed state"


def test_declaring_the_cleaned_product_on_the_dirty_branch_is_refused(actor):
    """The masquerade: pieces wearing the wash's own output would count as
    already washed. The declaration is refused at the route."""
    a = actor(); bootstrap_admin(a)
    g = _import_line(a)
    routes = a.req("GET", "/routes/").json()
    branch = next(r for r in routes if r["load"] == g.st["Teardown"]
                  and r["unload"] == g.st["Busbar Clean"] and r["processId"] == g.pr["NMC"])
    r = a.req("PUT", f"/routes/{branch['_id']}",
              {"outputTemplateId": g.tm["NMC busbar"]["_id"]})
    assert r.status_code == 400 and "masquerade" in r.text.lower() or "already finished" in r.text, r.text


def test_fragmented_lots_still_wash_and_assemble(actor):
    """Two packs torn down separately, everything advanced in dribs and drabs —
    fragmentation must never change what the material adds up to."""
    a = actor(); bootstrap_admin(a)
    g = _import_line(a)
    for ref in ("F1", "F2"):
        _order(a, g, "NMC", ref)
        _teardown(a, g, "NMC", ref)
    for c in [c for c in _cards(a) if c["lotTemplateId"] == g.tm["Cleaning solution (NMC)"]["_id"]]:
        n = c["bins"][g.st["Cleaning solution"]]["count"]
        for _ in range(n):   # one unit at a time
            assert _adv(a, c["_id"], g.st["Cleaning solution"], g.st["Busbar Clean"], 1).status_code == 200

    # Wash everything: 4 dirty + 4 solution → 4 cleaned.
    m = a.req("POST", f"/merge/{g.st['Busbar Clean']}", {"processId": g.pr["NMC"]})
    assert m.status_code == 201, m.text
    assert m.json()["assemblies"] == 4
    totals = _totals(a, g)
    assert totals.get(g.tm["NMC busbar"]["_id"]) == 4
    assert g.tm["NMC dirty busbar"]["_id"] not in totals
    assert g.tm["Cleaning solution (NMC)"]["_id"] not in totals
