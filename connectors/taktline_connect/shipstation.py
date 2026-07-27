"""ShipStation connector — orders awaiting fulfilment that need to be made.

awaiting_shipment order item  ──►  Taktline pull order (one per item)
Taktline order completed       ──►  ShipStation order marked shipped

Auth is HTTP Basic (API key + secret). Item ``sku`` maps via PRODUCT_MAPPING.
`mark_done` marks the order shipped — adjust to an order tag / hold-release if
"manufactured" shouldn't mean "shipped" in your workflow.
"""
from __future__ import annotations

import requests

from .config import Config
from .core import Connector, Mapping
from .taktline import TaktlineClient

BASE = "https://ssapi.shipstation.com"


def orders_from_shipstation(orders: list[dict]) -> list[dict]:
    """Pure mapping (unit-tested): ShipStation orders → release rows."""
    out = []
    for o in orders:
        oid = o.get("orderId")
        for it in o.get("items", []):
            out.append({
                "id": f"{oid}:{it.get('sku') or it.get('orderItemId')}",
                "product_ref": it.get("sku") or it.get("name"),
                "qty": int(it.get("quantity") or 0),
                "state": o.get("orderStatus"),
            })
    return out


class ShipStationClient:
    def __init__(self, cfg: Config, timeout: float = 30.0):
        if not (cfg.shipstation_api_key and cfg.shipstation_api_secret):
            raise RuntimeError("SHIPSTATION_API_KEY and SHIPSTATION_API_SECRET are required.")
        self.auth = (cfg.shipstation_api_key, cfg.shipstation_api_secret)
        self.timeout = timeout

    def list_orders(self, states) -> list[dict]:
        statuses = tuple(states) or ("awaiting_shipment",)
        rows = []
        for st in statuses:
            r = requests.get(f"{BASE}/orders", auth=self.auth, timeout=self.timeout,
                             params={"orderStatus": st, "pageSize": 250})
            r.raise_for_status()
            rows += orders_from_shipstation(r.json().get("orders", []))
        return rows

    def mark_done(self, external_ref: str) -> None:
        order_id = str(external_ref).split(":")[0]
        r = requests.post(f"{BASE}/orders/markasshipped", auth=self.auth, timeout=self.timeout,
                          json={"orderId": int(order_id), "notifyCustomer": False})
        r.raise_for_status()


def build(cfg: Config) -> Connector:
    return Connector(
        erp=ShipStationClient(cfg),
        taktline=TaktlineClient(cfg.taktline_url, cfg.taktline_api_key),
        mapping=Mapping(cfg.product_mapping),
        source="shipstation",
        order_states=cfg.order_states,
    )
