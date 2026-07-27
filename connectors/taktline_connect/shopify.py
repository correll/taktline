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

import requests

from .config import Config
from .core import Connector, Mapping
from .taktline import TaktlineClient


def _line_ref(order_id, line_id) -> str:
    return f"{order_id}:{line_id}"


def orders_from_shopify(orders: list[dict]) -> list[dict]:
    """Pure mapping (unit-tested): Shopify orders → release rows."""
    out = []
    for o in orders:
        # Friendly order reference for the shop floor: "#1001" (name) or the order
        # number; falls back server-side to the composite id if absent.
        code = o.get("name") or (f"#{o['order_number']}" if o.get("order_number") else None)
        for li in o.get("line_items", []):
            out.append({
                "id": _line_ref(o.get("id"), li.get("id")),
                "product_ref": li.get("sku") or li.get("title"),
                "qty": int(li.get("quantity") or 0),
                "state": o.get("financial_status"),
                "lot_code": code,
            })
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

    def _orders(self, **params) -> list[dict]:
        r = requests.get(self.base + "/orders.json", headers=self.headers,
                         params={"limit": 250, **params}, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("orders", [])

    def list_orders(self, states) -> list[dict]:
        # paid + still open (unfulfilled) → releasable
        return orders_from_shopify(self._orders(status="open", financial_status="paid"))

    def list_cancellations(self, states) -> list[str]:
        refs = cancel_refs_from_shopify(self._orders(status="cancelled"))
        refs += cancel_refs_from_shopify(self._orders(status="any", financial_status="refunded"))
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
