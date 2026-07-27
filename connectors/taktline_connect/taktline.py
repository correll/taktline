"""Thin Taktline API client — the *one* dependency every connector shares.

Authenticates with a company-scoped API key (``Authorization: Bearer tk_...``)
created under Settings → Integrations. The key only needs the ``orders`` scope;
it can release orders and drain the completion outbox, nothing else. This is the
frozen canonical contract — connectors never touch any other endpoint, which is
what keeps them thin.
"""
from __future__ import annotations

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
        return r.json() if r.content else None

    # --- release ---------------------------------------------------------
    def create_order(self, template_id: str, quantity: int, external_ref: str, source: str,
                     lot_code: str | None = None) -> dict:
        """Release a pull order. Idempotent server-side on (source, externalRef):
        re-posting the same ref returns the existing order instead of duplicating.

        ``lot_code`` is the human reference printed on the released Kanban card(s)
        (e.g. a Shopify order name "#1001"); when omitted the server uses the
        externalRef, so the lot always traces back to its ERP order."""
        body = {
            "productTemplateId": template_id,
            "quantity": quantity,
            "source": source,
            "externalRef": external_ref,
        }
        if lot_code:
            body["lotCode"] = lot_code
        return self._post("/orders/", body)

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
    def list_outbox(self, status: str = "pending") -> list[dict]:
        return self._get(f"/orders/outbox?status={status}")

    def ack_outbox(self, event_id: str) -> None:
        self._post(f"/orders/outbox/{event_id}/ack")
