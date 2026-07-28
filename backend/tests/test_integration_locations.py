"""Integration locations — where work enters and leaves the business.

Before this, the boundary was implicit in the shape of the graph: any leaf with
no incoming routes could originate lots, and *any* leaf with no outgoing routes
completed orders. Nothing knew that a particular dock belonged to Shopify, or
which of two finished-goods leaves was the one that ships, so a completion could
only ever be addressed to whichever connector released the order.

    [Odoo Goods In] ──► Cell A ──► [ShipStation]
     source, odoo                   sink, shipstation

The line below is deliberately trivial. What is being tested is not the graph —
that is covered exhaustively in test_reman_line — but the binding: that a
release seeds the *bound source* rather than the first work station, and that a
completion reaches the partner whose dock it left through even when a different
one (here, a manual release) put the order in.
"""

from tests.helpers import bootstrap_admin


def _station(a, name, **kw):
    body = {"name": name, "position": {"x": 10, "y": 10, "width": 60, "height": 60}}
    body.update(kw)
    r = a.req("POST", "/stations/", body)
    assert r.status_code == 201, r.text
    return r.json()


def _line(a):
    """Goods In (odoo, source) → Cell A → Shipping (shipstation, sink)."""
    goods_in = _station(a, "Odoo Goods In",
                        integrationProvider="odoo", integrationRole="source")
    cell = _station(a, "Cell A")
    ship = _station(a, "ShipStation Shipping",
                    integrationProvider="shipstation", integrationRole="sink")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    for load, unload in ((goods_in["_id"], cell["_id"]), (cell["_id"], ship["_id"])):
        r = a.req("POST", "/routes/", {"processId": proc, "load": load,
                                       "unload": unload, "quantity": 1})
        assert r.status_code == 201, r.text
    tmpl = a.req("POST", "/lot-templates/", {"name": "Widget", "processId": proc,
                                             "startStationId": cell["_id"]}).json()
    return goods_in, cell, ship, proc, tmpl


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

def test_release_seeds_the_bound_source_location(actor):
    a = actor(); bootstrap_admin(a)
    goods_in, cell, ship, proc, tmpl = _line(a)
    r = a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 3,
                                  "source": "odoo", "externalRef": "MO-1"})
    assert r.status_code == 201, r.text

    cards = a.req("GET", "/cards/").json()
    assert len(cards) == 1, cards
    bins = cards[0]["bins"]
    # The lot starts at the dock work actually arrives through — *not* at the
    # product's own origin, which is where it would have appeared before.
    assert goods_in["_id"] in bins, bins
    assert cell["_id"] not in bins, bins
    assert bins[goods_in["_id"]]["count"] == 3


# ─── Sink: the completion reaches the partner it left through ────────────────

def _advance(a, card_id, frm, to, qty):
    r = a.req("POST", f"/cards/{card_id}/advance",
              {"fromStationId": frm, "toStationId": to, "quantity": qty})
    assert r.status_code == 200, r.text
    return r.json()


def test_completion_is_delivered_to_the_sinks_partner_and_the_releaser(actor):
    a = actor(); bootstrap_admin(a)
    goods_in, cell, ship, proc, tmpl = _line(a)
    # Released by hand: before, its completion carried source='manual' and no
    # connector could ever ack it — the event sat pending forever.
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 2,
                              "source": "manual", "externalRef": "UI-1"})
    card = a.req("GET", "/cards/").json()[0]
    _advance(a, card["_id"], goods_in["_id"], cell["_id"], 2)
    _advance(a, card["_id"], cell["_id"], ship["_id"], 2)

    events = a.req("GET", "/orders/outbox?status=pending").json()
    audiences = sorted(e["payload"]["source"] for e in events)
    assert audiences == ["manual", "shipstation"], events
    assert all(e["payload"]["sinkProvider"] == "shipstation" for e in events)
    assert all(e["eventType"] == "order.completed" for e in events)

    # The shipper can now drain its own completions by name — the whole point.
    mine = a.req("GET", "/orders/outbox?status=pending&source=shipstation").json()
    assert len(mine) == 1 and mine[0]["payload"]["externalRef"] == "UI-1"


def test_no_duplicate_when_the_releaser_owns_the_dock(actor):
    """Odoo releases and Odoo's own dock ships it: one event, not two."""
    a = actor(); bootstrap_admin(a)
    goods_in = _station(a, "Odoo Goods In", integrationProvider="odoo", integrationRole="source")
    cell = _station(a, "Cell A")
    out = _station(a, "Odoo Shipping", integrationProvider="odoo", integrationRole="sink")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    for load, unload in ((goods_in["_id"], cell["_id"]), (cell["_id"], out["_id"])):
        a.req("POST", "/routes/", {"processId": proc, "load": load, "unload": unload, "quantity": 1})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Widget", "processId": proc,
                                             "startStationId": cell["_id"]}).json()
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                              "source": "odoo", "externalRef": "MO-2"})
    card = a.req("GET", "/cards/").json()[0]
    _advance(a, card["_id"], goods_in["_id"], cell["_id"], 1)
    _advance(a, card["_id"], cell["_id"], out["_id"], 1)

    events = a.req("GET", "/orders/outbox?status=pending").json()
    assert len(events) == 1, events
    assert events[0]["payload"]["source"] == "odoo"


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
    goods_in, cell, ship, proc, tmpl = _line(a)
    stats = {s["stationId"]: s for s in a.req("GET", "/sessions/stats").json()}
    # Stats only lists stations with sessions; assert via the per-station route,
    # which answers for any station.
    for sid in (goods_in["_id"], ship["_id"]):
        s = a.req("GET", f"/sessions/stats/{sid}").json()
        assert s["isWarehouse"] is True, (sid, s)
        assert s["oee"] is None, s
    work = a.req("GET", f"/sessions/stats/{cell['_id']}").json()
    assert work["isWarehouse"] is False, work
