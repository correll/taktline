"""Shopify connector — Admin REST orders → Taktline pull orders, with the
edit/cancel/refund path wired to Taktline's cancel-by-ref.

paid + open order line item  ──►  Taktline pull order (one per line item)
cancelled / refunded order   ──►  Taktline order cancelled (lots scrapped)

One Taktline order per Shopify *line item* (ref ``"<orderId>:<lineItemId>"``), so
a multi-product cart releases the right lot for each SKU. Completion back to
Shopify (fulfilment) is left as a documented hook — most retail flows don't need
the shop floor to fulfil.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests

from .config import Config
from .core import Connector, Mapping
from .taktline import TaktlineClient

log = logging.getLogger("taktline_connect")
MAX_PAGES = 200          # 50k orders per cycle — a runaway-cursor backstop


def _line_ref(order_id, line_id) -> str:
    return f"{order_id}:{line_id}"


def orders_from_shopify(orders: list[dict]) -> list[dict]:
    """Pure mapping (unit-tested): Shopify orders → release rows."""
    out = []
    for o in orders:
        # Friendly order reference for the shop floor: "#1001" (name) or the order
        # number; falls back server-side to the composite id if absent.
        code = o.get("name") or (f"#{o['order_number']}" if o.get("order_number") else None)
        # What the shop floor and the shipper need from the storefront: who it
        # is for and where it goes. Flat scalars — the server prints them on the
        # Kanban card and returns them to the sink at handoff.
        ship = o.get("shipping_address") or {}
        attrs = {k: v for k, v in {
            "customer": " ".join(filter(None, [(o.get("customer") or {}).get("first_name"),
                                               (o.get("customer") or {}).get("last_name")])) or None,
            "shipTo": ", ".join(filter(None, [ship.get("address1"), ship.get("city"),
                                              ship.get("zip"), ship.get("country_code")])) or None,
        }.items() if v}
        for li in o.get("line_items", []):
            row = {
                "id": _line_ref(o.get("id"), li.get("id")),
                "product_ref": li.get("sku") or li.get("title"),
                "qty": int(li.get("quantity") or 0),
                "state": o.get("financial_status"),
                "lot_code": code,
            }
            if attrs:
                row["attributes"] = attrs
            out.append(row)
    return out


def cancel_refs_from_shopify(orders: list[dict]) -> list[str]:
    return [_line_ref(o.get("id"), li.get("id"))
            for o in orders for li in o.get("line_items", [])]


class ShopifyClient:
    def __init__(self, cfg: Config, timeout: float = 30.0):
        if not cfg.shopify_shop:
            raise RuntimeError("SHOPIFY_SHOP is required (e.g. my-store.myshopify.com).")
        self.base = f"https://{cfg.shopify_shop}/admin/api/{cfg.shopify_api_version}"
        self.headers = {"X-Shopify-Access-Token": cfg.shopify_token}
        self.timeout = timeout
        self.fulfill = cfg.shopify_fulfill
        self.cancel_lookback_days = cfg.cancel_lookback_days

    @staticmethod
    def _next_link(resp) -> str | None:
        """Shopify pages with an opaque cursor in the ``Link`` header; the next
        URL already carries every filter, so it must be fetched bare."""
        for part in (resp.headers.get("Link") or "").split(","):
            bits = part.split(";")
            if len(bits) >= 2 and 'rel="next"' in bits[1]:
                return bits[0].strip().strip("<>")
        return None

    def _orders(self, **params) -> list[dict]:
        url, query, out = self.base + "/orders.json", {"limit": 250, **params}, []
        for _ in range(MAX_PAGES):
            r = requests.get(url, headers=self.headers, params=query, timeout=self.timeout)
            r.raise_for_status()
            out += r.json().get("orders", [])
            url = self._next_link(r)
            if not url:
                return out
            query = None          # the cursor URL is complete on its own
        log.warning("shopify: stopped after %d pages (%d orders) — some orders were "
                    "not read this cycle", MAX_PAGES, len(out))
        return out

    def list_orders(self, states) -> list[dict]:
        # paid + still open (unfulfilled) → releasable. ORDER_STATES, when set,
        # overrides the financial statuses considered releasable.
        out = []
        for fin in (tuple(states) or ("paid",)):
            out += orders_from_shopify(self._orders(status="open", financial_status=fin))
        return out

    def list_cancellations(self, states) -> list[str]:
        # Bounded by a lookback window: the cancelled/refunded sets only grow, and
        # re-cancelling the shop's entire history on every poll would spend the
        # whole API budget re-doing settled work.
        since = (datetime.now(timezone.utc)
                 - timedelta(days=self.cancel_lookback_days)).isoformat()
        refs = cancel_refs_from_shopify(self._orders(status="cancelled", updated_at_min=since))
        refs += cancel_refs_from_shopify(
            self._orders(status="any", financial_status="refunded", updated_at_min=since))
        return refs

    def mark_done(self, external_ref: str) -> None:
        """On Taktline completion, fulfil the Shopify order via the Fulfillment
        Orders API. Opt-in (SHOPIFY_FULFILL_ON_COMPLETE) — off by default so
        completions simply drain. Fulfils all open fulfillment orders for the
        order; refine to the single line item if you split fulfilment per SKU."""
        if not self.fulfill:
            return
        order_id = str(external_ref).split(":")[0]
        r = requests.get(f"{self.base}/orders/{order_id}/fulfillment_orders.json",
                         headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        open_fos = [fo["id"] for fo in r.json().get("fulfillment_orders", [])
                    if fo.get("status") in ("open", "in_progress")]
        if not open_fos:
            return
        payload = {"fulfillment": {"line_items_by_fulfillment_order":
                                   [{"fulfillment_order_id": fid} for fid in open_fos]}}
        requests.post(f"{self.base}/fulfillments.json", headers=self.headers,
                      json=payload, timeout=self.timeout).raise_for_status()


def build(cfg: Config) -> Connector:
    return Connector(
        erp=ShopifyClient(cfg),
        taktline=TaktlineClient(cfg.taktline_url, cfg.taktline_api_key),
        mapping=Mapping(cfg.product_mapping),
        source="shopify",
        order_states=cfg.order_states,
    )
