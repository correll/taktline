"""ERP-agnostic orchestration. Everything here is testable with fakes — no
network, no ERP SDK. An ERP client is anything implementing the small protocol
below; the shared :class:`Connector` drives it against Taktline.

    ERP client protocol
    --------------------
    list_orders(states)  -> list[{'id', 'product_ref', 'qty', 'state', 'lot_code'?}]   (required)
        'lot_code' is optional — a human order reference (e.g. Shopify "#1001")
        printed on the released Kanban card; the server falls back to the id.
    mark_done(external_ref) -> None      # order finished in Taktline → close in ERP
    cancel(external_ref)    -> None      # order cancelled in Taktline → cancel in ERP

    Optional (implement when the ERP is the source of truth for cancellations,
    e.g. Shopify/WooCommerce — a shopper cancels or refunds in the store):
    list_cancellations(states) -> list[external_ref]   # refs cancelled in the ERP

    mark_done / cancel are optional too — a connector that only feeds orders in
    (and never reports completion back) can omit them.
"""
from __future__ import annotations

import logging

log = logging.getLogger("taktline_connect")


class Mapping:
    """Config-owned map: ERP product ref → Taktline lot-template id.

    We map to the template *id* (not name) on purpose: an ``orders``-scoped API
    key cannot list templates, so the connector must never need a lookup. Admins
    read the ids off Settings → Integrations → Product ids and drop them here.
    """

    def __init__(self, product_map: dict[str, str]):
        self.product_map = product_map or {}

    def resolve(self, product_ref: str | None) -> str | None:
        if product_ref is None:
            return None
        return self.product_map.get(product_ref)


class Connector:
    def __init__(self, erp, taktline, mapping: Mapping, source: str, order_states=()):
        self.erp = erp
        self.taktline = taktline
        self.mapping = mapping
        self.source = source
        self.order_states = tuple(order_states)

    # --- ERP → Taktline: release pull orders -----------------------------
    def sync_orders(self) -> int:
        released = 0
        for o in self.erp.list_orders(self.order_states):
            ref = str(o["id"])
            template_id = self.mapping.resolve(o.get("product_ref"))
            if not template_id:
                log.warning("no template mapping for product %r (order %s) — skipping",
                            o.get("product_ref"), ref)
                continue
            qty = int(o.get("qty") or 0)
            if qty < 1:
                continue
            order = self.taktline.create_order(template_id, qty, external_ref=ref,
                                               source=self.source, lot_code=o.get("lot_code"))
            log.info("released %s order %s → %s (%s ×%d)",
                     self.source, ref, order.get("id"), o.get("product_ref"), qty)
            released += 1
        return released

    # --- ERP → Taktline: propagate ERP-initiated cancellations -----------
    def sync_cancellations(self) -> int:
        """For stores where the shopper cancels/refunds (Shopify, Woo): pull the
        cancelled refs and cancel the matching Taktline orders by (source, ref).
        No-op for ERPs that don't source cancellations."""
        lister = getattr(self.erp, "list_cancellations", None)
        if lister is None:
            return 0
        cancelled = 0
        for ref in lister(self.order_states):
            try:
                if self.taktline.cancel_by_ref(self.source, str(ref)):
                    log.info("%s: cancelled %s (ERP-initiated)", self.source, ref)
                    cancelled += 1
            except Exception as e:  # noqa: BLE001 — one bad ref shouldn't stop the rest
                log.error("cancel of %s failed: %s", ref, e)
        return cancelled

    # --- Taktline → ERP: drain completions/cancellations -----------------
    def sync_completions(self) -> int:
        delivered = 0
        for ev in self.taktline.list_outbox("pending"):
            payload = ev.get("payload") or {}
            if payload.get("source") != self.source:
                continue  # another connector owns this event
            ref = payload.get("externalRef")
            if not ref:
                self.taktline.ack_outbox(ev["id"])   # nothing to deliver; clear it
                continue
            try:
                etype = ev.get("eventType")
                if etype == "order.completed":
                    handler = getattr(self.erp, "mark_done", None)
                elif etype == "order.cancelled":
                    handler = getattr(self.erp, "cancel", None)
                else:
                    handler = None
                if handler is not None:
                    handler(ref)
                    log.info("%s: delivered %s for %s", self.source, etype, ref)
                else:
                    log.info("%s: %s not consumed by this connector — draining %s",
                             self.source, etype, ref)
                self.taktline.ack_outbox(ev["id"])
                delivered += 1
            except Exception as e:  # noqa: BLE001 — leave un-acked so it retries next cycle
                log.error("delivery failed for event %s (ref %s): %s — will retry", ev["id"], ref, e)
        return delivered

    def run_once(self) -> tuple[int, int, int]:
        return self.sync_orders(), self.sync_cancellations(), self.sync_completions()
