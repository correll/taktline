"""Xero connector — accepted Quotes signal production of their line items.

Like QBO, Xero has no manufacturing order; an accepted Quote is a reasonable
"make this" signal. Each line item → a Taktline release keyed
``"Quote:<quoteId>:<index>"``, mapped by the line's Item Code (PRODUCT_MAPPING).
"""
from __future__ import annotations

import logging

import requests

from .config import Config
from .core import Connector, Mapping
from .oauth import load_refresh_token, refresh_access_token
from .taktline import TaktlineClient

log = logging.getLogger("taktline_connect")
TOKEN_URL = "https://identity.xero.com/connect/token"
API_BASE = "https://api.xero.com/api.xro/2.0"
PAGE_SIZE = 100
MAX_PAGES = 200


def orders_from_xero(quotes: list[dict]) -> list[dict]:
    """Pure mapping (unit-tested): Xero quotes → release rows."""
    out = []
    for q in quotes:
        qid = q.get("QuoteID") or q.get("QuoteNumber")
        for i, li in enumerate(q.get("LineItems", [])):
            item = li.get("Item") or {}
            out.append({
                # LineItemID is stable across edits; the positional index is not.
                # Keyed on the index, inserting a line at the top shifts every
                # ref: the new line inherits an already-released ref (so it never
                # produces) and the last line gets a fresh one (so it produces twice).
                "id": f"Quote:{qid}:{li.get('LineItemID') or i}",
                "product_ref": item.get("Code") or li.get("Description"),
                "qty": int(float(li.get("Quantity") or 0)),
                "state": q.get("Status"),
                "lot_code": q.get("QuoteNumber"),
            })
    return out


class XeroClient:
    def __init__(self, cfg: Config, timeout: float = 30.0):
        if not (cfg.xero_tenant_id and cfg.xero_refresh_token):
            raise RuntimeError("XERO_TENANT_ID and XERO_REFRESH_TOKEN are required.")
        self.cfg = cfg
        self.timeout = timeout
        self.tenant = cfg.xero_tenant_id
        # Xero rotates on every refresh, so the env value is stale after the
        # first cycle; the persisted one is the only way to survive a restart.
        self.refresh_token = load_refresh_token("xero", cfg.xero_refresh_token)
        self.access = None

    def _auth(self):
        self.access, self.refresh_token = refresh_access_token(
            TOKEN_URL, self.cfg.xero_client_id, self.cfg.xero_client_secret,
            self.refresh_token, self.timeout, provider="xero")

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
            page = 1
            while page <= MAX_PAGES:
                quotes = self._get("/Quotes", Status=st, page=page).get("Quotes", [])
                rows += orders_from_xero(quotes)
                if len(quotes) < PAGE_SIZE:      # Xero caps /Quotes at 100 per page
                    break
                page += 1
            else:
                log.warning("xero: stopped after %d pages of %s quotes", MAX_PAGES, st)
        return rows


def build(cfg: Config) -> Connector:
    return Connector(
        erp=XeroClient(cfg),
        taktline=TaktlineClient(cfg.taktline_url, cfg.taktline_api_key),
        mapping=Mapping(cfg.product_mapping),
        source="xero",
        order_states=cfg.order_states,
    )
