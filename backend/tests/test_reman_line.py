"""Battery remanufacturing — the composite rehearsal for minting, moving,
merging and splitting, on a line hard enough to break naive graph semantics:

    Intake ─► Teardown ══╦═(×8, Module)══► ModuleTest ─(×6)──┐
                         ╠═(×4, Busbar)══► BusbarClean ─(×4)─┤
                         ╠═(×2, Cable)═══► CableStrip ─(×2)► HarnessBuild ─(×1)─┤
                         ╚═(×1, Housing)═► HousingWash ─(×1)─┤                  │
       CapStore ────────────(×2)────────────────────────────►┘                  ▼
                                                  Repack ─► FinalTest ─► PackWarehouse

One used pack tears down into 8 modules + 4 busbars + 2 cables + 1 housing; a
harness is 2 cables + 2 caps; a remanufactured pack consumes 6 modules +
4 busbars + 1 harness + 1 housing, so every pack leaves 2 surplus modules for
the spares shelf. Every assertion here is the physically correct outcome —
these tests exist because each of them failed at least once."""

from tests.helpers import bootstrap_admin, flat_routes


class N:
    """Ids of the built factory."""


def _station(a, name):
    r = a.req("POST", "/stations/", {"name": name,
              "position": {"x": 10, "y": 10, "width": 60, "height": 60}})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _template(a, name, proc, station):
    r = a.req("POST", "/lot-templates/", {"name": name, "processId": proc,
                                          "startStationId": station})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _route(a, proc, load, unload):
    r = a.req("POST", "/routes/", {"processId": proc, "load": load,
                                   "unload": unload, "quantity": 1})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _weight(a, rid, qty=None, output=None):
    """Weights and branch products are only accepted once a sibling branch
    exists, so a branching line is drawn flat first and annotated second."""
    body = {}
    if qty is not None:
        body["quantity"] = qty
    if output:
        body["outputTemplateId"] = output
    r = a.req("PUT", f"/routes/{rid}", body)
    assert r.status_code == 200, r.text


def _card(a, tmpl, proc, station, qty=1, lot_num=None):
    body = {"lotTemplateId": tmpl, "processId": proc, "totalQuantity": qty,
            "bins": {station: {"count": qty}}, "fields": {}, "flagged": False,
            "description": "", "status": "idle"}
    if lot_num:
        body["lotNum"] = lot_num
    r = a.req("POST", "/cards/", body)
    assert r.status_code == 201, r.text
    return r.json()


def _advance(a, card_id, frm, to, qty=1):
    return a.req("POST", f"/cards/{card_id}/advance",
                 {"fromStationId": frm, "toStationId": to, "quantity": qty})


def _census(a):
    """{(template name, station name): units} — the whole floor at a glance."""
    tmpl = {t["_id"]: t["name"] for t in a.req("GET", "/lot-templates/").json()}
    st = {s["_id"]: s["name"] for s in a.req("GET", "/stations/").json()}
    out = {}
    for c in a.req("GET", "/cards/").json():
        for sid, b in c["bins"].items():
            if b["count"] > 0:
                k = (tmpl.get(c["lotTemplateId"], "?"), st.get(sid, sid))
                out[k] = out.get(k, 0) + b["count"]
    return out


def build_reman(a):
    n = N()
    r = a.req("POST", "/processes/", {"name": "Reman"})
    n.proc = r.json()["_id"]
    for nm in ["Intake", "Teardown", "ModuleTest", "BusbarClean", "CableStrip",
               "HousingWash", "CapStore", "HarnessBuild", "Repack", "FinalTest",
               "PackWarehouse", "SpareModules"]:
        setattr(n, nm, _station(a, nm))
    n.t_pack = _template(a, "Used pack", n.proc, n.Intake)
    n.t_module = _template(a, "Module", n.proc, n.ModuleTest)
    n.t_busbar = _template(a, "Busbar", n.proc, n.BusbarClean)
    n.t_cable = _template(a, "Cable", n.proc, n.CableStrip)
    n.t_housing = _template(a, "Housing", n.proc, n.HousingWash)
    n.t_cap = _template(a, "Cap", n.proc, n.CapStore)
    n.t_harness = _template(a, "Harness", n.proc, n.HarnessBuild)
    n.t_reman = _template(a, "Reman pack", n.proc, n.Repack)

    _route(a, n.proc, n.Intake, n.Teardown)
    r_mod = _route(a, n.proc, n.Teardown, n.ModuleTest)
    r_bus = _route(a, n.proc, n.Teardown, n.BusbarClean)
    r_cab = _route(a, n.proc, n.Teardown, n.CableStrip)
    r_hou = _route(a, n.proc, n.Teardown, n.HousingWash)
    r_cha = _route(a, n.proc, n.CableStrip, n.HarnessBuild)
    r_cap = _route(a, n.proc, n.CapStore, n.HarnessBuild)
    r_mrep = _route(a, n.proc, n.ModuleTest, n.Repack)
    r_brep = _route(a, n.proc, n.BusbarClean, n.Repack)
    _route(a, n.proc, n.HarnessBuild, n.Repack)
    _route(a, n.proc, n.HousingWash, n.Repack)
    _route(a, n.proc, n.Repack, n.FinalTest)
    _route(a, n.proc, n.FinalTest, n.PackWarehouse)
    # second pass — the siblings exist now
    _weight(a, r_mod, 8, output=n.t_module)
    _weight(a, r_bus, 4, output=n.t_busbar)
    _weight(a, r_cab, 2, output=n.t_cable)
    _weight(a, r_hou, output=n.t_housing)
    _weight(a, r_cha, 2)
    _weight(a, r_cap, 2)
    _weight(a, r_mrep, 6)
    _weight(a, r_brep, 4)
    return n


def _teardown_one_pack(a, n, lot="PACK-001"):
    c = _card(a, n.t_pack, n.proc, n.Intake, 1, lot_num=lot)
    assert _advance(a, c["_id"], n.Intake, n.Teardown).status_code == 200
    assert _advance(a, c["_id"], n.Teardown, n.ModuleTest).status_code == 200


def _stage_repack(a, n):
    """Advance everything at the four feed stations into Repack."""
    for c in a.req("GET", "/cards/").json():
        for frm in (n.ModuleTest, n.BusbarClean, n.HousingWash, n.HarnessBuild):
            cnt = (c["bins"].get(frm) or {}).get("count", 0)
            if cnt:
                assert _advance(a, c["_id"], frm, n.Repack, cnt).status_code == 200


def _build_harness(a, n, cap_lot="CAPS-1"):
    for c in a.req("GET", "/cards/").json():
        cnt = (c["bins"].get(n.CableStrip) or {}).get("count", 0)
        if cnt:
            assert _advance(a, c["_id"], n.CableStrip, n.HarnessBuild, cnt).status_code == 200
    cap = _card(a, n.t_cap, n.proc, n.CapStore, 2, lot_num=cap_lot)
    assert _advance(a, cap["_id"], n.CapStore, n.HarnessBuild, 2).status_code == 200
    r = a.req("POST", f"/merge/{n.HarnessBuild}")
    assert r.status_code == 201, r.text


# ─── Teardown: fan-out with declared products ────────────────────────────────

def test_teardown_fans_out_into_declared_products(actor):
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    _teardown_one_pack(a, n)
    census = _census(a)
    assert census == {("Module", "ModuleTest"): 8, ("Busbar", "BusbarClean"): 4,
                      ("Cable", "CableStrip"): 2, ("Housing", "HousingWash"): 1}
    cards = a.req("GET", "/cards/").json()
    # the pieces are the same physical material: one lot code, no work state
    assert {c["lotNum"] for c in cards} == {"PACK-001"}
    assert {c["status"] for c in cards} == {"idle"}


def test_multi_unit_teardown_scales_every_branch(actor):
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    c = _card(a, n.t_pack, n.proc, n.Intake, 3, lot_num="P3")
    assert _advance(a, c["_id"], n.Intake, n.Teardown, 3).status_code == 200
    assert _advance(a, c["_id"], n.Teardown, n.ModuleTest, 3).status_code == 200
    assert _census(a) == {("Module", "ModuleTest"): 24, ("Busbar", "BusbarClean"): 12,
                          ("Cable", "CableStrip"): 6, ("Housing", "HousingWash"): 3}


# ─── The merge boundary ──────────────────────────────────────────────────────

def test_precursor_advances_into_but_never_out_of_the_merge(actor):
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    _teardown_one_pack(a, n)
    mod = next(c for c in a.req("GET", "/cards/").json() if c["bins"].get(n.ModuleTest))
    # into the merge: 1:1, the weight is applied by the merge, not the move
    r = _advance(a, mod["_id"], n.ModuleTest, n.Repack, 8)
    assert r.status_code == 200 and r.json()["bins"][n.Repack]["count"] == 8
    # out of the merge: never — that would book a module as a finished pack
    assert _advance(a, mod["_id"], n.Repack, n.FinalTest, 1).status_code == 409


def test_two_level_merge_with_partial_card_consumption(actor):
    """The repack takes 6 of the 8 modules OFF one card, leaving a 2-unit
    remainder — partial consumption, not whole-card consumption."""
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    _teardown_one_pack(a, n)
    _build_harness(a, n)
    _stage_repack(a, n)

    pv = a.req("GET", f"/merge/{n.Repack}").json()
    assert pv["assembliesPossible"] == 1          # limited by 8 // 6 modules
    assert a.req("POST", f"/merge/{n.Repack}").status_code == 201
    census = _census(a)
    assert census == {("Reman pack", "Repack"): 1, ("Module", "Repack"): 2}

    pack = next(c for c in a.req("GET", "/cards/").json()
                if c["lotTemplateId"] == n.t_reman)
    assert _advance(a, pack["_id"], n.Repack, n.FinalTest).status_code == 200
    assert _advance(a, pack["_id"], n.FinalTest, n.PackWarehouse).status_code == 200
    assert _census(a)[("Reman pack", "PackWarehouse")] == 1


# ─── Pull: demand recombines backward through split + two merges ─────────────

def test_pull_recombines_demand_across_split_and_merges(actor):
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    assert a.req("POST", f"/merge/{n.Repack}/pull", {"quantity": 1}).status_code == 201
    # four backward walks all reach Intake; the demand is max'd, never summed
    assert _census(a) == {("Used pack", "Intake"): 1, ("Cap", "CapStore"): 2}


def test_pull_scales_with_ceiling_division(actor):
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    a.req("POST", f"/merge/{n.Repack}/pull", {"quantity": 3})
    # 3 assemblies need 18 modules → ceil(18/8) = 3 packs; 6 caps for 3 harnesses
    assert _census(a) == {("Used pack", "Intake"): 3, ("Cap", "CapStore"): 6}


# ─── Orders through the whole graph ──────────────────────────────────────────

def test_order_attribution_survives_split_and_two_merges(actor):
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    order = a.req("POST", "/orders/", {"productTemplateId": n.t_reman, "quantity": 1,
                                       "source": "odoo", "externalRef": "MO-500"}).json()
    assert _census(a) == {("Used pack", "Intake"): 1, ("Cap", "CapStore"): 2}
    assert all(c["orderId"] == order["id"] and c["lotNum"] == "MO-500"
               for c in a.req("GET", "/cards/").json())

    pack = next(c for c in a.req("GET", "/cards/").json() if c["lotTemplateId"] == n.t_pack)
    assert _advance(a, pack["_id"], n.Intake, n.Teardown).status_code == 200
    assert _advance(a, pack["_id"], n.Teardown, n.ModuleTest).status_code == 200
    # the split pieces are still the order's material
    assert all(c["orderId"] == order["id"] for c in a.req("GET", "/cards/").json())

    for c in a.req("GET", "/cards/").json():
        cnt = (c["bins"].get(n.CableStrip) or {}).get("count", 0)
        if cnt:
            _advance(a, c["_id"], n.CableStrip, n.HarnessBuild, cnt)
    for c in a.req("GET", "/cards/").json():
        cnt = (c["bins"].get(n.CapStore) or {}).get("count", 0)
        if cnt:
            _advance(a, c["_id"], n.CapStore, n.HarnessBuild, cnt)
    assert a.req("POST", f"/merge/{n.HarnessBuild}").status_code == 201
    _stage_repack(a, n)
    assert a.req("POST", f"/merge/{n.Repack}").status_code == 201

    pack2 = next(c for c in a.req("GET", "/cards/").json() if c["lotTemplateId"] == n.t_reman)
    # every consumed precursor carried the order → the assembly keeps both
    assert pack2["orderId"] == order["id"] and pack2["lotNum"] == "MO-500"

    assert _advance(a, pack2["_id"], n.Repack, n.FinalTest).status_code == 200
    assert _advance(a, pack2["_id"], n.FinalTest, n.PackWarehouse).status_code == 200
    o = a.req("GET", f"/orders/{order['id']}").json()
    assert o["status"] == "completed" and o["quantityDone"] == 1
    box = a.req("GET", "/orders/outbox?status=pending&source=odoo").json()
    assert [e["eventType"] for e in box] == ["order.completed"]


def test_ordering_a_disassembled_product_pulls_the_source_pack(actor):
    """Modules are made by tearing a pack apart — an order for 8 of them must
    order ONE pack at Intake, not conjure finished modules mid-line."""
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    r = a.req("POST", "/orders/", {"productTemplateId": n.t_module, "quantity": 8,
                                   "source": "odoo", "externalRef": "MO-M8"})
    assert r.status_code == 201, r.text
    assert _census(a) == {("Used pack", "Intake"): 1}


def test_order_for_spare_modules_completes_via_the_relief_route(actor):
    """The full spares loop: order modules → a pack is pulled → teardown → the
    modules are set aside onto the spares shelf (a leaf) → order completes."""
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    _route(a, n.proc, n.ModuleTest, n.SpareModules)      # the relief valve
    order = a.req("POST", "/orders/", {"productTemplateId": n.t_module, "quantity": 8,
                                       "source": "odoo", "externalRef": "MO-SP"}).json()
    pack = next(c for c in a.req("GET", "/cards/").json() if c["lotTemplateId"] == n.t_pack)
    assert _advance(a, pack["_id"], n.Intake, n.Teardown).status_code == 200
    assert _advance(a, pack["_id"], n.Teardown, n.ModuleTest).status_code == 200
    mod = next(c for c in a.req("GET", "/cards/").json() if c["bins"].get(n.ModuleTest))
    assert _advance(a, mod["_id"], n.ModuleTest, n.SpareModules, 8).status_code == 200
    o = a.req("GET", f"/orders/{order['id']}").json()
    assert o["status"] == "completed" and o["quantityDone"] == 8


# ─── The relief valve: surplus without duplication ───────────────────────────

def test_surplus_to_warehouse_relocates_without_duplication(actor):
    """A module is already a piece of a teardown — setting it aside cannot
    disassemble it again. Before the piece-relocation rule, sending 2 surplus
    modules to the spares shelf relabelled them as the shelf's product AND
    minted 2 phantom modules toward the merge; sending 6 into the merge minted
    6 phantoms onto the shelf. 8 modules became 16 units."""
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    _route(a, n.proc, n.ModuleTest, n.SpareModules)      # ModuleTest is now a split
    _teardown_one_pack(a, n)

    mod = next(c for c in a.req("GET", "/cards/").json() if c["bins"].get(n.ModuleTest))
    assert _advance(a, mod["_id"], n.ModuleTest, n.SpareModules, 2).status_code == 200
    census = _census(a)
    assert census[("Module", "SpareModules")] == 2       # still modules, still 2
    assert ("Module", "Repack") not in census            # nothing minted at the merge

    mod = next(c for c in a.req("GET", "/cards/").json() if c["bins"].get(n.ModuleTest))
    assert _advance(a, mod["_id"], n.ModuleTest, n.Repack, 6).status_code == 200
    census = _census(a)
    assert census[("Module", "Repack")] == 6
    assert census[("Module", "SpareModules")] == 2       # untouched by the merge feed
    total = sum(v for (t, _), v in census.items() if t == "Module")
    assert total == 8                                    # conservation


def test_source_material_still_fans_out_after_the_piece_rule(actor):
    """The relocation rule must not weaken real disassembly: the pack is not a
    branch product, so it still fans out onto every branch at once."""
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    _route(a, n.proc, n.ModuleTest, n.SpareModules)
    _teardown_one_pack(a, n)                             # asserts the fan-out itself
    assert _census(a)[("Module", "ModuleTest")] == 8


# ─── Unmerge, two levels deep ────────────────────────────────────────────────

def test_two_level_unmerge_restores_the_exact_precursors(actor):
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    _teardown_one_pack(a, n, lot="PACK-U")
    _build_harness(a, n, cap_lot="PACK-U")
    _stage_repack(a, n)
    assert a.req("POST", f"/merge/{n.Repack}").status_code == 201

    pack = next(c for c in a.req("GET", "/cards/").json() if c["lotTemplateId"] == n.t_reman)
    r = a.req("POST", f"/cards/{pack['_id']}/unmerge", {"stationId": n.Repack, "quantity": 1})
    assert r.status_code == 200, r.text
    census = _census(a)
    assert census[("Module", "ModuleTest")] == 6
    assert census[("Busbar", "BusbarClean")] == 4
    assert census[("Harness", "HarnessBuild")] == 1
    assert census[("Housing", "HousingWash")] == 1

    harness = next(c for c in a.req("GET", "/cards/").json()
                   if c["lotTemplateId"] == n.t_harness)
    r = a.req("POST", f"/cards/{harness['_id']}/unmerge",
              {"stationId": n.HarnessBuild, "quantity": 1})
    assert r.status_code == 200, r.text
    census = _census(a)
    assert census[("Cable", "CableStrip")] == 2 and census[("Cap", "CapStore")] == 2


def test_unmerge_honours_a_direct_disassembly_feed(actor):
    """A split branch may feed the merge DIRECTLY (teardown busbars go straight
    to repack). The feed declares its product, so the unmerge must recreate
    that product at the branch's source — not whatever template happens to
    originate there."""
    a = actor(); bootstrap_admin(a)
    r = a.req("POST", "/processes/", {"name": "Direct"})
    proc = r.json()["_id"]
    intake, tear, mtest, repack = (_station(a, x) for x in
                                   ["Intake", "Teardown", "ModuleTest", "Repack"])
    t_pack = _template(a, "Used pack", proc, intake)
    t_module = _template(a, "Module", proc, mtest)
    t_busbar = _template(a, "Busbar", proc, tear)   # the direct feed's declared product
    t_out = _template(a, "Reman pack", proc, repack)

    _route(a, proc, intake, tear)
    r_m = _route(a, proc, tear, mtest)
    r_b = _route(a, proc, tear, repack)                  # split branch INTO the merge
    r_mr = _route(a, proc, mtest, repack)
    _weight(a, r_m, 8, output=t_module)
    _weight(a, r_b, output=t_busbar)
    _weight(a, r_mr, 6)

    c = _card(a, t_pack, proc, intake, 1, lot_num="D1")
    assert _advance(a, c["_id"], intake, tear).status_code == 200
    assert _advance(a, c["_id"], tear, mtest).status_code == 200
    census = _census(a)
    assert census[("Module", "ModuleTest")] == 8
    assert census[("Busbar", "Repack")] == 1             # landed straight on the merge

    for card in a.req("GET", "/cards/").json():
        cnt = (card["bins"].get(mtest) or {}).get("count", 0)
        if cnt:
            assert _advance(a, card["_id"], mtest, repack, cnt).status_code == 200
    assert a.req("POST", f"/merge/{repack}").status_code == 201

    pack = next(x for x in a.req("GET", "/cards/").json() if x["lotTemplateId"] == t_out)
    r = a.req("POST", f"/cards/{pack['_id']}/unmerge", {"stationId": repack, "quantity": 1})
    assert r.status_code == 200, r.text
    census = _census(a)
    assert census[("Busbar", "Teardown")] == 1           # the declared product, at source
    assert census[("Module", "ModuleTest")] == 6


# ─── A sibling process sharing stations must not contaminate ─────────────────

def test_sibling_process_never_contaminates(actor):
    """Either/or routing lives in its own process (that is the documented
    model). Splits were process-scoped from day one — merges, pulls, unmerges,
    the precursor gate and route-following must be too."""
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    r = a.req("POST", "/processes/", {"name": "Recycle"})
    recycle = r.json()["_id"]
    shredder = _station(a, "Shredder")
    graded = _station(a, "GradedCellStore")
    recycle_out = _station(a, "RecycleOut")
    t_graded = _template(a, "Graded cell", recycle, graded)
    _route(a, recycle, n.ModuleTest, shredder)
    _route(a, recycle, graded, n.Repack)
    _route(a, recycle, n.Repack, recycle_out)

    # (a) the Reman merge preview must list only Reman's four feeds
    pv = a.req("GET", f"/merge/{n.Repack}").json()
    assert len(pv["requirements"]) == 4
    assert graded not in {r["sourceStationId"] for r in pv["requirements"]}

    # (b) a Reman pull must not seed Recycle's queues
    a.req("POST", f"/merge/{n.Repack}/pull", {"quantity": 1})
    assert ("Graded cell", "GradedCellStore") not in _census(a)

    # (c) a Reman card must not ride a Recycle-only route
    _teardown_one_pack(a, n)
    mod = next(c for c in a.req("GET", "/cards/").json() if c["bins"].get(n.ModuleTest))
    assert _advance(a, mod["_id"], n.ModuleTest, shredder, 1).status_code == 400

    # (d) a Recycle card passes THROUGH Repack — Reman's merge gate is not its gate
    g = _card(a, t_graded, recycle, graded, 1)
    assert _advance(a, g["_id"], graded, n.Repack).status_code == 200
    assert _advance(a, g["_id"], n.Repack, recycle_out).status_code == 200

    # (e) a Recycle card standing at Repack is never consumed by Reman's merge
    g2 = _card(a, t_graded, recycle, graded, 1)
    _advance(a, g2["_id"], graded, n.Repack)
    _build_harness(a, n)
    _stage_repack(a, n)
    assert a.req("POST", f"/merge/{n.Repack}").status_code == 201
    assert _census(a).get(("Graded cell", "Repack")) == 1


# ─── Conservation under a full cycle ─────────────────────────────────────────

def test_conservation_through_teardown_merge_unmerge(actor):
    """Tear down, assemble, dissolve — at every step the modules on the floor
    plus the modules inside assemblies must account for exactly 8 per pack."""
    a = actor(); bootstrap_admin(a)
    n = build_reman(a)
    _teardown_one_pack(a, n)
    _build_harness(a, n)
    _stage_repack(a, n)
    assert a.req("POST", f"/merge/{n.Repack}").status_code == 201
    census = _census(a)
    assert census[("Module", "Repack")] == 2             # 6 of 8 inside the pack
    pack = next(c for c in a.req("GET", "/cards/").json() if c["lotTemplateId"] == n.t_reman)
    a.req("POST", f"/cards/{pack['_id']}/unmerge", {"stationId": n.Repack, "quantity": 1})
    total = sum(v for (t, _), v in _census(a).items() if t == "Module")
    assert total == 8                                    # 2 leftover + 6 restored


# ─── The commit must land before the response leaves the server ──────────────

def test_every_session_dependency_commits_before_the_response():
    """FastAPI closes request-scoped dependency stacks only AFTER the response
    has been sent, so a commit living there races the client's next request —
    a tablet could 404 a card whose creation it just saw succeed. get_session
    must therefore be function-scoped at EVERY declaration site: the first one
    FastAPI solves decides which stack the shared session lands in, so one
    stray unscoped Depends silently reintroduces the race."""
    from fastapi.routing import APIRoute
    from app.main import app
    from app.db.connection import get_session

    def walk(dependant, seen):
        for sub in dependant.dependencies:
            if sub.call is get_session:
                seen.append(sub)
            walk(sub, seen)

    checked = 0
    for route in flat_routes(app):
        if not isinstance(getattr(route, "original_route", route), APIRoute):
            continue
        found = []
        walk(route.dependant, found)
        for dep in found:
            assert dep.scope == "function", (
                f"{route.path} declares get_session without scope='function' — "
                f"its commit would land after the response is sent")
            checked += 1
    assert checked > 50   # sanity: the walk really saw the app


# ─── The merge gate applies to the board drag, not just to /advance ──────────

def _merge_gate_rig(a):
    """Cell A + Cell B ─► Assembly ─► Testing, with an assembly product defined
    and one unmerged precursor standing at Assembly."""
    qa, qb = _station(a, "Cell A"), _station(a, "Cell B")
    asm, test = _station(a, "Assembly"), _station(a, "Testing")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    for load, unload in ((qa, asm), (qb, asm), (asm, test)):
        _route(a, proc, load, unload)
    motor = _template(a, "Motor", proc, qa)
    _template(a, "Frame", proc, qb)
    _template(a, "E-Bike", proc, asm)          # the thing Assembly mints
    card = a.req("POST", "/cards/", {"lotTemplateId": motor, "processId": proc,
                                     "totalQuantity": 1,
                                     "bins": {asm: {"count": 1}}}).json()
    return qa, asm, test, card


def test_the_board_drag_cannot_push_an_unmerged_precursor_onward(actor):
    """/advance has refused this for a while; the board's drag never did, so a
    motor could be dragged out of Assembly into Testing and booked as a finished
    e-bike, stranding the frame it should have been merged with."""
    a = actor(); bootstrap_admin(a)
    qa, asm, test, card = _merge_gate_rig(a)
    r = a.req("POST", f"/cards/{card['_id']}/move",
              {"fromStationId": asm, "toStationId": test, "quantity": 1})
    assert r.status_code == 409, r.text
    assert "precursor waiting to be merged" in r.json()["detail"], r.text
    # and nothing moved
    fresh = a.req("GET", f"/cards/{card['_id']}").json()
    assert fresh["bins"].get(asm, {}).get("count") == 1, fresh


def test_dragging_a_precursor_back_is_still_allowed(actor):
    """The gate is about pushing work onward, not about correcting a mistake —
    a super-admin must still be able to put a precursor back where it came
    from, which is also how an unmerge starts."""
    a = actor(); bootstrap_admin(a)
    qa, asm, test, card = _merge_gate_rig(a)
    r = a.req("POST", f"/cards/{card['_id']}/move",
              {"fromStationId": asm, "toStationId": qa, "quantity": 1})
    assert r.status_code == 200, r.text
    assert r.json()["bins"].get(qa, {}).get("count") == 1, r.json()


def test_the_assembly_itself_moves_on_freely(actor):
    """Only precursors are held: what the merge minted is finished work."""
    a = actor(); bootstrap_admin(a)
    qa, asm, test, _ = _merge_gate_rig(a)
    ebike = next(t for t in a.req("GET", "/lot-templates/").json() if t["name"] == "E-Bike")
    proc = a.req("GET", "/processes/").json()[0]["_id"]
    made = a.req("POST", "/cards/", {"lotTemplateId": ebike["_id"], "processId": proc,
                                     "totalQuantity": 1, "bins": {asm: {"count": 1}}}).json()
    r = a.req("POST", f"/cards/{made['_id']}/move",
              {"fromStationId": asm, "toStationId": test, "quantity": 1})
    assert r.status_code == 200, r.text
