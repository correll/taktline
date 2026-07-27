"""WooCommerce connector — WP REST (wc/v3) orders → Taktline. Shopify's twin.

processing order line item   ──►  Taktline pull order (one per line item)
cancelled / refunded order   ──►  Taktline order cancelled
Taktline order completed     ──►  Woo order status = completed

Auth is HTTP Basic with the store's REST consumer key/secret (HTTPS assumed).
"""
from __future__ import annotations

import logging

import requests

from .config import Config
from .core import Connector, Mapping
from .taktline import TaktlineClient

log = logging.getLogger("taktline_connect")
DEFAULT_STATES = ("processing",)
MAX_PAGES = 200


def _line_ref(order_id, line_id) -> str:
    return f"{order_id}:{line_id}"


def orders_from_woo(orders: list[dict]) -> list[dict]:
    """Pure mapping (unit-tested): Woo orders → release rows."""
    out = []
    for o in orders:
        # Woo's human order number (usually == id, but can differ with plugins).
        num = o.get("number") or o.get("id")
        code = f"#{num}" if num is not None else None
        for li in o.get("line_items", []):
            out.append({
                "id": _line_ref(o.get("id"), li.get("id")),
                "product_ref": li.get("sku") or li.get("name"),
                "qty": int(li.get("quantity") or 0),
                "state": o.get("status"),
                "lot_code": code,
            })
    return out


def cancel_refs_from_woo(orders: list[dict]) -> list[str]:
    return [_line_ref(o.get("id"), li.get("id"))
            for o in orders for li in o.get("line_items", [])]


class WooClient:
    def __init__(self, cfg: Config, timeout: float = 30.0):
        if not cfg.woo_url:
            raise RuntimeError("WOO_URL is required (e.g. https://store.example.com).")
        self.base = cfg.woo_url.rstrip("/") + "/wp-json/wc/v3"
        self.auth = (cfg.woo_consumer_key, cfg.woo_consumer_secret)
        self.timeout = timeout

    def _orders(self, status: str) -> list[dict]:
        """Every page, oldest first. Woo defaults to newest-first, so a single
        page of a >100-order backlog would show only the newest — and because an
        order leaves ``processing`` only when Taktline completes it, the oldest
        work would never be released at all."""
        out, page = [], 1
        while page <= MAX_PAGES:
            r = requests.get(self.base + "/orders", auth=self.auth, timeout=self.timeout,
                             params={"status": status, "per_page": 100, "page": page,
                                     "orderby": "date", "order": "asc"})
            r.raise_for_status()
            rows = r.json()
            out += rows
            total = int(r.headers.get("X-WP-TotalPages") or 1)
            if not rows or page >= total:
                return out
            page += 1
        log.warning("woocommerce: stopped after %d pages (%d orders)", MAX_PAGES, len(out))
        return out

    def list_orders(self, states) -> list[dict]:
        out = []
        for s in (tuple(states) or DEFAULT_STATES):
            out += orders_from_woo(self._orders(s))
        return out

    def list_cancellations(self, states) -> list[str]:
        refs = []
        for s in ("cancelled", "refunded"):
            refs += cancel_refs_from_woo(self._orders(s))
        return refs

    def mark_done(self, external_ref: str) -> None:
        order_id = str(external_ref).split(":")[0]
        r = requests.put(self.base + f"/orders/{order_id}", auth=self.auth,
                         json={"status": "completed"}, timeout=self.timeout)
        r.raise_for_status()


def build(cfg: Config) -> Connector:
    return Connector(
        erp=WooClient(cfg),
        taktline=TaktlineClient(cfg.taktline_url, cfg.taktline_api_key),
        mapping=Mapping(cfg.product_mapping),
        source="woocommerce",
        order_states=cfg.order_states,
    )
