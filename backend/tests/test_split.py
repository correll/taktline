"""Split stations: a station with 2+ outgoing routes multiplies a lot into
pieces, the mirror image of a merge consuming precursors."""

from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {},
           "color": None, "icon": None,
           "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _line(a: Actor):
    """bar --(x4)--> tube  and  bar --> scrap   (bar is a split station)"""
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    bar, tube, scrap = st("bar"), st("tube"), st("scrap")
    proc = a.req("POST", "/processes/", {"name": "Cutting"}).json()
    a.req("POST", "/routes/", {"processId": proc["_id"], "load": bar["_id"],
                               "unload": scrap["_id"], "quantity": 1})
    r = a.req("POST", "/routes/", {"processId": proc["_id"], "load": bar["_id"],
                                   "unload": tube["_id"], "quantity": 4})
    assert r.status_code == 201, r.text
    return bar, tube, scrap, proc


def test_split_route_may_carry_a_weight():
    a = Actor(); bootstrap_admin(a)
    _line(a)   # the weighted split route is accepted (asserted inside)


def test_advancing_through_a_split_fans_out_to_every_branch():
    """A split is a disassembly: one bar becomes four tubes AND one offcut, each
    its own lot pinned to that branch's product."""
    a = Actor(); bootstrap_admin(a)
    bar, tube, scrap, proc = _line(a)
    tmpl = a.req("POST", "/lot-templates/", {"name": "Bar", "processId": proc["_id"],
                                             "startStationId": bar["_id"]}).json()
    card = a.req("POST", "/cards/", {
        "lotTemplateId": tmpl["_id"], "processId": proc["_id"], "totalQuantity": 2,
        "bins": {bar["_id"]: {"count": 2}}, "fields": {}, "flagged": False,
        "description": "", "status": "idle"}).json()

    r = a.req("POST", f"/cards/{card['_id']}/advance",
              {"fromStationId": bar["_id"], "toStationId": tube["_id"], "quantity": 1})
    assert r.status_code == 200, r.text

    cards = a.req("GET", "/cards/").json()
    at = lambda sid: [c for c in cards if c["bins"].get(sid, {}).get("count", 0) > 0]
    assert at(tube["_id"])[0]["bins"][tube["_id"]]["count"] == 4    # four tubes…
    assert at(scrap["_id"])[0]["bins"][scrap["_id"]]["count"] == 1  # …and one offcut
    assert at(bar["_id"])[0]["bins"][bar["_id"]]["count"] == 1      # second bar untouched
    # Each piece is pinned to the product that branch originates.
    tmpls = {t["_id"]: t for t in a.req("GET", "/lot-templates/").json()}
    assert tmpls[at(tube["_id"])[0]["lotTemplateId"]]["startStationId"] == tube["_id"]
    assert tmpls[at(scrap["_id"])[0]["lotTemplateId"]]["startStationId"] == scrap["_id"]


def test_pull_through_a_split_creates_one_upstream_lot():
    """Demand for four tubes must order one bar, not four.

    bar --(x4)--> tube --> assembly <-- widget
      \--> scrap                     (bar splits; assembly merges)
    """
    a = Actor(); bootstrap_admin(a)
    bar, tube, _scrap, proc = _line(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    assembly, widget = st("assembly"), st("widget")
    for load in (tube, widget):
        r = a.req("POST", "/routes/", {"processId": proc["_id"], "load": load["_id"],
                                       "unload": assembly["_id"], "quantity": 1})
        assert r.status_code == 201, r.text

    r = a.req("POST", f"/merge/{assembly['_id']}/pull", {"quantity": 4})
    assert r.status_code == 201, r.text
    by_station = {s["stationId"]: s["quantity"] for s in r.json()["sources"]}
    assert by_station[bar["_id"]] == 1        # one bar yields the four tubes
    assert by_station[widget["_id"]] == 4     # the 1:1 branch still needs four


def test_weight_still_rejected_on_an_unbranched_route():
    a = Actor(); bootstrap_admin(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    x, y = st("x"), st("y")
    proc = a.req("POST", "/processes/", {"name": "P"}).json()
    r = a.req("POST", "/routes/", {"processId": proc["_id"], "load": x["_id"],
                                   "unload": y["_id"], "quantity": 3})
    assert r.status_code == 400 and "branches" in r.text


def _diamond(a: Actor):
    """loc1 --> loc2 --> loc4  and  loc1 --> loc3 --> loc4 (all weights 1)."""
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    l1, l2, l3, l4 = st("loc1"), st("loc2"), st("loc3"), st("loc4")
    p = a.req("POST", "/processes/", {"name": "Diamond"}).json()["_id"]
    for load, unload in ((l1, l2), (l1, l3), (l2, l4), (l3, l4)):
        r = a.req("POST", "/routes/", {"processId": p, "load": load["_id"],
                                       "unload": unload["_id"], "quantity": 1})
        assert r.status_code == 201, r.text
    return l1, l2, l3, l4, p


def test_diamond_pull_creates_a_single_source_lot():
    """Demand that reconverges on one split source is recombined: pulling one
    assembly orders ONE lot at loc1, not one per branch."""
    a = Actor(); bootstrap_admin(a)
    l1, _l2, _l3, l4, _p = _diamond(a)
    r = a.req("POST", f"/merge/{l4['_id']}/pull", {"quantity": 1})
    assert r.status_code == 201, r.text
    sources = r.json()["sources"]
    assert len(sources) == 1
    assert sources[0]["stationId"] == l1["_id"] and sources[0]["quantity"] == 1
    assert len(r.json()["createdCardIds"]) == 1


def test_diamond_pull_scales_with_demand():
    a = Actor(); bootstrap_admin(a)
    l1, _l2, _l3, l4, _p = _diamond(a)
    r = a.req("POST", f"/merge/{l4['_id']}/pull", {"quantity": 5})
    sources = r.json()["sources"]
    assert len(sources) == 1 and sources[0]["quantity"] == 5   # 5 units, still one lot


def test_diamond_with_uneven_split_weights_takes_the_larger_branch():
    """One unit at the source becomes pieces on every branch at once, so the
    requirement is the biggest branch's demand — never the sum."""
    a = Actor(); bootstrap_admin(a)
    l1, l2, l3, l4, p = _diamond(a)
    # loc1 --(x2)--> loc2 (2 pieces per unit) while loc1 --> loc3 stays 1:1
    route = next(r for r in a.req("GET", "/routes/").json()
                 if r["load"] == l1["_id"] and r["unload"] == l2["_id"])
    assert a.req("PUT", f"/routes/{route['_id']}", {"quantity": 2}).status_code == 200

    r = a.req("POST", f"/merge/{l4['_id']}/pull", {"quantity": 4})
    sources = r.json()["sources"]
    assert len(sources) == 1
    # loc2 branch needs ceil(4/2)=2; loc3 branch needs 4 → 4 units cover both.
    assert sources[0]["quantity"] == 4


def test_alternative_routing_in_another_process_is_not_a_split():
    """Choice routing lives in its own process: a second outgoing route in a
    DIFFERENT process neither unlocks a weight nor causes a fan-out."""
    a = Actor(); bootstrap_admin(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    qc, paint, rework = st("qc"), st("paint"), st("rework")
    main = a.req("POST", "/processes/", {"name": "Main"}).json()["_id"]
    alt  = a.req("POST", "/processes/", {"name": "Rework"}).json()["_id"]
    assert a.req("POST", "/routes/", {"processId": main, "load": qc["_id"],
                                      "unload": paint["_id"], "quantity": 1}).status_code == 201
    assert a.req("POST", "/routes/", {"processId": alt, "load": qc["_id"],
                                      "unload": rework["_id"], "quantity": 1}).status_code == 201

    # qc branches only across processes, so Main's route stays unbranched: no weight.
    route = next(r for r in a.req("GET", "/routes/").json()
                 if r["load"] == qc["_id"] and r["unload"] == paint["_id"])
    assert a.req("PUT", f"/routes/{route['_id']}", {"quantity": 3}).status_code == 400

    tmpl = a.req("POST", "/lot-templates/", {"name": "Part", "processId": main,
                                             "startStationId": qc["_id"]}).json()
    card = a.req("POST", "/cards/", {
        "lotTemplateId": tmpl["_id"], "processId": main, "totalQuantity": 1,
        "bins": {qc["_id"]: {"count": 1}}, "fields": {}, "flagged": False,
        "description": "", "status": "idle"}).json()
    body = a.req("POST", f"/cards/{card['_id']}/advance",
                 {"fromStationId": qc["_id"], "toStationId": paint["_id"],
                  "quantity": 1}).json()
    # Plain 1:1 hop — the other process's branch is untouched.
    assert body["bins"][paint["_id"]]["count"] == 1
    assert rework["_id"] not in body["bins"]


def test_diamond_flows_end_to_end():
    """The point of fan-out: one pulled lot at loc1 becomes a piece on loc2 AND
    loc3 in a single advance, so the merge at loc4 can complete."""
    a = Actor(); bootstrap_admin(a)
    l1, l2, l3, l4, _p = _diamond(a)
    a.req("POST", f"/merge/{l4['_id']}/pull", {"quantity": 1})
    card = next(c for c in a.req("GET", "/cards/").json()
                if c["bins"].get(l1["_id"], {}).get("count", 0) > 0)

    r = a.req("POST", f"/cards/{card['_id']}/advance",
              {"fromStationId": l1["_id"], "toStationId": l2["_id"], "quantity": 1})
    assert r.status_code == 200, r.text

    # One piece per branch, each its own lot, both carrying the source lot code.
    cards = a.req("GET", "/cards/").json()
    at = lambda sid: [c for c in cards if c["bins"].get(sid, {}).get("count", 0) > 0]
    assert len(at(l2["_id"])) == 1 and len(at(l3["_id"])) == 1
    assert not at(l1["_id"])                                   # source consumed
    assert at(l2["_id"])[0]["lotNum"] == card["lotNum"] == at(l3["_id"])[0]["lotNum"]

    # Both pieces move on to the merge station…
    for src, piece in ((l2, at(l2["_id"])[0]), (l3, at(l3["_id"])[0])):
        r = a.req("POST", f"/cards/{piece['_id']}/advance",
                  {"fromStationId": src["_id"], "toStationId": l4["_id"], "quantity": 1})
        assert r.status_code == 200, r.text
    assert a.req("GET", f"/merge/{l4['_id']}").json()["assembliesPossible"] == 1

    # …and the merge completes.
    r = a.req("POST", f"/merge/{l4['_id']}")
    assert r.status_code == 201, r.text
    assert r.json()["assemblies"] == 1


def test_warehouse_is_excluded_from_oee():
    """A warehouse stores rather than runs, so OEE there would measure shelf
    time. It is reported as null and flagged."""
    a = Actor(); bootstrap_admin(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    work, wh = st("welding"), st("warehouse")
    p = a.req("POST", "/processes/", {"name": "P"}).json()["_id"]
    a.req("POST", "/routes/", {"processId": p, "load": work["_id"],
                               "unload": wh["_id"], "quantity": 1})
    # A closed work session at each station.
    for station in (work, wh):
        s = a.req("POST", "/sessions/", {"stationId": station["_id"], "cardId": None,
                                         "quantity": 2}).json()
        assert a.req("POST", f"/sessions/{s['_id']}/end", {"quantity": 2}).status_code == 200

    stats = {s["stationId"]: s for s in a.req("GET", "/sessions/stats").json()}
    assert stats[work["_id"]]["isWarehouse"] is False
    assert stats[work["_id"]]["oee"] is not None          # a real station still reports
    assert stats[wh["_id"]]["isWarehouse"] is True
    assert stats[wh["_id"]]["oee"] is None                # the warehouse does not
    assert stats[wh["_id"]]["cycleTimeSec"] is not None    # cycle time still measured

    one = a.req("GET", f"/sessions/stats/{wh['_id']}").json()
    assert one["isWarehouse"] is True and one["oee"] is None


def test_split_branch_landing_on_a_merge_station_stays_a_precursor():
    """loc1 splits, one branch lands on loc3 — which is itself a merge fed by
    loc5. The minted piece must read as "the loc1 branch's precursor", not as
    loc3's own product (that template is what loc3 mints assemblies with)."""
    a = Actor(); bootstrap_admin(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    l1, l3, l5, l9 = st("loc1"), st("loc3"), st("loc5"), st("loc9")
    p = a.req("POST", "/processes/", {"name": "P"}).json()["_id"]
    for load, unload in ((l1, l9), (l1, l3), (l5, l3)):
        assert a.req("POST", "/routes/", {"processId": p, "load": load["_id"],
                                          "unload": unload["_id"], "quantity": 1}).status_code == 201
    mk_t = lambda n, sid: a.req("POST", "/lot-templates/", {
        "name": n, "processId": p, "startStationId": sid}).json()
    t1, t5 = mk_t("Bar", l1["_id"]), mk_t("Widget", l5["_id"])
    mk_c = lambda t, sid: a.req("POST", "/cards/", {
        "lotTemplateId": t["_id"], "processId": p, "totalQuantity": 1,
        "bins": {sid: {"count": 1}}, "fields": {}, "flagged": False,
        "description": "", "status": "idle"}).json()

    a.req("POST", f"/cards/{mk_c(t1, l1['_id'])['_id']}/advance",
          {"fromStationId": l1["_id"], "toStationId": l3["_id"], "quantity": 1})
    a.req("POST", f"/cards/{mk_c(t5, l5['_id'])['_id']}/advance",
          {"fromStationId": l5["_id"], "toStationId": l3["_id"], "quantity": 1})

    tmpls = {t["_id"]: t for t in a.req("GET", "/lot-templates/").json()}
    at3 = [c for c in a.req("GET", "/cards/").json()
           if c["bins"].get(l3["_id"], {}).get("count", 0) > 0]
    # Neither piece wears loc3's own (assembly) template.
    assert all(tmpls[c["lotTemplateId"]]["startStationId"] != l3["_id"] for c in at3)
    assert {tmpls[c["lotTemplateId"]]["startStationId"] for c in at3} == {l1["_id"], l5["_id"]}

    assert a.req("GET", f"/merge/{l3['_id']}").json()["assembliesPossible"] == 1
    r = a.req("POST", f"/merge/{l3['_id']}")
    assert r.status_code == 201, r.text
    assert r.json()["assemblies"] == 1
    # The assembly is loc3's own product, and the precursors are gone.
    after = [c for c in a.req("GET", "/cards/").json()
             if c["bins"].get(l3["_id"], {}).get("count", 0) > 0]
    assert len(after) == 1
    assert tmpls.get(after[0]["lotTemplateId"], a.req("GET", "/lot-templates/").json()
                     and next(t for t in a.req("GET", "/lot-templates/").json()
                              if t["_id"] == after[0]["lotTemplateId"]))["startStationId"] == l3["_id"]


def test_two_split_fed_branches_into_one_merge_stay_distinct():
    """Both branches are minted by splits; each must keep its own source's
    identity or the merge would count one pile twice."""
    a = Actor(); bootstrap_admin(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    bar, plate, scrapA, scrapB, asm = st("bar"), st("plate"), st("scrapA"), st("scrapB"), st("asm")
    p = a.req("POST", "/processes/", {"name": "P"}).json()["_id"]
    for load, unload in ((bar, scrapA), (bar, asm), (plate, scrapB), (plate, asm)):
        assert a.req("POST", "/routes/", {"processId": p, "load": load["_id"],
                                          "unload": unload["_id"], "quantity": 1}).status_code == 201
    for src in (bar, plate):
        t = a.req("POST", "/lot-templates/", {"name": f"{src['name']} stock",
                                              "processId": p, "startStationId": src["_id"]}).json()
        c = a.req("POST", "/cards/", {
            "lotTemplateId": t["_id"], "processId": p, "totalQuantity": 1,
            "bins": {src["_id"]: {"count": 1}}, "fields": {}, "flagged": False,
            "description": "", "status": "idle"}).json()
        a.req("POST", f"/cards/{c['_id']}/advance",
              {"fromStationId": src["_id"], "toStationId": asm["_id"], "quantity": 1})

    prev = a.req("GET", f"/merge/{asm['_id']}").json()
    assert [r["availableUnits"] for r in prev["requirements"]] == [1, 1]   # not [2, 0]
    assert prev["assembliesPossible"] == 1


def test_disassembly_branches_carry_their_own_products():
    """A battery disassembles into modules, busbars and cables; the cable then
    merges with a cap. Each branch must yield its own named product, including
    the branch that lands on the merge station."""
    a = Actor(); bootstrap_admin(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    teardown, mod_store, bus_store = st("teardown"), st("module store"), st("busbar store")
    cap_line, reassembly = st("cap line"), st("cable+cap")
    p = a.req("POST", "/processes/", {"name": "Recycling"}).json()["_id"]
    mk_t = lambda n, sid: a.req("POST", "/lot-templates/", {
        "name": n, "processId": p, "startStationId": sid}).json()
    battery = mk_t("Battery", teardown["_id"])
    module, busbar, cable = (mk_t("Module", mod_store["_id"]),
                             mk_t("Busbar", bus_store["_id"]),
                             mk_t("Cable", teardown["_id"]))
    cap = mk_t("Cap", cap_line["_id"])

    # Three disassembly branches, each declaring its product; the cable branch
    # lands straight on the merge station.
    def route(load, unload, qty, out=None):
        body = {"processId": p, "load": load["_id"], "unload": unload["_id"], "quantity": qty}
        if out: body["outputTemplateId"] = out["_id"]
        return a.req("POST", "/routes/", body)
    assert route(teardown, mod_store, 1).status_code == 201            # sibling first
    assert route(teardown, bus_store, 4, busbar).status_code == 201
    assert route(teardown, reassembly, 1, cable).status_code == 201
    assert route(cap_line, reassembly, 1).status_code == 201
    # Name the module branch's product too, now that the split exists.
    mod_route = next(r for r in a.req("GET", "/routes/").json()
                     if r["load"] == teardown["_id"] and r["unload"] == mod_store["_id"])
    assert a.req("PUT", f"/routes/{mod_route['_id']}",
                 {"outputTemplateId": module["_id"], "quantity": 6}).status_code == 200

    mk_c = lambda t, sid, n=1: a.req("POST", "/cards/", {
        "lotTemplateId": t["_id"], "processId": p, "totalQuantity": n,
        "bins": {sid: {"count": n}}, "fields": {}, "flagged": False,
        "description": "", "status": "idle"}).json()
    scrap = mk_c(battery, teardown["_id"])
    a.req("POST", f"/cards/{scrap['_id']}/advance",
          {"fromStationId": teardown["_id"], "toStationId": mod_store["_id"], "quantity": 1})

    tmpls = {t["_id"]: t["name"] for t in a.req("GET", "/lot-templates/").json()}
    cards = a.req("GET", "/cards/").json()
    named = {tmpls[c["lotTemplateId"]]: sum(b["count"] for b in c["bins"].values())
             for c in cards}
    assert named["Module"] == 6 and named["Busbar"] == 4
    assert named["Cable"] == 1      # lands straight on the merge, so 1:1
    assert "Battery" not in named   # fully disassembled

    # The cable is a precursor at the merge, not a stray "Battery".
    a.req("POST", f"/cards/{mk_c(cap, cap_line['_id'])['_id']}/advance",
          {"fromStationId": cap_line["_id"], "toStationId": reassembly["_id"], "quantity": 1})
    prev = a.req("GET", f"/merge/{reassembly['_id']}").json()
    assert prev["assembliesPossible"] == 1     # one cable + one cap
    r = a.req("POST", f"/merge/{reassembly['_id']}")
    assert r.status_code == 201, r.text


def test_output_product_rejected_on_an_unbranched_route():
    a = Actor(); bootstrap_admin(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    x, y = st("x"), st("y")
    p = a.req("POST", "/processes/", {"name": "P"}).json()["_id"]
    t = a.req("POST", "/lot-templates/", {"name": "T", "processId": p,
                                          "startStationId": x["_id"]}).json()
    r = a.req("POST", "/routes/", {"processId": p, "load": x["_id"], "unload": y["_id"],
                                   "quantity": 1, "outputTemplateId": t["_id"]})
    assert r.status_code == 400 and "split" in r.text
