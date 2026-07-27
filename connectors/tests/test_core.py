"""Connector orchestration — verified against fakes, no network or ERP SDK.

The same Connector drives every ERP, so these tests cover Odoo, NetSuite, and
any future connector at once.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from taktline_connect.core import Connector, Mapping   # noqa: E402


class FakeErp:
    def __init__(self, orders):
        self.orders = orders
        self.done: list[str] = []
        self.cancelled: list[str] = []

    def list_orders(self, states):
        return [o for o in self.orders if not states or o["state"] in states]

    def mark_done(self, ref):
        self.done.append(ref)

    def cancel(self, ref):
        self.cancelled.append(ref)


class FakeStore:
    """A storefront ERP (Shopify/Woo shape) — cancellations originate here."""
    def __init__(self, orders, cancellations):
        self.orders = orders
        self.cancellations = cancellations

    def list_orders(self, states):
        return [o for o in self.orders if not states or o["state"] in states]

    def list_cancellations(self, states):
        return list(self.cancellations)


class FakeTaktline:
    def __init__(self):
        self.orders: dict = {}          # (source, ref) -> order
        self.outbox: list[dict] = []
        self.acked: list[str] = []
        self.cancelled: list[tuple] = []

    def create_order(self, template_id, quantity, external_ref, source, lot_code=None):
        key = (source, external_ref)
        if key in self.orders:          # server-side idempotency on (source, ref)
            return self.orders[key]
        o = {"id": f"ord-{len(self.orders)}", "externalRef": external_ref,
             "quantity": quantity, "templateId": template_id, "lotCode": lot_code}
        self.orders[key] = o
        return o

    def cancel_by_ref(self, source, external_ref):
        self.cancelled.append((source, external_ref))
        return (source, external_ref) in self.orders   # False if unknown → benign

    def list_outbox(self, status="pending"):
        return [e for e in self.outbox if e["status"] == status]

    def ack_outbox(self, event_id):
        for e in self.outbox:
            if e["id"] == event_id:
                e["status"] = "delivered"
        self.acked.append(event_id)


def _connector(orders, source="odoo", states=("confirmed",), pmap=None):
    v = FakeTaktline()
    erp = FakeErp(orders)
    mapping = Mapping(pmap if pmap is not None else {"BIKE-001": "tmpl-1"})
    return Connector(erp, v, mapping, source=source, order_states=states), erp, v


def _event(eid, etype, source, ref, status="pending"):
    return {"id": eid, "eventType": etype, "status": status,
            "payload": {"source": source, "externalRef": ref}}


# --- release ------------------------------------------------------------

def test_release_maps_and_creates():
    c, _, v = _connector([{"id": 42, "product_ref": "BIKE-001", "qty": 5, "state": "confirmed"}])
    assert c.sync_orders() == 1
    (order,) = v.orders.values()
    assert order["externalRef"] == "42" and order["quantity"] == 5 and order["templateId"] == "tmpl-1"


def test_release_passes_lot_code_through():
    # A friendly ERP reference on the order becomes the lot code sent to Taktline;
    # without one the server falls back to the externalRef (lotCode stays None).
    c, _, v = _connector([{"id": 42, "product_ref": "BIKE-001", "qty": 1,
                           "state": "confirmed", "lot_code": "MO/00042"}])
    c.sync_orders()
    assert next(iter(v.orders.values()))["lotCode"] == "MO/00042"

    c, _, v = _connector([{"id": 43, "product_ref": "BIKE-001", "qty": 1, "state": "confirmed"}])
    c.sync_orders()
    assert next(iter(v.orders.values()))["lotCode"] is None


def test_release_is_idempotent():
    c, _, v = _connector([{"id": 42, "product_ref": "BIKE-001", "qty": 5, "state": "confirmed"}])
    c.sync_orders()
    c.sync_orders()                     # second pass must not duplicate
    assert len(v.orders) == 1


def test_release_skips_unmapped_product():
    c, _, v = _connector([{"id": 7, "product_ref": "UNKNOWN", "qty": 3, "state": "confirmed"}])
    assert c.sync_orders() == 0 and v.orders == {}


def test_release_skips_wrong_state():
    c, _, v = _connector([{"id": 7, "product_ref": "BIKE-001", "qty": 3, "state": "draft"}])
    assert c.sync_orders() == 0 and v.orders == {}


def test_release_skips_zero_qty():
    c, _, v = _connector([{"id": 7, "product_ref": "BIKE-001", "qty": 0, "state": "confirmed"}])
    assert c.sync_orders() == 0 and v.orders == {}


# --- completions --------------------------------------------------------

def test_completion_marks_done_and_acks():
    c, erp, v = _connector([])
    v.outbox = [_event("e1", "order.completed", "odoo", "42")]
    assert c.sync_completions() == 1
    assert erp.done == ["42"] and v.acked == ["e1"]
    assert v.outbox[0]["status"] == "delivered"


def test_cancellation_cancels_and_acks():
    c, erp, v = _connector([])
    v.outbox = [_event("e1", "order.cancelled", "odoo", "42")]
    assert c.sync_completions() == 1
    assert erp.cancelled == ["42"] and v.acked == ["e1"]


def test_completion_ignores_foreign_source():
    c, erp, v = _connector([], source="odoo")
    v.outbox = [_event("e1", "order.completed", "netsuite", "42")]
    assert c.sync_completions() == 0
    assert erp.done == [] and v.acked == []     # left for the netsuite connector


def test_failed_delivery_is_not_acked():
    c, erp, v = _connector([])

    def boom(ref):
        raise RuntimeError("ERP down")
    erp.mark_done = boom
    v.outbox = [_event("e1", "order.completed", "odoo", "42")]
    assert c.sync_completions() == 0
    assert v.acked == [] and v.outbox[0]["status"] == "pending"   # retried next cycle


def test_completion_drains_when_handler_absent():
    # A store connector (no mark_done/cancel) still drains completion events.
    v = FakeTaktline()
    erp = FakeStore(orders=[], cancellations=[])   # no mark_done attribute
    c = Connector(erp, v, Mapping({}), source="shopify", order_states=())
    v.outbox = [_event("e1", "order.completed", "shopify", "42")]
    assert c.sync_completions() == 1
    assert v.acked == ["e1"]                        # drained, nothing pushed back


# --- ERP-initiated cancellations (Shopify/Woo cancel & refund) ----------

def test_sync_cancellations_cancels_by_ref():
    v = FakeTaktline()
    erp = FakeStore(orders=[{"id": "S1", "product_ref": "BIKE-001", "qty": 1, "state": "open"}],
                    cancellations=["S1", "S2"])
    c = Connector(erp, v, Mapping({"BIKE-001": "tmpl-1"}), source="shopify", order_states=())
    c.sync_orders()                                 # S1 released
    assert c.sync_cancellations() == 1              # S1 cancelled; S2 unknown → benign
    assert ("shopify", "S1") in v.cancelled and ("shopify", "S2") in v.cancelled


def test_sync_cancellations_noop_without_lister():
    # Odoo/NetSuite-style ERP (no list_cancellations) → nothing to do.
    c, _, v = _connector([])
    assert c.sync_cancellations() == 0 and v.cancelled == []


def test_run_once_returns_three_counts():
    c, _, v = _connector([{"id": 1, "product_ref": "BIKE-001", "qty": 2, "state": "confirmed"}])
    v.outbox = [_event("e1", "order.completed", "odoo", "99")]
    # (released, cancelled, delivered) — FakeErp has no list_cancellations → 0
    assert c.run_once() == (1, 0, 1)
