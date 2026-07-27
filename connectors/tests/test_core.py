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
    """Mirrors the server contract: idempotent release that reports whether it
    created anything, a source-filtered outbox, ack, and a failure counter."""

    def __init__(self, reject: set | None = None):
        self.orders: dict = {}          # (source, ref) -> order
        self.outbox: list[dict] = []
        self.acked: list[str] = []
        self.failed: list[str] = []
        self.cancelled: list[tuple] = []
        self.reject = reject or set()   # external refs the server rejects (4xx)
        self.outbox_queries: list = []

    def create_order(self, template_id, quantity, external_ref, source, lot_code=None):
        if external_ref in self.reject:
            raise RuntimeError(f"404 Client Error for ref {external_ref}")
        key = (source, external_ref)
        if key in self.orders:          # server-side idempotency on (source, ref)
            return {**self.orders[key], "created": False}
        o = {"id": f"ord-{len(self.orders)}", "externalRef": external_ref,
             "quantity": quantity, "templateId": template_id, "lotCode": lot_code}
        self.orders[key] = o
        return {**o, "created": True}

    def cancel_by_ref(self, source, external_ref):
        self.cancelled.append((source, external_ref))
        return (source, external_ref) in self.orders   # False if unknown → benign

    def list_outbox(self, status="pending", source=None):
        self.outbox_queries.append((status, source))
        return [e for e in self.outbox
                if e["status"] == status
                and (source is None or (e["payload"] or {}).get("source") == source)]

    def ack_outbox(self, event_id):
        for e in self.outbox:
            if e["id"] == event_id:
                e["status"] = "delivered"
        self.acked.append(event_id)

    def fail_outbox(self, event_id):
        self.failed.append(event_id)
        for e in self.outbox:
            if e["id"] == event_id:
                e["attempts"] = e.get("attempts", 0) + 1
                return e
        return None


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


# --- resilience: one bad order must not wedge the connector -------------

def test_a_rejected_order_does_not_abort_the_cycle():
    """The failure mode this guards: a template deleted while still listed in
    PRODUCT_MAPPING makes the server 404 that one order. Unguarded, the raise
    escapes sync_orders and takes the *whole* cycle with it — the orders behind
    it never release and completions never drain. The ERP returns the same list
    next poll, so nothing ever recovers."""
    v = FakeTaktline(reject={"BAD"})
    erp = FakeErp([{"id": "BAD", "product_ref": "BIKE-001", "qty": 1, "state": "confirmed"},
                   {"id": "GOOD", "product_ref": "BIKE-001", "qty": 2, "state": "confirmed"}])
    c = Connector(erp, v, Mapping({"BIKE-001": "tmpl-1"}), source="odoo",
                  order_states=("confirmed",))
    v.outbox = [_event("e1", "order.completed", "odoo", "77")]

    released, _, delivered = c.run_once()

    assert released == 1                                  # GOOD still went out
    assert [k[1] for k in v.orders] == ["GOOD"]
    assert delivered == 1 and v.acked == ["e1"]           # completions still drained


def test_redelivered_order_is_not_counted_as_a_new_release():
    # A connector re-posts its whole open backlog every cycle; only a 201 is news.
    c, _, v = _connector([{"id": 42, "product_ref": "BIKE-001", "qty": 5, "state": "confirmed"}])
    assert c.sync_orders() == 1
    assert c.sync_orders() == 0                           # same order, already released
    assert len(v.orders) == 1


def test_numeric_product_ref_matches_a_json_string_key():
    # PRODUCT_MAPPING is JSON, so its keys are strings; an ERP reporting a numeric
    # product id would otherwise never map and be skipped forever.
    c, _, v = _connector([{"id": 1, "product_ref": 4471, "qty": 1, "state": "confirmed"}],
                         pmap={"4471": "tmpl-9"})
    assert c.sync_orders() == 1
    assert next(iter(v.orders.values()))["templateId"] == "tmpl-9"


def test_decimal_quantity_is_accepted():
    c, _, v = _connector([{"id": 1, "product_ref": "BIKE-001", "qty": "4.000",
                           "state": "confirmed"}])
    assert c.sync_orders() == 1
    assert next(iter(v.orders.values()))["quantity"] == 4


def test_zero_quantity_is_skipped_loudly(caplog):
    # A mis-mapped qty field reads as 0 for every order; silence would look healthy.
    c, _, v = _connector([{"id": 1, "product_ref": "BIKE-001", "qty": 0, "state": "confirmed"}])
    with caplog.at_level("WARNING"):
        assert c.sync_orders() == 0
    assert not v.orders
    assert any("quantity" in r.getMessage() for r in caplog.records)


# --- outbox hygiene ------------------------------------------------------

def test_outbox_is_polled_for_this_connector_only():
    """Events nobody can ack (manual UI releases, CSV imports) stay pending
    forever. Sharing one 500-row window with them eventually starves out this
    connector's own completions, so the query is scoped by source."""
    c, _, v = _connector([])
    v.outbox = [_event("mine", "order.completed", "odoo", "1"),
                _event("theirs", "order.completed", "manual", "2")]
    assert c.sync_completions() == 1
    assert v.outbox_queries == [("pending", "odoo")]
    assert v.acked == ["mine"]


def test_failed_delivery_records_an_attempt_server_side():
    class Boom(FakeErp):
        def mark_done(self, ref):
            raise RuntimeError("ERP down")

    v = FakeTaktline()
    c = Connector(Boom([]), v, Mapping({}), source="odoo", order_states=())
    v.outbox = [_event("e1", "order.completed", "odoo", "42")]
    assert c.sync_completions() == 0
    assert v.acked == []              # not acked — it will be retried
    assert v.failed == ["e1"]         # but the attempt is counted, so it can park
