"""The ERP's data must survive the whole journey of the material it describes.

    release ─► seed queues ─► work ─► merge/split/unmerge ─► handoff ─► sink

An order arrives carrying context — customer, due date, ship-to. That context
is only useful if it is standing next to the material: on the Kanban card at
the queue, still on the card after a merge or a teardown, and back in the
sink's hands when the goods leave. Every transformation used to reset
``fields={}``, so the customer's name fell off the card at the first merge and
the shipper got an order id and nothing else.

The invariant these tests enforce: **no transformation drops the data.**
Attribution (orderId) and context (attributes→fields) follow the same rule the
lot code already followed — same physical material, same card contents.
"""

from tests.helpers import bootstrap_admin

ATTRS = {"customer": "Ada Lovelace", "shipTo": "12 Analytical Way, London",
         "dueDate": "2026-08-15", "priority": "rush"}


def _station(a, name, **kw):
    body = {"name": name, "position": {"x": 10, "y": 10, "width": 60, "height": 60}}
    body.update(kw)
    r = a.req("POST", "/stations/", body)
    assert r.status_code == 201, r.text
    return r.json()


def _route(a, proc, load, unload, qty=1):
    r = a.req("POST", "/routes/", {"processId": proc, "load": load,
                                   "unload": unload, "quantity": qty})
    assert r.status_code == 201, r.text
    return r.json()


def _merge_line(a):
    """Queue A + Queue B ─► Assembly ─► [ShipStation].  Product = the assembly."""
    qa = _station(a, "Queue A")
    qb = _station(a, "Queue B")
    asm = _station(a, "Assembly")
    ship = _station(a, "ShipStation",
                    integrationProvider="shipstation", integrationRole="sink")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    _route(a, proc, qa["_id"], asm["_id"])
    _route(a, proc, qb["_id"], asm["_id"])
    _route(a, proc, asm["_id"], ship["_id"])
    tmpl = a.req("POST", "/lot-templates/", {"name": "Assembly Widget", "processId": proc,
                                             "startStationId": asm["_id"]}).json()
    return qa, qb, asm, ship, proc, tmpl


# ─── Release: the data lands on the order and on every seeded card ───────────

def test_release_stamps_attributes_onto_every_seeded_lot(actor):
    a = actor(); bootstrap_admin(a)
    qa, qb, asm, ship, proc, tmpl = _merge_line(a)
    r = a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                                  "source": "shopify", "externalRef": "1001:11",
                                  "lotCode": "#1001", "attributes": ATTRS})
    assert r.status_code == 201, r.text
    assert r.json()["attributes"] == ATTRS

    cards = a.req("GET", "/cards/").json()
    # An assembled product pulls: one precursor lot per feeding queue.
    assert len(cards) == 2, cards
    for c in cards:
        assert c["fields"] == ATTRS, c            # the ERP's context is ON the card
        assert c["lotNum"] == "#1001", c          # traceable to the store order
    seeded_at = sorted(sid for c in cards for sid in c["bins"])
    assert seeded_at == sorted([qa["_id"], qb["_id"]]), seeded_at


def test_attributes_must_be_flat_and_bounded(actor):
    a = actor(); bootstrap_admin(a)
    _, _, _, _, _, tmpl = _merge_line(a)
    r = a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                                  "source": "x", "externalRef": "n1",
                                  "attributes": {"nested": {"not": "allowed"}}})
    assert r.status_code == 422, r.text
    r = a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                                  "source": "x", "externalRef": "n2",
                                  "attributes": {f"k{i}": i for i in range(40)}})
    assert r.status_code == 422, r.text


# ─── The full loop: merge keeps it, handoff returns it ───────────────────────

def test_data_survives_merge_and_returns_to_the_sink(actor):
    a = actor(); bootstrap_admin(a)
    qa, qb, asm, ship, proc, tmpl = _merge_line(a)
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                              "source": "shopify", "externalRef": "1001:11",
                              "lotCode": "#1001", "attributes": ATTRS})
    # Work the precursors forward into the merge station.
    for c in a.req("GET", "/cards/").json():
        frm = next(iter(c["bins"]))
        r = a.req("POST", f"/cards/{c['_id']}/advance",
                  {"fromStationId": frm, "toStationId": asm["_id"], "quantity": 1})
        assert r.status_code == 200, r.text
    # Assemble.
    r = a.req("POST", f"/merge/{asm['_id']}")
    assert r.status_code in (200, 201), r.text
    assembled = a.req("GET", "/cards/").json()
    assert len(assembled) == 1, assembled
    card = assembled[0]
    assert card["fields"] == ATTRS, card          # survived the merge
    assert card["lotNum"] == "#1001", card
    assert card["orderId"] is not None, card

    # Hand it to the shipper — the sink gets back what the store sent in.
    r = a.req("POST", f"/cards/{card['_id']}/handoff",
              {"fromStationId": asm["_id"], "integrationStationId": ship["_id"],
               "quantity": 1})
    assert r.status_code == 200, r.text
    events = a.req("GET", "/orders/outbox?status=pending").json()
    audiences = sorted(e["payload"]["source"] for e in events)
    assert audiences == ["shipstation", "shopify"], events
    for e in events:
        p = e["payload"]
        assert p["attributes"] == ATTRS, p        # ship-to back in the shipper's hands
        assert p["lotCode"] == "#1001", p
        assert p["units"] == 1, p                 # THIS handoff, not the cumulative count
        assert p["sinkProvider"] == "shipstation", p


# ─── Split and unmerge: transformations, not laundering ──────────────────────

def test_teardown_pieces_keep_the_context(actor):
    """One source lot fans out into pieces; each piece is the same physical
    material and keeps order, code and context."""
    a = actor(); bootstrap_admin(a)
    src = _station(a, "Teardown")
    p1 = _station(a, "Modules")
    p2 = _station(a, "Housings")
    proc = a.req("POST", "/processes/", {"name": "Tear"}).json()["_id"]
    _route(a, proc, src["_id"], p1["_id"])
    _route(a, proc, src["_id"], p2["_id"])
    tmpl = a.req("POST", "/lot-templates/", {"name": "Pack", "processId": proc,
                                             "startStationId": src["_id"]}).json()
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                              "source": "odoo", "externalRef": "MO-5",
                              "lotCode": "MO/00005", "attributes": ATTRS})
    card = a.req("GET", "/cards/").json()[0]
    r = a.req("POST", f"/cards/{card['_id']}/advance",
              {"fromStationId": src["_id"], "toStationId": p1["_id"], "quantity": 1})
    assert r.status_code == 200, r.text
    pieces = a.req("GET", "/cards/").json()
    assert len(pieces) == 2, pieces               # one per branch
    for piece in pieces:
        assert piece["fields"] == ATTRS, piece
        assert piece["lotNum"] == "MO/00005", piece
        assert piece["orderId"] == card["orderId"], piece


def test_unmerge_keeps_order_and_context(actor):
    a = actor(); bootstrap_admin(a)
    qa, qb, asm, ship, proc, tmpl = _merge_line(a)
    a.req("POST", "/orders", {"productTemplateId": tmpl["_id"], "quantity": 1,
                              "source": "shopify", "externalRef": "1001:11",
                              "lotCode": "#1001", "attributes": ATTRS})
    for c in a.req("GET", "/cards/").json():
        frm = next(iter(c["bins"]))
        a.req("POST", f"/cards/{c['_id']}/advance",
              {"fromStationId": frm, "toStationId": asm["_id"], "quantity": 1})
    a.req("POST", f"/merge/{asm['_id']}")
    card = a.req("GET", "/cards/").json()[0]
    r = a.req("POST", f"/cards/{card['_id']}/unmerge",
              {"stationId": asm["_id"], "quantity": 1})
    assert r.status_code == 200, r.text
    for pre in a.req("GET", "/cards/").json():
        assert pre["fields"] == ATTRS, pre
        assert pre["lotNum"] == "#1001", pre
        assert pre["orderId"] == card["orderId"], pre   # the order is still owed


# ─── No order, still a handoff ───────────────────────────────────────────────

def test_orderless_handoff_still_tells_the_sink(actor):
    """A hand-made lot (or set-aside surplus) leaving through a partner's dock
    is still physical goods the partner received. `lot.handoff` carries the
    card's identity; connectors that only speak order events drain it
    harmlessly — the core acks unknown types without delivering."""
    a = actor(); bootstrap_admin(a)
    cell = _station(a, "Cell A")
    ship = _station(a, "ShipStation",
                    integrationProvider="shipstation", integrationRole="sink")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    _route(a, proc, cell["_id"], ship["_id"])
    tmpl = a.req("POST", "/lot-templates/", {"name": "Widget", "processId": proc,
                                             "startStationId": cell["_id"]}).json()
    r = a.req("POST", "/cards/", {"lotTemplateId": tmpl["_id"], "processId": proc,
                                  "lotNum": "HAND-1", "totalQuantity": 2,
                                  "bins": {cell["_id"]: {"count": 2}},
                                  "fields": {"note": "spares for the fair"}})
    assert r.status_code == 201, r.text
    card = r.json()
    r = a.req("POST", f"/cards/{card['_id']}/handoff",
              {"fromStationId": cell["_id"], "integrationStationId": ship["_id"],
               "quantity": 2})
    assert r.status_code == 200, r.text
    events = a.req("GET", "/orders/outbox?status=pending&source=shipstation").json()
    assert len(events) == 1, events
    e = events[0]
    assert e["eventType"] == "lot.handoff", e
    assert e["payload"]["lotCode"] == "HAND-1", e
    assert e["payload"]["units"] == 2, e
    assert e["payload"]["attributes"] == {"note": "spares for the fair"}, e


# ─── CSV: the spreadsheet's extra columns ride on the card ───────────────────

def test_csv_extra_columns_become_card_data(actor):
    a = actor(); bootstrap_admin(a)
    cell = _station(a, "Cell A")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    tmpl = a.req("POST", "/lot-templates/", {"name": "Widget", "processId": proc,
                                             "startStationId": cell["_id"]}).json()
    csv_text = ("product,quantity,externalRef,customer,dueDate\n"
                f"Widget,3,CSV-1,Grace Hopper,2026-09-01\n")
    r = a.req("POST", "/orders/import",
              files={"file": ("orders.csv", csv_text, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["released"] == 1, r.json()

    card = a.req("GET", "/cards/").json()[0]
    assert card["fields"] == {"customer": "Grace Hopper", "dueDate": "2026-09-01"}, card
