"""Xero connector — accepted Quotes signal production of their line items.

Like QBO, Xero has no manufacturing order; an accepted Quote is a reasonable
"make this" signal. Each line item → a Taktline release keyed
``"Quote:<quoteId>:<index>"``, mapped by the line's Item Code (PRODUCT_MAPPING).
"""
from __future__ import annotations

import requests

from .config import Config
from .core import Connector, Mapping
from .oauth import refresh_access_token
from .taktline import TaktlineClient

TOKEN_URL = "https://identity.xero.com/connect/token"
API_BASE = "https://api.xero.com/api.xro/2.0"


def orders_from_xero(quotes: list[dict]) -> list[dict]:
    """Pure mapping (unit-tested): Xero quotes → release rows."""
    out = []
    for q in quotes:
        qid = q.get("QuoteID") or q.get("QuoteNumber")
        for i, li in enumerate(q.get("LineItems", [])):
            item = li.get("Item") or {}
            out.append({
                "id": f"Quote:{qid}:{i}",
                "product_ref": item.get("Code") or li.get("Description"),
                "qty": int(float(li.get("Quantity") or 0)),
                "state": q.get("Status"),
            })
    return out


class XeroClient:
    def __init__(self, cfg: Config, timeout: float = 30.0):
        if not (cfg.xero_tenant_id and cfg.xero_refresh_token):
            raise RuntimeError("XERO_TENANT_ID and XERO_REFRESH_TOKEN are required.")
        self.cfg = cfg
        self.timeout = timeout
        self.tenant = cfg.xero_tenant_id
        self.refresh_token = cfg.xero_refresh_token
        self.access = None

    def _auth(self):
        self.access, self.refresh_token = refresh_access_token(
            TOKEN_URL, self.cfg.xero_client_id, self.cfg.xero_client_secret, self.refresh_token, self.timeout)

    def _get(self, path: str, **params) -> dict:
        if self.access is None:
            self._auth()
        def call():
            return requests.get(API_BASE + path, timeout=self.timeout, params=params,
                                headers={"Authorization": f"Bearer {self.access}",
                                         "Xero-tenant-id": self.tenant, "Accept": "application/json"})
        r = call()
        if r.status_code == 401:
            self._auth()
            r = call()
        r.raise_for_status()
        return r.json()

    def list_orders(self, states) -> list[dict]:
        rows = []
        for st in (tuple(states) or ("ACCEPTED",)):
            rows += orders_from_xero(self._get("/Quotes", Status=st).get("Quotes", []))
        return rows


def build(cfg: Config) -> Connector:
    return Connector(
        erp=XeroClient(cfg),
        taktline=TaktlineClient(cfg.taktline_url, cfg.taktline_api_key),
        mapping=Mapping(cfg.product_mapping),
        source="xero",
        order_states=cfg.order_states,
    )
