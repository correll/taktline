"""Thin Taktline API client — the *one* dependency every connector shares.

Authenticates with a company-scoped API key (``Authorization: Bearer tk_...``)
created under Settings → Integrations. The key only needs the ``orders`` scope;
it can release orders and drain the completion outbox, nothing else. This is the
frozen canonical contract — connectors never touch any other endpoint, which is
what keeps them thin.
"""
from __future__ import annotations

from urllib.parse import quote

import requests


class TaktlineClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {api_key}"})

    def _get(self, path: str):
        r = self.s.get(self.base + path, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict | None = None):
        r = self.s.post(self.base + path, json=body, timeout=self.timeout)
        r.raise_for_status()
        return (r.json() if r.content else None), r.status_code

    # --- release ---------------------------------------------------------
    def create_order(self, template_id: str, quantity: int, external_ref: str, source: str,
                     lot_code: str | None = None, attributes: dict | None = None) -> dict:
        """Release a pull order. Idempotent server-side on (source, externalRef):
        re-posting the same ref returns the existing order instead of duplicating.

        ``lot_code`` is the human reference printed on the released Kanban card(s)
        (e.g. a Shopify order name "#1001"); when omitted the server uses the
        externalRef, so the lot always traces back to its ERP order.

        The returned dict carries ``created``: True when this call released the
        order (HTTP 201), False when the server returned one that already existed
        (200). Connectors re-post their whole open backlog every cycle, so this is
        what separates a real release from a redelivery."""
        body = {
            "productTemplateId": template_id,
            "quantity": quantity,
            "source": source,
            "externalRef": external_ref,
        }
        if lot_code:
            body["lotCode"] = lot_code
        if attributes:
            # Flat scalar map (customer, due date, ship-to…) — the server stamps
            # it onto every seeded Kanban card and echoes it back at handoff.
            body["attributes"] = attributes
        order, status = self._post("/orders/", body)
        return {**(order or {}), "created": status == 201}

    def cancel_by_ref(self, source: str, external_ref: str) -> bool:
        """Cancel the order matching (source, externalRef). Returns False if no
        such order exists (404) — benign for a cancel/refund of something that was
        never released. Idempotent: re-cancelling an already-cancelled order 200s."""
        r = self.s.post(self.base + "/orders/cancel",
                        json={"source": source, "externalRef": external_ref},
                        timeout=self.timeout)
        if r.status_code == 404:
            return False
        r.raise_for_status()
        return True

    # --- completions -----------------------------------------------------
    def list_outbox(self, status: str = "pending", source: str | None = None) -> list[dict]:
        """Pending delivery events. Pass ``source`` to see only this connector's
        own events — the unfiltered window is shared with releases nobody acks
        (manual, CSV), which would eventually crowd out real completions."""
        path = f"/orders/outbox?status={status}"
        if source:
            path += f"&source={quote(source)}"
        return self._get(path)

    def ack_outbox(self, event_id: str) -> None:
        self._post(f"/orders/outbox/{event_id}/ack")

    def fail_outbox(self, event_id: str) -> dict | None:
        """Record a failed delivery attempt; the server parks the event as
        'failed' once it has burned through its retries."""
        return self._post(f"/orders/outbox/{event_id}/fail")[0]
