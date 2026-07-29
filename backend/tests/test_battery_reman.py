"""Two battery chemistries remanufactured over one shop floor.

The audit scenario: every station is shared, every judgement must therefore be
process-scoped, and the ERP loop runs end to end — demand in through Odoo,
finished packs out through ShipStation.

                     NMC process (×4 modules, ×2 busbars per pack)
                     LFP process (×6 modules, ×1 busbar per pack)

    [Odoo] ┄demand┄► Reassembly            (the reman pack is MADE here)
    Intake ─► Teardown ═╦═► Module Test ──► Reassembly ─► QA ─► Warehouse
                        ╚═► Busbar Clean ─► Reassembly       └┄handoff┄► [ShipStation]

Both processes draw this same shape with different weights, so the shared
stations carry two value streams at once. What this file pins that nothing else
does:

- teardown weights are the card's own process's, not the bench's other tenant's
- two merges at one bench are BOTH reachable (selected cards name the process;
  AUTO prefers a line that can actually assemble) — the resolution bug found by
  this audit made the tie-loser's merge impossible to run
- un-splitting consumes the lot's own twins by lot code, not a stranger's
- lots can never land on a partner's node, from any endpoint — the guard found
  by this audit; and a handoff link is not a split branch
- a partial handoff reports progress with this event's units, then completes
- line cycle time comes out of the real API, and sessions auto-close
"""

from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}

ATTRS = {"customer": "Grid Storage GmbH", "dueDate": "2026-09-01"}


def _st(a, name, **kw):
    r = a.req("POST", "/stations/", {**STATION, "name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _route(a, proc, load, unload):
    r = a.req("POST", "/routes/", {"processId": proc, "load": load,
                                   "unload": unload, "quantity": 1})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _set(a, route_id, **body):
    r = a.req("PUT", f"/routes/{route_id}", body)
    assert r.status_code == 200, r.text


def _tmpl(a, name, proc, station):
    r = a.req("POST", "/lot-templates/", {"name": name, "processId": proc,
                                          "startStationId": station})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _cards(a):
    return a.req("GET", "/cards/").json()


def _at(a, station, proc=None):
    return sum(c["bins"].get(station, {}).get("count", 0) for c in _cards(a)
               if proc is None or c["processId"] == proc)


def _advance(a, card_id, frm, to, qty):
    r = a.req("POST", f"/cards/{card_id}/advance",
              {"fromStationId": frm, "toStationId": to, "quantity": qty})
    assert r.status_code == 200, r.text
    return r.json()


class Rig:
    """The whole floor, both chemistries."""


def _build(a: Actor) -> Rig:
    g = Rig()
    # 24/7 plant: line-cycle anchors then sit between real departures, not at a
    # 9am opening three days ago.
    a.req("PUT", "/global-settings/", {"workHours": [[15] * 24 for _ in range(7)]})

    g.intake  = _st(a, "Intake")
    g.tear    = _st(a, "Teardown")
    g.modtest = _st(a, "Module Test")
    g.busbar  = _st(a, "Busbar Clean")
    g.reasm   = _st(a, "Reassembly")
    g.qa      = _st(a, "QA")
    g.wh      = _st(a, "Warehouse", isStorage=True)
    g.odoo    = _st(a, "Odoo", integrationProvider="odoo", integrationRole="both")
    g.ship    = _st(a, "ShipStation", integrationProvider="shipstation", integrationRole="sink")

    def build_process(name, mod_yield, bus_yield, mod_need, bus_need):
        r = a.req("POST", "/processes/", {"name": name, "desiredTaktSec": 1800})
        assert r.status_code == 201, r.text
        p = r.json()["_id"]
        routes = {}
        routes["in_tear"]  = _route(a, p, g.intake, g.tear)
        routes["tear_mod"] = _route(a, p, g.tear, g.modtest)
        routes["tear_bus"] = _route(a, p, g.tear, g.busbar)
        routes["mod_re"]   = _route(a, p, g.modtest, g.reasm)
        routes["bus_re"]   = _route(a, p, g.busbar, g.reasm)
        routes["re_qa"]    = _route(a, p, g.reasm, g.qa)

        pack   = _tmpl(a, f"{name} used pack", p, g.intake)
        module = _tmpl(a, f"{name} module", p, g.modtest)
        busbar = _tmpl(a, f"{name} busbar", p, g.busbar)
        reman  = _tmpl(a, f"Reman {name}", p, g.reasm)

        # Weights & declared branch products — only legal once the shape exists.
        _set(a, routes["tear_mod"], quantity=mod_yield, outputTemplateId=module)
        _set(a, routes["tear_bus"], quantity=bus_yield, outputTemplateId=busbar)
        _set(a, routes["mod_re"], quantity=mod_need)
        _set(a, routes["bus_re"], quantity=bus_need)

        # Boundary links, drawn after products exist (the placement rule wants
        # the demand link on the location where the ordered product is made).
        _route(a, p, g.odoo, g.reasm)
        _route(a, p, g.qa, g.ship)
        return {"proc": p, "pack": pack, "module": module, "busbar": busbar,
                "reman": reman, "routes": routes}

    g.nmc = build_process("NMC", mod_yield=4, bus_yield=2, mod_need=3, bus_need=2)
    g.lfp = build_process("LFP", mod_yield=6, bus_yield=1, mod_need=6, bus_need=1)
    return g


def _order(a, g, line, qty, ref, source="odoo"):
    r = a.req("POST", "/orders", {"productTemplateId": line["reman"], "quantity": qty,
                                  "source": source, "externalRef": ref,
                                  "lotCode": ref, "attributes": ATTRS})
    assert r.status_code == 201, r.text
    return r.json()


def _teardown(a, g, line, ref):
    """Advance the pack minted for `ref` through the teardown; return the pieces."""
    pack = next(c for c in _cards(a)
                if c["lotTemplateId"] == line["pack"] and c["lotNum"] == ref)
    n = pack["bins"][g.intake]["count"]
    _advance(a, pack["_id"], g.intake, g.tear, n)
    _advance(a, pack["_id"], g.tear, g.modtest, n)
    mods = next(c for c in _cards(a)
                if c["lotTemplateId"] == line["module"] and c["lotNum"] == ref)
    bus = next(c for c in _cards(a)
               if c["lotTemplateId"] == line["busbar"] and c["lotNum"] == ref)
    return mods, bus


# ─── The desired takt is a process property ──────────────────────────────────

def test_desired_takt_roundtrips_and_updates(actor):
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    procs = {p["_id"]: p for p in a.req("GET", "/processes/").json()}
    assert procs[g.nmc["proc"]]["desiredTaktSec"] == 1800
    r = a.req("PUT", f"/processes/{g.nmc['proc']}", {"desiredTaktSec": 900})
    assert r.status_code == 200 and r.json()["desiredTaktSec"] == 900
    # and absence stays absent — nothing invents a target
    r = a.req("POST", "/processes/", {"name": "No takt"})
    assert r.json()["desiredTaktSec"] is None


# ─── Demand pulls through the diamond, per line ──────────────────────────────

def test_an_order_pulls_one_pack_through_the_diamond(actor):
    """One reman NMC needs 3 modules (a pack yields 4) and 2 busbars (a pack
    yields 2): the diamond recombines to exactly one used pack at Intake."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    o = _order(a, g, g.nmc, 1, "NMC-1")
    cards = [c for c in _cards(a) if c["orderId"] == o["id"]]
    assert len(cards) == 1, cards
    c = cards[0]
    assert c["lotTemplateId"] == g.nmc["pack"], "the pull minted the wrong product"
    assert c["bins"] == {g.intake: {"count": 1}}, c["bins"]
    assert c["lotNum"] == "NMC-1" and c["fields"] == ATTRS
    assert _at(a, g.intake, g.lfp["proc"]) == 0, "the other chemistry was seeded"


def test_demand_scales_by_ceiling_per_line(actor):
    """Two reman LFP need 12 modules; a pack yields 6 → two packs. The same
    order on NMC would need 6 modules of 4-per-pack → also two, by ceiling."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    o = _order(a, g, g.lfp, 2, "LFP-2")
    packs = [c for c in _cards(a) if c["orderId"] == o["id"]]
    assert len(packs) == 1 and packs[0]["bins"][g.intake]["count"] == 2, packs


# ─── Teardown uses the card's own process's weights ──────────────────────────

def test_teardown_uses_its_own_processes_weights(actor):
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    _order(a, g, g.nmc, 1, "NMC-1")
    _order(a, g, g.lfp, 1, "LFP-1")

    n_mods, n_bus = _teardown(a, g, g.nmc, "NMC-1")
    assert n_mods["bins"][g.modtest]["count"] == 4, "NMC yields 4 modules"
    assert n_bus["bins"][g.busbar]["count"] == 2, "NMC yields 2 busbars"

    l_mods, l_bus = _teardown(a, g, g.lfp, "LFP-1")
    assert l_mods["bins"][g.modtest]["count"] == 6, "LFP yields 6 — not NMC's 4"
    assert l_bus["bins"][g.busbar]["count"] == 1

    # Context rode along on every piece, and conservation holds per line.
    for piece in (n_mods, n_bus, l_mods, l_bus):
        fresh = a.req("GET", f"/cards/{piece['_id']}").json()
        assert fresh["fields"] == ATTRS and fresh["orderId"] is not None
    assert _at(a, g.modtest, g.nmc["proc"]) == 4 and _at(a, g.busbar, g.nmc["proc"]) == 2
    assert _at(a, g.modtest, g.lfp["proc"]) == 6 and _at(a, g.busbar, g.lfp["proc"]) == 1


# ─── The spares route is an escape path, not a second disassembly ────────────

def test_set_aside_to_spares_relocates_and_never_mints(actor):
    """A spares shelf fed from Module Test gives that station two outgoing
    routes in BOTH processes — including LFP, whose teardown yield (6) exactly
    matches its merge's take (6), so no structural surplus ever needs the
    route. It exists as the escape path for a failed or extra module, and it is
    safe because a module card wears the branch's own product: setting one
    aside is a relocation, not a re-triggered split — nothing is minted on the
    other branch, nothing is relabelled."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    spares = _st(a, "Spare Modules", isStorage=True)
    for line in (g.nmc, g.lfp):
        _route(a, line["proc"], g.modtest, spares)

    # LFP: the balanced line. One module fails test and goes to the shelf.
    _order(a, g, g.lfp, 1, "LFP-1")
    mods, _ = _teardown(a, g, g.lfp, "LFP-1")
    before = {c["_id"] for c in _cards(a)}
    _advance(a, mods["_id"], g.modtest, spares, 1)

    assert {c["_id"] for c in _cards(a)} == before, "the set-aside minted cards"
    fresh = a.req("GET", f"/cards/{mods['_id']}").json()
    assert fresh["lotTemplateId"] == g.lfp["module"], "the piece was relabelled"
    assert fresh["bins"] == {g.modtest: {"count": 5}, spares: {"count": 1}}, fresh["bins"]

    # NMC: the line with a real surplus — 4 arrive, the merge takes 3. The
    # fourth goes to the shelf and the merge still assembles.
    _order(a, g, g.nmc, 1, "NMC-1")
    n_mods, n_bus = _teardown(a, g, g.nmc, "NMC-1")
    _advance(a, n_mods["_id"], g.modtest, spares, 1)
    _advance(a, n_mods["_id"], g.modtest, g.reasm, 3)
    _advance(a, n_bus["_id"], g.busbar, g.reasm, 2)
    r = a.req("POST", f"/merge/{g.reasm}", {"cardIds": [n_mods["_id"], n_bus["_id"]]})
    assert r.status_code == 201, r.text
    assert _at(a, spares) == 2                      # one of each chemistry


# ─── The merge preview describes ONE line, and only material feeds ───────────

def test_preview_scopes_to_one_process_and_ignores_the_erp_link(actor):
    """Reassembly is fed by both chemistries AND by Odoo's demand link. The
    preview must describe one line's recipe — two requirements, not four, and
    never one for the ERP, which hands this station nothing. It also names the
    precursor products per branch, so a client never has to guess them."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    _stage_both_lines(a, g)

    p = a.req("GET", f"/merge/{g.reasm}").json()
    assert p["isMergeStation"] is True
    assert len(p["requirements"]) == 2, "the preview merged two lines into one recipe"
    assert {r["sourceStationId"] for r in p["requirements"]} == {g.modtest, g.busbar}
    assert g.odoo not in {r["sourceStationId"] for r in p["requirements"]}
    assert {pr["name"] for pr in p["processes"]} == {"NMC", "LFP"}, p["processes"]

    # Each line is reachable, with its own weights and its own precursors.
    for line, name, mods, bus in ((g.nmc, "NMC", 3, 2), (g.lfp, "LFP", 6, 1)):
        q = a.req("GET", f"/merge/{g.reasm}?processId={line['proc']}").json()
        assert q["processId"] == line["proc"]
        assert q["assemblyTemplateName"] == f"Reman {name}"
        by_src = {r["sourceStationId"]: r for r in q["requirements"]}
        assert by_src[g.modtest]["requiredPerAssembly"] == mods
        assert by_src[g.busbar]["requiredPerAssembly"] == bus
        assert by_src[g.modtest]["precursorTemplateIds"] == [line["module"]]
        assert by_src[g.busbar]["precursorTemplateIds"] == [line["busbar"]]
        assert q["assembliesPossible"] == 1


def test_the_proposal_is_exactly_what_an_unguided_merge_consumes(actor):
    """The modal opens on the preview's proposed cards and merges THOSE, so the
    proposal has to be the same merge the station would have done by itself —
    same assemblies, same cards consumed. Otherwise 'just press MERGE' quietly
    means something else than the AUTO button it replaced."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    _stage_both_lines(a, g)

    p = a.req("GET", f"/merge/{g.reasm}?processId={g.nmc['proc']}").json()
    proposed = [cid for r in p["requirements"] for cid in r["proposedCardIds"]]
    assert proposed, "the preview proposed nothing while an assembly was possible"

    r = a.req("POST", f"/merge/{g.reasm}", {"cardIds": proposed})
    assert r.status_code == 201, r.text
    assert r.json()["assemblies"] == p["assembliesPossible"]
    made = a.req("GET", f"/cards/{r.json()['createdCardId']}").json()
    assert made["lotTemplateId"] == g.nmc["reman"]

    # With nothing left to assemble the proposal is empty, not stale.
    after = a.req("GET", f"/merge/{g.reasm}?processId={g.nmc['proc']}").json()
    assert after["assembliesPossible"] == 0
    assert all(rq["proposedCardIds"] == [] for rq in after["requirements"])


# ─── Pulling at a shared station names its process ───────────────────────────

def test_pull_at_a_shared_station_honours_the_named_process(actor):
    """QA is fed by both chemistries, one route each, so a bare pull falls to
    the deterministic tie-break. Naming the process pulls THAT line — and a
    process that does not feed the station is refused, never substituted."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)

    r = a.req("POST", f"/merge/{g.qa}/pull", {"quantity": 1, "processId": g.lfp["proc"]})
    assert r.status_code == 201, r.text
    packs = [c for c in _cards(a) if c["bins"].get(g.intake)]
    assert len(packs) == 1 and packs[0]["lotTemplateId"] == g.lfp["pack"], \
        "the pull walked the wrong chemistry"

    stranger = a.req("POST", "/processes/", {"name": "Stranger"}).json()["_id"]
    r = a.req("POST", f"/merge/{g.qa}/pull", {"quantity": 1, "processId": stranger})
    assert r.status_code == 400 and "does not feed" in r.json()["detail"], r.text


# ─── Two merges, one bench — both reachable ──────────────────────────────────

def _stage_both_lines(a, g):
    """Both chemistries torn down and staged at the shared Reassembly bench."""
    _order(a, g, g.nmc, 1, "NMC-1")
    _order(a, g, g.lfp, 1, "LFP-1")
    for line, ref in ((g.nmc, "NMC-1"), (g.lfp, "LFP-1")):
        mods, bus = _teardown(a, g, line, ref)
        need_m = 3 if line is g.nmc else 6
        _advance(a, mods["_id"], g.modtest, g.reasm, need_m)
        _advance(a, bus["_id"], g.busbar, g.reasm, bus["bins"][g.busbar]["count"])


def test_selected_cards_name_the_process_and_both_merges_run(actor):
    """The resolution bug this audit found: with two merges tied at one bench,
    the deterministic tie-break won every call, so the losing line's merge was
    unreachable — its worker's selection 400'd and AUTO ate the winner's parts.
    Selected cards now say which line is being assembled."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    _stage_both_lines(a, g)

    for line, ref in ((g.nmc, "NMC-1"), (g.lfp, "LFP-1")):
        picks = [c["_id"] for c in _cards(a)
                 if c["processId"] == line["proc"] and c["bins"].get(g.reasm)]
        r = a.req("POST", f"/merge/{g.reasm}", {"cardIds": picks})
        assert r.status_code == 201, f"{ref}: {r.text}"
        made = a.req("GET", f"/cards/{r.json()['createdCardId']}").json()
        assert made["lotTemplateId"] == line["reman"]
        assert made["lotNum"] == ref and made["fields"] == ATTRS

    # Nothing bled between the lines: each bench-side surplus is its own.
    assert _at(a, g.reasm, g.nmc["proc"]) == 1     # the reman NMC pack
    assert _at(a, g.reasm, g.lfp["proc"]) == 1     # the reman LFP pack
    assert _at(a, g.modtest, g.nmc["proc"]) == 1   # NMC's surplus module
    assert _at(a, g.modtest, g.lfp["proc"]) == 0   # LFP had none


def test_a_selection_spanning_two_processes_is_refused(actor):
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    _stage_both_lines(a, g)
    picks = [c["_id"] for c in _cards(a) if c["bins"].get(g.reasm)]
    r = a.req("POST", f"/merge/{g.reasm}", {"cardIds": picks})
    assert r.status_code == 400 and "span two processes" in r.json()["detail"], r.text


def test_auto_merge_picks_the_line_that_can_actually_assemble(actor):
    """AUTO at a shared bench must not 400 on the tie-winner's empty feeds
    while the other line stands ready."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    # Stage ONLY the LFP line.
    _order(a, g, g.lfp, 1, "LFP-1")
    mods, bus = _teardown(a, g, g.lfp, "LFP-1")
    _advance(a, mods["_id"], g.modtest, g.reasm, 6)
    _advance(a, bus["_id"], g.busbar, g.reasm, 1)

    r = a.req("POST", f"/merge/{g.reasm}")          # AUTO, no hint
    assert r.status_code == 201, r.text
    made = a.req("GET", f"/cards/{r.json()['createdCardId']}").json()
    assert made["lotTemplateId"] == g.lfp["reman"], "AUTO assembled the wrong line"


# ─── Un-splitting takes the lot's own twins ──────────────────────────────────

def test_unsplit_consumes_its_own_lots_twins_not_a_strangers(actor):
    """Two packs of the same chemistry torn down side by side: moving pack A's
    modules back must fold in pack A's busbars — the same physical material —
    and leave pack B's standing untouched."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    _order(a, g, g.nmc, 1, "PACK-A")
    _order(a, g, g.nmc, 1, "PACK-B")
    _teardown(a, g, g.nmc, "PACK-A")
    _teardown(a, g, g.nmc, "PACK-B")
    assert _at(a, g.modtest) == 8 and _at(a, g.busbar) == 4

    a_mods = next(c for c in _cards(a)
                  if c["lotTemplateId"] == g.nmc["module"] and c["lotNum"] == "PACK-A")
    r = a.req("POST", f"/cards/{a_mods['_id']}/move",
              {"fromStationId": g.modtest, "toStationId": g.tear, "quantity": 4})
    assert r.status_code == 200, r.text

    reformed = r.json()
    assert reformed["lotNum"] == "PACK-A" and reformed["bins"] == {g.tear: {"count": 1}}
    left_bus = [c for c in _cards(a) if c["lotTemplateId"] == g.nmc["busbar"]]
    assert len(left_bus) == 1 and left_bus[0]["lotNum"] == "PACK-B", \
        "the un-split consumed a stranger's busbars"
    assert left_bus[0]["bins"][g.busbar]["count"] == 2
    assert _at(a, g.modtest) == 4       # B's modules untouched


# ─── The partner boundary is a wall for lots ─────────────────────────────────

def test_no_endpoint_can_park_a_lot_on_the_partner_node(actor):
    """Found by this audit: a handoff link is a real route row, so /advance
    walked finished goods ONTO the ShipStation node — where they then credited
    the order as an unbound leaf, bypassing the handoff and its sink-addressed
    event. A scanner at QA would have done it on every read."""
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    _order(a, g, g.nmc, 1, "NMC-1")
    mods, bus = _teardown(a, g, g.nmc, "NMC-1")
    _advance(a, mods["_id"], g.modtest, g.reasm, 3)
    _advance(a, bus["_id"], g.busbar, g.reasm, 2)
    made_id = a.req("POST", f"/merge/{g.reasm}",
                    {"cardIds": [c["_id"] for c in _cards(a) if c["bins"].get(g.reasm)]}
                    ).json()["createdCardId"]
    _advance(a, made_id, g.reasm, g.qa, 1)

    for endpoint, body in (
        ("advance", {"fromStationId": g.qa, "toStationId": g.ship, "quantity": 1}),
        ("move",    {"fromStationId": g.qa, "toStationId": g.ship, "quantity": 1}),
    ):
        r = a.req("POST", f"/cards/{made_id}/{endpoint}", body)
        assert r.status_code == 400, f"{endpoint} parked a lot on the node: {r.text}"
        assert "never sit on" in r.json()["detail"], r.text

    r = a.req("POST", "/cards/", {"lotTemplateId": g.nmc["pack"], "processId": g.nmc["proc"],
                                  "totalQuantity": 1, "bins": {g.ship: {"count": 1}}})
    assert r.status_code == 400, "create placed bins on the node"
    r = a.req("PUT", f"/cards/{made_id}", {"bins": {g.ship: {"count": 1}}})
    assert r.status_code == 400, "update placed bins on the node"
    assert _at(a, g.ship) == 0


def test_ship_and_stock_are_two_processes(actor):
    """Ship-or-stock is not a branch inside one process — it is two processes
    over the same stations: one pulled by the warehouse (make-to-stock,
    completing on arrival there) and one pulled by the shipper (make-to-order,
    completing at the handoff). The same physical QA bench carries both, and
    each process's flow through it stays deterministic.

    An earlier placement rule special-cased onward routes to storage instead,
    which smuggled an either/or into a single process — exactly the thing the
    separate-process convention exists to prevent."""
    a = actor(); bootstrap_admin(a)
    cell = _st(a, "Cell")
    qa   = _st(a, "Shared QA")
    wh   = _st(a, "Stock shelf", isStorage=True)
    ship = _st(a, "ShipStation", integrationProvider="shipstation", integrationRole="sink")

    stock = a.req("POST", "/processes/", {"name": "To stock"}).json()["_id"]
    _route(a, stock, cell, qa)
    _route(a, stock, qa, wh)
    stock_tmpl = _tmpl(a, "Stock widget", stock, cell)

    to_ship = a.req("POST", "/processes/", {"name": "To ship"}).json()["_id"]
    _route(a, to_ship, cell, qa)
    ship_tmpl = _tmpl(a, "Ship widget", to_ship, cell)
    # The handoff draws fine: within ITS process QA sends work nowhere else.
    # The stock process's QA→shelf route belongs to a different value stream
    # and must not count against it.
    _route(a, to_ship, qa, ship)

    # The mirror: the ship process may not later fork around its own handoff.
    r = a.req("POST", "/routes/", {"processId": to_ship, "load": qa,
                                   "unload": wh, "quantity": 1})
    assert r.status_code == 400, r.text
    assert "its own process" in r.json()["detail"] or "own process" in r.json()["detail"], r.text

    # Both flows run over the shared bench, each deterministic in its process.
    sc = a.req("POST", "/cards/", {"lotTemplateId": stock_tmpl, "processId": stock,
                                   "totalQuantity": 1, "bins": {cell: {"count": 1}}}).json()
    _advance(a, sc["_id"], cell, qa, 1)
    _advance(a, sc["_id"], qa, wh, 1)                 # 1:1, no phantom anywhere
    assert _at(a, wh) == 1 and _at(a, ship) == 0

    hc = a.req("POST", "/cards/", {"lotTemplateId": ship_tmpl, "processId": to_ship,
                                   "totalQuantity": 1, "bins": {cell: {"count": 1}}}).json()
    _advance(a, hc["_id"], cell, qa, 1)
    r = a.req("POST", f"/cards/{hc['_id']}/handoff",
              {"fromStationId": qa, "integrationStationId": ship, "quantity": 1})
    assert r.status_code == 200, r.text
    assert a.req("GET", f"/cards/{hc['_id']}").status_code == 404   # left the system


# ─── Partial handoff: progress, then completion ──────────────────────────────

def test_partial_handoff_reports_progress_then_completion(actor):
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    o = _order(a, g, g.lfp, 2, "LFP-2")
    mods, bus = _teardown(a, g, g.lfp, "LFP-2")     # 2 packs → 12 modules, 2 busbars
    _advance(a, mods["_id"], g.modtest, g.reasm, 12)
    _advance(a, bus["_id"], g.busbar, g.reasm, 2)
    r = a.req("POST", f"/merge/{g.reasm}",
              {"cardIds": [c["_id"] for c in _cards(a) if c["bins"].get(g.reasm)]})
    assert r.status_code == 201 and r.json()["assemblies"] == 2, r.text
    made_id = r.json()["createdCardId"]
    _advance(a, made_id, g.reasm, g.qa, 2)

    # First unit ships.
    r = a.req("POST", f"/cards/{made_id}/handoff",
              {"fromStationId": g.qa, "integrationStationId": g.ship, "quantity": 1})
    assert r.status_code == 200 and r.json()["orderStatus"] == "in_progress", r.text
    remainder = a.req("GET", f"/cards/{made_id}").json()
    assert remainder["bins"][g.qa]["count"] == 1 and remainder["totalQuantity"] == 1

    events = a.req("GET", "/orders/outbox?status=pending").json()
    prog = [e for e in events if e["eventType"] == "order.progress"]
    assert prog and all(e["payload"]["units"] == 1 for e in prog)
    assert {e["payload"]["source"] for e in prog} == {"odoo", "shipstation"}
    assert all(e["payload"]["attributes"] == ATTRS and e["payload"]["lotCode"] == "LFP-2"
               for e in prog)

    # Second unit ships → completed, and the card is gone.
    r = a.req("POST", f"/cards/{made_id}/handoff",
              {"fromStationId": g.qa, "integrationStationId": g.ship, "quantity": 1})
    assert r.status_code == 200 and r.json()["orderStatus"] == "completed", r.text
    assert a.req("GET", f"/cards/{made_id}").status_code == 404
    done = a.req("GET", f"/orders/{o['id']}").json()
    assert done["status"] == "completed" and done["quantityDone"] == 2


# ─── Timing comes out of the real API ────────────────────────────────────────

def test_line_cycle_time_and_session_autoclose(actor):
    a = actor(); bootstrap_admin(a)
    g = _build(a)
    # Two teardowns, so Teardown's departures span separate requests and the
    # inter-departure interval is a real duration rather than a same-call tie.
    _order(a, g, g.nmc, 1, "NMC-1")
    _teardown(a, g, g.nmc, "NMC-1")
    _order(a, g, g.nmc, 1, "NMC-2")
    _teardown(a, g, g.nmc, "NMC-2")

    tear = a.req("GET", f"/sessions/stats/{g.tear}").json()
    assert tear["lineCycleTimeSec"] is not None, "departures happened; the metric must exist"
    assert 0 < tear["lineCycleTimeSec"] < 3600, tear["lineCycleTimeSec"]

    # One open session per station+operator: starting a second closes the first.
    s1 = a.req("POST", "/sessions/", {"stationId": g.modtest, "operatorId": "kim",
                                      "quantity": 1}).json()
    s2 = a.req("POST", "/sessions/", {"stationId": g.modtest, "operatorId": "kim",
                                      "quantity": 1}).json()
    assert s2["_id"] != s1["_id"]
    listed = {s["_id"]: s for s in a.req("GET", f"/sessions/?stationId={g.modtest}").json()}
    assert listed[s1["_id"]]["endedAt"] is not None, "the dangling session stayed open"
    assert listed[s2["_id"]]["endedAt"] is None
