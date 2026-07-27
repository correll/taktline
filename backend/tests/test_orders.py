"""Production-order loop: release (pull) → attribution through merge →
warehouse completion → outbox → ack. Plus idempotency and cancel."""

from tests.helpers import bootstrap_admin, add_member


def build_line(a):
    """Steel + Motor → Assembly (merge) → Warehouse, with source & assembly
    templates. Returns the ids we need."""
    st = {n: a.req("POST", "/stations/", {"name": n}).json()["_id"]
          for n in ("Steel", "Motor", "Assembly", "Warehouse")}
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()
    for load, unload in [("Steel", "Assembly"), ("Motor", "Assembly"), ("Assembly", "Warehouse")]:
        r = a.req("POST", "/routes/", {"processId": proc["_id"], "load": st[load], "unload": st[unload], "quantity": 1})
        assert r.status_code == 201, r.text
    # templates: the two source parts + the assembled product (starts at the merge)
    a.req("POST", "/lot-templates/", {"name": "Steel Part", "startStationId": st["Steel"], "processId": proc["_id"]})
    a.req("POST", "/lot-templates/", {"name": "Motor Part", "startStationId": st["Motor"], "processId": proc["_id"]})
    asm = a.req("POST", "/lot-templates/", {"name": "E-Bike", "startStationId": st["Assembly"], "processId": proc["_id"]}).json()
    return st, proc, asm


def test_order_release_completion_and_outbox(actor):
    a = actor(); bootstrap_admin(a)
    st, proc, asm = build_line(a)

    # 1) release an ERP order for 2 units of the assembled product
    r = a.req("POST", "/orders/", {"productTemplateId": asm["_id"], "quantity": 2,
                                   "source": "odoo", "externalRef": "MO-1"})
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["status"] == "released" and order["quantity"] == 2

    # pull tagged precursor lots at the two source queues
    cards = a.req("GET", "/cards/").json()
    tagged = [c for c in cards if c["orderId"] == order["id"]]
    assert len(tagged) == 2
    assert {tuple(c["bins"].keys())[0] for c in tagged} == {st["Steel"], st["Motor"]}
    assert all(list(c["bins"].values())[0]["count"] == 2 for c in tagged)
    # the lot code comes from the ERP order (externalRef, since no explicit lotCode)
    assert all(c["lotNum"] == "MO-1" for c in tagged)

    # 2) idempotency: same (source, externalRef) returns the same order, no new lots
    r2 = a.req("POST", "/orders/", {"productTemplateId": asm["_id"], "quantity": 5,
                                    "source": "odoo", "externalRef": "MO-1"})
    # 200 (not 201) is how a connector tells a redelivery from a real release
    assert r2.status_code == 200 and r2.json()["id"] == order["id"] and r2.json()["quantity"] == 2
    assert len([c for c in a.req("GET", "/cards/").json() if c["orderId"] == order["id"]]) == 2

    # 3) move both precursors to the merge station, then merge
    for c in tagged:
        frm = list(c["bins"].keys())[0]
        assert a.req("POST", f"/cards/{c['_id']}/move",
                     {"fromStationId": frm, "toStationId": st["Assembly"], "quantity": 2}).status_code == 200
    merged = a.req("POST", f"/merge/{st['Assembly']}")
    assert merged.status_code == 201, merged.text
    assembly_card = merged.json()["createdCardId"]

    # attribution survived the merge — and so did the lot code (all precursors
    # shared "MO-1", so the finished assembly keeps it)
    ac = a.req("GET", f"/cards/{assembly_card}").json()
    assert ac["orderId"] == order["id"]
    assert ac["lotNum"] == "MO-1"

    # 4) move the finished assembly into the warehouse → completion
    assert a.req("POST", f"/cards/{assembly_card}/move",
                 {"fromStationId": st["Assembly"], "toStationId": st["Warehouse"], "quantity": 2}).status_code == 200

    done = a.req("GET", f"/orders/{order['id']}").json()
    assert done["status"] == "completed" and done["quantityDone"] == 2

    # 5) an outbox event is queued for the ERP connector
    pending = a.req("GET", "/orders/outbox", headers={}).json()
    completed_ev = [e for e in pending if e["eventType"] == "order.completed" and e["payload"]["externalRef"] == "MO-1"]
    assert len(completed_ev) == 1
    ev = completed_ev[0]
    assert ev["payload"]["completed"] is True and ev["payload"]["quantityDone"] == 2

    # 6) ack it → leaves the pending queue
    assert a.req("POST", f"/orders/outbox/{ev['id']}/ack").status_code == 204
    still_pending = [e for e in a.req("GET", "/orders/outbox").json() if e["id"] == ev["id"]]
    assert still_pending == []


def test_order_lot_code_explicit_and_generated(actor):
    """A connector may send a friendly lotCode (Shopify "#1001") distinct from the
    externalRef idempotency key; the released lot carries it. A bare manual order
    with neither still gets a generated code, never a null."""
    a = actor(); bootstrap_admin(a)
    st, proc, asm = build_line(a)

    # explicit lotCode wins over externalRef
    o = a.req("POST", "/orders/", {"productTemplateId": asm["_id"], "quantity": 1,
                                   "source": "shopify", "externalRef": "1001:11",
                                   "lotCode": "#1001"}).json()
    lots = [c for c in a.req("GET", "/cards/").json() if c["orderId"] == o["id"]]
    assert lots and all(c["lotNum"] == "#1001" for c in lots)

    # no ref and no code → generated (single-source product at its origin)
    single = a.req("POST", "/lot-templates/", {"name": "Widget", "startStationId": st["Steel"],
                                               "processId": proc["_id"]}).json()
    o2 = a.req("POST", "/orders/", {"productTemplateId": single["_id"], "quantity": 1,
                                    "source": "manual"}).json()
    lot2 = next(c for c in a.req("GET", "/cards/").json() if c["orderId"] == o2["id"])
    assert lot2["lotNum"] and len(lot2["lotNum"]) == 6


def test_order_create_requires_admin(actor):
    admin = actor(); bootstrap_admin(admin)
    st, proc, asm = build_line(admin)
    member = actor(); add_member(admin, member, "user")
    assert member.req("POST", "/orders/", {"productTemplateId": asm["_id"], "quantity": 1}).status_code == 403


def test_order_cancel_scraps_lots(actor):
    a = actor(); bootstrap_admin(a)
    st, proc, asm = build_line(a)
    order = a.req("POST", "/orders/", {"productTemplateId": asm["_id"], "quantity": 1}).json()
    assert len([c for c in a.req("GET", "/cards/").json() if c["orderId"] == order["id"]]) >= 1

    r = a.req("POST", f"/orders/{order['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert [c for c in a.req("GET", "/cards/").json() if c["orderId"] == order["id"]] == []
    cancelled = [e for e in a.req("GET", "/orders/outbox").json() if e["eventType"] == "order.cancelled"]
    assert len(cancelled) == 1


def test_outbox_can_be_scoped_to_one_connector(actor):
    """Events nobody acks (a manual UI release, a CSV import) stay pending for
    good. Sharing one 500-row window with them eventually crowds out a real
    connector's completions, so a connector filters the poll by its own source."""
    a = actor(); bootstrap_admin(a)
    st, proc, asm = build_line(a)
    for source, ref in (("odoo", "MO-9"), ("manual", "UI-1")):
        r = a.req("POST", "/orders/", {"productTemplateId": asm["_id"], "quantity": 1,
                                       "source": source, "externalRef": ref})
        assert r.status_code == 201, r.text
        a.req("POST", f"/orders/{r.json()['id']}/cancel")      # emits order.cancelled

    everything = a.req("GET", "/orders/outbox").json()
    assert {e["payload"]["source"] for e in everything} == {"odoo", "manual"}

    mine = a.req("GET", "/orders/outbox?status=pending&source=odoo").json()
    assert [e["payload"]["externalRef"] for e in mine] == ["MO-9"]


def test_undeliverable_event_parks_after_its_retries(actor):
    """A completion the ERP can never accept (its order was deleted there) must
    stop being retried, or it occupies a slot in every poll forever."""
    a = actor(); bootstrap_admin(a)
    st, proc, asm = build_line(a)
    r = a.req("POST", "/orders/", {"productTemplateId": asm["_id"], "quantity": 1,
                                   "source": "odoo", "externalRef": "MO-X"})
    a.req("POST", f"/orders/{r.json()['id']}/cancel")
    ev = a.req("GET", "/orders/outbox?source=odoo").json()[0]

    for i in range(1, 10):
        body = a.req("POST", f"/orders/outbox/{ev['id']}/fail").json()
        assert body["attempts"] == i
        assert body["status"] == ("failed" if i >= 10 else "pending")
    body = a.req("POST", f"/orders/outbox/{ev['id']}/fail").json()
    assert body["status"] == "failed" and body["attempts"] == 10

    assert [e["id"] for e in a.req("GET", "/orders/outbox?source=odoo").json()] == []
    # parked, not lost — still visible for an operator to inspect
    assert [e["id"] for e in a.req("GET", "/orders/outbox?status=failed").json()] == [ev["id"]]
    # and a late success can still ack it
    assert a.req("POST", f"/orders/outbox/{ev['id']}/fail").json()["attempts"] == 10


def test_fail_is_tenant_scoped(actor):
    a = actor(); bootstrap_admin(a)
    st, proc, asm = build_line(a)
    r = a.req("POST", "/orders/", {"productTemplateId": asm["_id"], "quantity": 1,
                                   "source": "odoo", "externalRef": "MO-T"})
    a.req("POST", f"/orders/{r.json()['id']}/cancel")
    ev = a.req("GET", "/orders/outbox?source=odoo").json()[0]

    other = actor(); bootstrap_admin(other)
    assert other.req("POST", f"/orders/outbox/{ev['id']}/fail").status_code == 404
