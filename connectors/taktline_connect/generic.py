"""Generic REST connector — poll any JSON endpoint that lists orders, with no
new code. Map its fields via ``GENERIC_FIELDS``.

This is the thin-client on-ramp for the long tail of REST-first systems —
**Zoho Inventory, Cin7/DEAR, MRPeasy, Acumatica, Dynamics 365 Business Central,
ShipStation, QuickBooks Online, Xero**, or a home-grown app. If a system just
needs different auth, pagination, or a completion callback, subclass
:class:`GenericRestClient` and override ``_fetch`` / add ``mark_done`` — the
shared :class:`~taktline_connect.core.Connector` is unchanged.

Env:
    GENERIC_ORDERS_URL   endpoint returning a JSON list (or {orders|data|items:[...]})
    GENERIC_AUTH_HEADER  optional, e.g. "Bearer xyz" or "Basic ..."
    GENERIC_FIELDS       optional JSON remapping field names, e.g.
                         {"id":"orderNo","product_ref":"sku","qty":"quantity",
                          "lot_code":"orderName"}
"""
from __future__ import annotations

import json

import requests

from .config import Config
from .core import Connector, Mapping
from .taktline import TaktlineClient


def orders_from_generic(items: list[dict], fields: dict | None) -> list[dict]:
    """Pure mapping (unit-tested): raw JSON rows → release rows via a field map."""
    f = fields or {}
    fid = f.get("id", "id")
    fp = f.get("product_ref", "product_ref")
    fq = f.get("qty", "qty")
    fs = f.get("state", "state")
    fc = f.get("lot_code", "lot_code")
    out = []
    for it in items:
        out.append({
            "id": it.get(fid),
            "product_ref": it.get(fp),
            # Decimal quantities are the norm in this long tail ("4.000" from Zoho,
            # Cin7, Business Central); a bare int() would raise on the string.
            "qty": int(float(it.get(fq) or 0)),
            "state": it.get(fs),
            "lot_code": it.get(fc),
        })
    return out


def _unwrap(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("orders", "data", "items", "results"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


class GenericRestClient:
    def __init__(self, cfg: Config, timeout: float = 30.0):
        if not cfg.generic_orders_url:
            raise RuntimeError("GENERIC_ORDERS_URL is required.")
        self.url = cfg.generic_orders_url
        self.timeout = timeout
        self.headers = {"Authorization": cfg.generic_auth_header} if cfg.generic_auth_header else {}
        self.fields = json.loads(cfg.generic_fields) if cfg.generic_fields else {}

    def _fetch(self) -> list[dict]:
        r = requests.get(self.url, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return _unwrap(r.json())

    def list_orders(self, states) -> list[dict]:
        rows = orders_from_generic(self._fetch(), self.fields)
        if states:
            rows = [r for r in rows if r.get("state") in states]
        return rows


def build(cfg: Config) -> Connector:
    return Connector(
        erp=GenericRestClient(cfg),
        taktline=TaktlineClient(cfg.taktline_url, cfg.taktline_api_key),
        mapping=Mapping(cfg.product_mapping),
        source="generic",
        order_states=cfg.order_states,
    )
