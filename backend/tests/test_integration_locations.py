"""Integration locations — where work enters and leaves the business.

Before this, the boundary was implicit in the shape of the graph: any leaf with
no incoming routes could originate lots, and *any* leaf with no outgoing routes
completed orders. Nothing knew that a particular dock belonged to Shopify, or
which of two finished-goods leaves was the one that ships, so a completion could
only ever be addressed to whichever connector released the order.

    [Odoo] ┄demand┄► Intake ──► Cell A ┄handoff┄► [ShipStation]
     source                                          sink

**Integration nodes never hold cards.** An ERP node raises *demand* against the
queue it is wired to — a release fires the same pull the "create precursors"
button does, and the lots appear at the queue, not on the partner's node. A
sink node is the far side of a handoff: the finished lot sits at a real
location until someone sends it ("Send back to Odoo"), and that act consumes it.

So an edge touching an integration node is a **boundary link, not material
flow**, and is excluded from every piece of graph reasoning. ShipStation is
sink-only: a shipper cannot raise demand.
"""

from tests.helpers import bootstrap_admin


def _station(a, name, **kw):
    body = {"name": name, "position": {"x": 10, "y": 10, "width": 60, "height": 60}}
    body.update(kw)
    r = a.req("POST", "/stations/", body)
    assert r.status_code == 201, r.text
    return r.json()


def _line(a):
    """[Odoo] ┄► Intake → Cell A ┄► [ShipStation]."""
    odoo = _station(a, "Odoo", integrationProvider="odoo", integrationRole="both")
    intake = _station(a, "Intake")
    cell = _station(a, "Cell A")
    ship = _station(a, "ShipStation",
                    integrationProvider="shipstation", integrationRole="sink")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    for load, unload in ((odoo["_id"], intake["_id"]),        # demand link
                         (intake["_id"], cell["_id"]),        # real flow
                         (cell["_id"], ship["_id"])):         # handoff link
        r = a.req("POST", "/routes/", {"processId": proc, "load": load,
                                       "unload": unload, "quantity": 1})
        assert r.status_code == 201, r.text
    tmpl = a.req("POST", "/lot-templates/", {"name": "Widget", "processId": proc,
                                             "startStationId": intake["_id"]}).json()
    return odoo, intake, cell, ship, proc, tmpl


# ─── The binding itself ──────────────────────────────────────────────────────

def test_a_location_can_be_bound_to_a_partner(actor):
    a = actor(); bootstrap_admin(a)
    s = _station(a, "Odoo Goods In", integrationProvider="odoo", integrationRole="source")
    assert s["integrationProvider"] == "odoo"
    assert s["integrationRole"] == "source"
    # And it round-trips through the list, which is what the map reads.
    listed = {x["_id"]: x for x in a.req("GET", "/stations/").json()}
    assert listed[s["_id"]]["integrationProvider"] == "odoo"


def test_an_ordinary_location_stays_unbound(actor):
    a = actor(); bootstrap_admin(a)
    s = _station(a, "Cell A")
    assert s["integrationProvider"] is None and s["integrationRole"] is None


def test_a_bogus_partner_or_role_is_refused(actor):
    a = actor(); bootstrap_admin(a)
    r = a.req("POST", "/stations/", {"name": "X", "integrationProvider": "sap"})
    assert r.status_code == 400, r.text
    r = a.req("POST", "/stations/", {"name": "X", "integrationProvider": "odoo",
                                     "integrationRole": "middle"})
    assert r.status_code == 400, r.text
    # A role with no partner is meaningless and must not be storable.
    r = a.req("POST", "/stations/", {"name": "X", "integrationRole": "sink"})
    assert r.status_code == 400, r.text


# ─── Source: a release seeds the bound dock, not the first work station ──────

def test_a_release_raises_demand_at_the_queue_not_on_the_partners_node(actor):
    """The ERP asks the queue for parts; it does not hand them over. Cards mint
    where the "create precursors" button would have made them."""
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    r = a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 3,
                                  "source": "odoo", "externalRef": "MO-1"})
    assert r.status_code == 201, r.text

    cards = a.req("GET", "/cards/").json()
    assert len(cards) == 1, cards
    bins = cards[0]["bins"]
    assert bins.get(intake["_id"], {}).get("count") == 3, bins
    # Nothing ever stands on the partner's node.
    assert odoo["_id"] not in bins, bins


def test_a_demand_link_does_not_make_the_queue_look_made_here(actor):
    """The regression this guards: an incoming edge from Odoo would otherwise
    read as an upstream feed, and the pull would walk back and try to seed the
    ERP itself instead of minting at the queue.

    (An earlier version of this test called `/merge/{id}/preview` — a path that
    does not exist — and guarded its assertion behind `if status == 200`, so it
    passed while checking nothing. The preview is `GET /merge/{id}`, and a
    guard that skips the assertion is a test that skips the test.)"""
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    r = a.req("GET", f"/merge/{intake['_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["isMergeStation"] is False, r.json()


# ─── Sink: the completion reaches the partner it left through ────────────────

def _advance(a, card_id, frm, to, qty):
    r = a.req("POST", f"/cards/{card_id}/advance",
              {"fromStationId": frm, "toStationId": to, "quantity": qty})
    assert r.status_code == 200, r.text
    return r.json()


def test_completion_is_delivered_to_the_sinks_partner_and_the_releaser(actor):
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    # Released by hand: before, its completion carried source='manual' and no
    # connector could ever ack it — the event sat pending forever.
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 2,
                              "source": "manual", "externalRef": "UI-1"})
    card = a.req("GET", "/cards/").json()[0]
    _advance(a, card["_id"], intake["_id"], cell["_id"], 2)
    # Nothing has been reported yet: the goods are on a bench, not shipped.
    assert a.req("GET", "/orders/outbox?status=pending").json() == []
    r = a.req("POST", f"/cards/{card['_id']}/handoff",
              {"fromStationId": cell["_id"], "integrationStationId": ship["_id"],
               "quantity": 2})
    assert r.status_code == 200, r.text
    assert r.json()["sentTo"] == "shipstation"
    # The lot left Taktline — it is not parked on the partner's node.
    assert a.req("GET", "/cards/").json() == []

    events = a.req("GET", "/orders/outbox?status=pending").json()
    audiences = sorted(e["payload"]["source"] for e in events)
    assert audiences == ["manual", "shipstation"], events
    assert all(e["payload"]["sinkProvider"] == "shipstation" for e in events)
    assert all(e["eventType"] == "order.completed" for e in events)

    # The shipper can now drain its own completions by name — the whole point.
    mine = a.req("GET", "/orders/outbox?status=pending&source=shipstation").json()
    assert len(mine) == 1 and mine[0]["payload"]["externalRef"] == "UI-1"


def test_no_duplicate_when_the_releaser_owns_the_handoff(actor):
    """Odoo raises the demand and Odoo takes the goods back: one event, not two."""
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    # Send back to Odoo rather than to the shipper.
    rr = a.req("POST", "/routes/", {"processId": proc, "load": cell["_id"],
                                    "unload": odoo["_id"], "quantity": 1})
    assert rr.status_code == 201, rr.text
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                              "source": "odoo", "externalRef": "MO-2"})
    card = a.req("GET", "/cards/").json()[0]
    _advance(a, card["_id"], intake["_id"], cell["_id"], 1)
    r = a.req("POST", f"/cards/{card['_id']}/handoff",
              {"fromStationId": cell["_id"], "integrationStationId": odoo["_id"],
               "quantity": 1})
    assert r.status_code == 200, r.text

    events = a.req("GET", "/orders/outbox?status=pending").json()
    assert len(events) == 1, events
    assert events[0]["payload"]["source"] == "odoo"


def test_a_shipper_cannot_raise_demand(actor):
    """ShipStation is sink-only: wiring it as a demand source is refused, which
    is the whole difference between a shipper and an ERP."""
    a = actor(); bootstrap_admin(a)
    r = a.req("POST", "/stations/", {"name": "Bad", "integrationProvider": "shipstation",
                                     "integrationRole": "source"})
    assert r.status_code == 400, r.text


def test_handoff_needs_a_drawn_link(actor):
    """A lot can only leave through a partner this location actually hands to."""
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                              "source": "odoo", "externalRef": "MO-9"})
    card = a.req("GET", "/cards/").json()[0]
    # Intake has no handoff link to the shipper.
    r = a.req("POST", f"/cards/{card['_id']}/handoff",
              {"fromStationId": intake["_id"], "integrationStationId": ship["_id"],
               "quantity": 1})
    assert r.status_code == 400, r.text


def test_an_unbound_leaf_still_completes_orders(actor):
    """The chosen migration rule: binding a sink is additive. Every line built
    before integration locations existed keeps reporting completions."""
    a = actor(); bootstrap_admin(a)
    cell = _station(a, "Cell A")
    wh = _station(a, "Warehouse")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    a.req("POST", "/routes/", {"processId": proc, "load": cell["_id"],
                               "unload": wh["_id"], "quantity": 1})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Widget", "processId": proc,
                                             "startStationId": cell["_id"]}).json()
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                              "source": "odoo", "externalRef": "MO-3"})
    card = a.req("GET", "/cards/").json()[0]
    _advance(a, card["_id"], cell["_id"], wh["_id"], 1)

    events = a.req("GET", "/orders/outbox?status=pending").json()
    assert len(events) == 1, events
    assert events[0]["payload"]["source"] == "odoo"
    # Nothing claims it left through a partner's dock, because it did not.
    assert events[0]["payload"]["sinkProvider"] is None


# ─── Bound locations are not shop-floor stations ─────────────────────────────

def test_bound_locations_report_no_oee_or_takt(actor):
    """Nobody stands at an ERP. A bound location is excluded the same way a
    warehouse is, so it cannot flatten the heat scale or invent a takt."""
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    # Stats only lists stations with sessions; assert via the per-station route,
    # which answers for any station.
    for sid in (odoo["_id"], ship["_id"]):
        s = a.req("GET", f"/sessions/stats/{sid}").json()
        assert s["isWarehouse"] is True, (sid, s)
        assert s["oee"] is None, s
    work = a.req("GET", f"/sessions/stats/{cell['_id']}").json()
    assert work["isWarehouse"] is False, work


# ─── Where an integration may attach ─────────────────────────────────────────

def test_demand_must_land_where_the_line_can_answer_it(actor):
    """An order has to arrive somewhere the line can act on: where the product
    is made, or somewhere the line already feeds (ordering into stock). A
    station that is neither cannot answer it — and a line can have many
    material entry points but only one finished product, which is why "where
    material starts" was never the test either.

    Cell A, fed by Intake, IS answerable and is allowed: pressing "pull
    precursors" there already walks back and seeds the queues. Refusing the
    link to a station whose pull button worked was the app disagreeing with
    itself."""
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)   # product is made at Intake
    assert a.req("POST", "/routes/", {"processId": proc, "load": odoo["_id"],
                                      "unload": cell["_id"], "quantity": 1}).status_code == 201

    # A station with no product and nothing feeding it stays refused.
    orphan = _station(a, "Nowhere")
    r = a.req("POST", "/routes/", {"processId": proc, "load": odoo["_id"],
                                   "unload": orphan["_id"], "quantity": 1})
    assert r.status_code == 400, r.text
    assert "nothing upstream feeds it" in r.json()["detail"], r.text


def test_demand_into_a_products_own_location_is_allowed(actor):
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    # _line already draws Odoo → Intake, and the Widget template starts there.
    routes = a.req("GET", "/routes/").json()
    assert any(r["load"] == odoo["_id"] and r["unload"] == intake["_id"] for r in routes), routes


def test_demand_may_target_an_assembly_location(actor):
    """The case that motivates the rule: an assembled product is made at its
    merge location, deep in the flow, and that is exactly where the ERP order
    belongs — the pull walks back to the queues on its own."""
    a = actor(); bootstrap_admin(a)
    odoo = _station(a, "Odoo", integrationProvider="odoo", integrationRole="both")
    qa, qb = _station(a, "Queue A"), _station(a, "Queue B")
    asm = _station(a, "Assembly")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    for load, unload in ((qa["_id"], asm["_id"]), (qb["_id"], asm["_id"])):
        a.req("POST", "/routes/", {"processId": proc, "load": load,
                                   "unload": unload, "quantity": 1})
    a.req("POST", "/lot-templates/", {"name": "Widget", "processId": proc,
                                      "startStationId": asm["_id"]})
    r = a.req("POST", "/routes/", {"processId": proc, "load": odoo["_id"],
                                   "unload": asm["_id"], "quantity": 1})
    assert r.status_code == 201, r.text

    # And the pull still seeds both material entry points, not the assembly.
    tmpl = [t for t in a.req("GET", "/lot-templates/").json() if t["name"] == "Widget"][0]
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                              "source": "odoo", "externalRef": "MO-ASM"})
    seeded = {sid for c in a.req("GET", "/cards/").json() for sid in c["bins"]}
    assert seeded == {qa["_id"], qb["_id"]}, seeded


def test_a_line_with_no_products_yet_can_still_be_drawn(actor):
    """Chicken-and-egg: the graph often exists before its products are named."""
    a = actor(); bootstrap_admin(a)
    odoo = _station(a, "Odoo", integrationProvider="odoo", integrationRole="both")
    anywhere = _station(a, "Cell A")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    r = a.req("POST", "/routes/", {"processId": proc, "load": odoo["_id"],
                                   "unload": anywhere["_id"], "quantity": 1})
    assert r.status_code == 201, r.text


def test_a_queue_fed_by_an_erp_is_still_a_leaf(actor):
    """The boundary link must not turn a location into a mid-line station: a
    release still mints there rather than pulling further back."""
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 2,
                              "source": "odoo", "externalRef": "MO-LEAF"})
    cards = a.req("GET", "/cards/").json()
    assert len(cards) == 1, cards
    assert cards[0]["bins"].get(intake["_id"], {}).get("count") == 2, cards[0]


def test_handoff_may_only_leave_the_end_of_the_flow(actor):
    """Goods leave when they are finished; a shipper hanging off a mid-line
    location would take parts that still have work to come."""
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    r = a.req("POST", "/routes/", {"processId": proc, "load": intake["_id"],
                                   "unload": ship["_id"], "quantity": 1})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "last station of this process" in detail, detail
    assert "still sends work on to Cell A" in detail, detail


# ─── Where demand may land ───────────────────────────────────────────────────

def _stock_line(a):
    """Steel + Motor → Assembly → Testing → Warehouse, with an ERP and a
    shipper standing by. Products start at the queues and at Assembly."""
    st = lambda n, **kw: a.req("POST", "/stations/", {
        "name": n, "description": "", "adapterType": None, "adapterConfig": {},
        "color": None, "icon": None,
        "position": {"x": 1, "y": 1, "width": 60, "height": 60}, **kw}).json()["_id"]
    g = {}
    for n in ("Steel", "Motor", "Assembly", "Testing", "Warehouse"):
        g[n] = st(n, **({"isStorage": True} if n == "Warehouse" else {}))
    g["Odoo"] = st("Odoo", integrationProvider="odoo", integrationRole="both")
    g["ShipStation"] = st("ShipStation", integrationProvider="shipstation",
                          integrationRole="sink")
    g["proc"] = a.req("POST", "/processes/", {"name": "Main"}).json()["_id"]
    for load, unload in (("Steel", "Assembly"), ("Motor", "Assembly"),
                         ("Assembly", "Testing"), ("Testing", "Warehouse")):
        r = a.req("POST", "/routes/", {"processId": g["proc"], "load": g[load],
                                       "unload": g[unload], "quantity": 1})
        assert r.status_code == 201, r.text
    for name, station in (("Bar", "Steel"), ("Motor", "Motor"), ("Machine", "Assembly")):
        a.req("POST", "/lot-templates/", {"name": name, "processId": g["proc"],
                                          "startStationId": g[station]})
    return g


def test_demand_may_land_on_a_warehouse_the_line_feeds(actor):
    """Ordering INTO STOCK. The board already offers "pull precursors" at a
    station the line feeds — pressing it walks back and seeds the source
    queues — so demand may be raised there too. The map used to refuse the link
    to the very station whose pull button worked, which meant the app
    contradicted itself about one station."""
    a = actor(); bootstrap_admin(a)
    g = _stock_line(a)

    r = a.req("POST", "/routes/", {"processId": g["proc"], "load": g["Odoo"],
                                   "unload": g["Warehouse"], "quantity": 1})
    assert r.status_code == 201, r.text

    # And the button that made the argument still works there.
    p = a.req("POST", f"/merge/{g['Warehouse']}/pull", {"quantity": 1})
    assert p.status_code == 201, p.text


def test_demand_may_still_land_where_the_product_is_made(actor):
    a = actor(); bootstrap_admin(a)
    g = _stock_line(a)
    r = a.req("POST", "/routes/", {"processId": g["proc"], "load": g["Odoo"],
                                   "unload": g["Assembly"], "quantity": 1})
    assert r.status_code == 201, r.text


def test_demand_on_a_station_with_nothing_upstream_is_still_refused(actor):
    """The genuinely wrong case survives: a source queue makes no finished
    product and nothing feeds it, so an order landing there cannot be answered."""
    a = actor(); bootstrap_admin(a)
    g = _stock_line(a)
    orphan = a.req("POST", "/stations/", {
        "name": "Nowhere", "description": "", "adapterType": None, "adapterConfig": {},
        "color": None, "icon": None,
        "position": {"x": 1, "y": 1, "width": 60, "height": 60}}).json()["_id"]
    r = a.req("POST", "/routes/", {"processId": g["proc"], "load": g["Odoo"],
                                   "unload": orphan, "quantity": 1})
    assert r.status_code == 400
    assert "nothing upstream feeds it" in r.json()["detail"], r.text


def test_two_integrations_cannot_be_linked_to_each_other(actor):
    """No material crosses an edge between two external systems, so the line
    would mean nothing. The refusal says so rather than talking about products."""
    a = actor(); bootstrap_admin(a)
    g = _stock_line(a)
    r = a.req("POST", "/routes/", {"processId": g["proc"], "load": g["Odoo"],
                                   "unload": g["ShipStation"], "quantity": 1})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "both integrations" in detail and "no material moves" in detail, detail


def test_a_shipper_cannot_raise_demand_by_drawing_the_link_backwards(actor):
    """ShipStation is sink-only: goods leave through it, orders do not start
    there. Binding already refuses the source role — but nothing asked the
    DRAWING, so an outgoing link from a shipper was accepted, which is exactly
    the demand link only a source would draw. The capability check existed two
    files away and the map walked round it."""
    a = actor(); bootstrap_admin(a)
    g = _stock_line(a)

    # The binding half of the rule, for contrast: still refused.
    r = a.req("PUT", f"/stations/{g['ShipStation']}", {"integrationRole": "source"})
    assert r.status_code == 400, r.text

    # And now the drawing half too.
    r = a.req("POST", "/routes/", {"processId": g["proc"], "load": g["ShipStation"],
                                   "unload": g["Assembly"], "quantity": 1})
    assert r.status_code == 400, r.text
    assert "orders do not start there" in r.json()["detail"], r.text

    # The direction that does mean something is unaffected.
    r = a.req("POST", "/routes/", {"processId": g["proc"], "load": g["Warehouse"],
                                   "unload": g["ShipStation"], "quantity": 1})
    assert r.status_code == 201, r.text


# ─── Every provider, every direction ─────────────────────────────────────────

def test_every_provider_binds_only_to_roles_it_can_play(actor):
    """Walks the whole catalog rather than spot-checking, so a provider added
    later is covered the day it appears."""
    from app.core.integrations import PROVIDERS, ROLES
    a = actor(); bootstrap_admin(a)
    for provider, capability in PROVIDERS.items():
        for role in sorted(ROLES):
            legal = role in (("source", "sink", "both") if capability == "both"
                             else (capability,))
            r = a.req("POST", "/stations/", {
                "name": f"{provider}-{role}", "description": "", "adapterType": None,
                "adapterConfig": {}, "color": None, "icon": None,
                "position": {"x": 1, "y": 1, "width": 60, "height": 60},
                "integrationProvider": provider, "integrationRole": role})
            assert (r.status_code == 201) is legal, \
                f"{provider} as {role}: expected {'ok' if legal else '400'}, got {r.status_code}"


def test_every_provider_draws_only_the_links_its_role_permits(actor):
    """Demand out, handoff in — each allowed exactly when the bound role can
    play that part. The bug this pins: the capability was enforced when binding
    a node and never when drawing its link, so a sink-only shipper could still
    draw the outgoing demand link a source draws."""
    from app.core.integrations import PROVIDERS
    a = actor(); bootstrap_admin(a)
    g = _stock_line(a)

    for provider, capability in PROVIDERS.items():
        for role in (("source", "sink", "both") if capability == "both" else (capability,)):
            node = a.req("POST", "/stations/", {
                "name": f"{provider}·{role}", "description": "", "adapterType": None,
                "adapterConfig": {}, "color": None, "icon": None,
                "position": {"x": 1, "y": 1, "width": 60, "height": 60},
                "integrationProvider": provider, "integrationRole": role}).json()["_id"]

            # Demand: partner → the station that makes the product.
            demand = a.req("POST", "/routes/", {"processId": g["proc"], "load": node,
                                                "unload": g["Assembly"], "quantity": 1})
            want_demand = role in ("source", "both")
            assert (demand.status_code == 201) is want_demand, \
                f"{provider}/{role} demand link: got {demand.status_code} {demand.text[:90]}"
            if demand.status_code == 201:
                a.req("DELETE", f"/routes/{demand.json()['_id']}")

            # Handoff: the end of the flow → partner.
            handoff = a.req("POST", "/routes/", {"processId": g["proc"], "load": g["Warehouse"],
                                                 "unload": node, "quantity": 1})
            want_handoff = role in ("sink", "both")
            assert (handoff.status_code == 201) is want_handoff, \
                f"{provider}/{role} handoff link: got {handoff.status_code} {handoff.text[:90]}"
            if handoff.status_code == 201:
                a.req("DELETE", f"/routes/{handoff.json()['_id']}")


def test_no_two_integrations_may_be_linked_whatever_they_are(actor):
    """Partner→partner is refused on the pairing, not on the capabilities — a
    source-capable node pointing at a sink-capable one still moves no material
    through Taktline."""
    from app.core.integrations import PROVIDERS
    a = actor(); bootstrap_admin(a)
    g = _stock_line(a)
    sources = [p for p, c in PROVIDERS.items() if c in ("source", "both")]
    sinks = [p for p, c in PROVIDERS.items() if c in ("sink", "both")]
    made = {}
    for p in set(sources + sinks):
        made[p] = a.req("POST", "/stations/", {
            "name": f"pp-{p}", "description": "", "adapterType": None, "adapterConfig": {},
            "color": None, "icon": None,
            "position": {"x": 1, "y": 1, "width": 60, "height": 60},
            "integrationProvider": p}).json()["_id"]
    for src in sources:
        for sink in sinks:
            if src == sink:
                continue
            r = a.req("POST", "/routes/", {"processId": g["proc"], "load": made[src],
                                           "unload": made[sink], "quantity": 1})
            assert r.status_code == 400, f"{src} → {sink} was allowed: {r.text[:100]}"
            assert "both integrations" in r.json()["detail"]


def test_the_frontend_registry_agrees_with_the_backend_catalog():
    """The UI decides which roles to offer from its own copy of the catalog
    (domain/integrations.ts). If the two drift, a provider added to the backend
    shows no controls, or the UI offers a role the server refuses — a dead
    control, which is the exact failure the capability rule exists to prevent.
    Checked by reading the file, because a build step cannot be assumed here.
    """
    import re
    from pathlib import Path
    from app.core.integrations import PROVIDERS

    ts = (Path(__file__).resolve().parents[2]
          / "frontend" / "src" / "domain" / "integrations.ts").read_text()
    found = dict(re.findall(
        r"\{\s*id:\s*'([a-z]+)'.*?defaultRole:\s*'(source|sink|both)'", ts, re.S))
    assert found, "could not parse the frontend registry — has its shape changed?"
    assert set(found) == set(PROVIDERS), (
        f"catalogs differ — backend only: {sorted(set(PROVIDERS) - set(found))}, "
        f"frontend only: {sorted(set(found) - set(PROVIDERS))}")
    for provider, capability in PROVIDERS.items():
        assert found[provider] == capability, (
            f"{provider}: backend says {capability!r}, the UI says {found[provider]!r} — "
            f"the UI would offer a role the server refuses, or hide one it allows")
