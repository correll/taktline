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
    ERP itself instead of minting at the queue."""
    a = actor(); bootstrap_admin(a)
    odoo, intake, cell, ship, proc, tmpl = _line(a)
    # Intake is still a leaf queue as far as the graph is concerned.
    r = a.req("GET", f"/merge/{intake['_id']}/preview")
    if r.status_code == 200:
        assert r.json().get("isMergeStation") in (False, None), r.json()


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
