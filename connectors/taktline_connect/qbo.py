"""QuickBooks Online connector — a sales document (Estimate by default) is the
signal to make its line items.

QBO is accounting, not manufacturing, so there's no "work order": the admin
chooses which document type + status means "produce this" (QBO_DOC). Each
SalesItemLine → a Taktline release, keyed ``"<doc>:<docId>:<lineId>"`` and mapped
by ItemRef name (put those in PRODUCT_MAPPING).
"""
from __future__ import annotations

import requests

from .config import Config
from .core import Connector, Mapping
from .oauth import refresh_access_token
from .taktline import TaktlineClient

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"


def orders_from_qbo(docs: list[dict], doc_type: str) -> list[dict]:
    """Pure mapping (unit-tested): QBO sales docs → release rows."""
    out = []
    for d in docs:
        did = d.get("Id")
        for ln in d.get("Line", []):
            det = ln.get("SalesItemLineDetail")
            if not det:
                continue                       # sub-total / description lines
            item = det.get("ItemRef") or {}
            out.append({
                "id": f"{doc_type}:{did}:{ln.get('Id')}",
                "product_ref": item.get("name") or item.get("value"),
                "qty": int(float(det.get("Qty") or 0)),
                "state": d.get("TxnStatus") or "Accepted",
            })
    return out


class QboClient:
    def __init__(self, cfg: Config, timeout: float = 30.0):
        if not (cfg.qbo_realm_id and cfg.qbo_refresh_token):
            raise RuntimeError("QBO_REALM_ID and QBO_REFRESH_TOKEN are required.")
        self.cfg = cfg
        self.timeout = timeout
        self.realm = cfg.qbo_realm_id
        self.doc = cfg.qbo_doc
        host = "sandbox-quickbooks" if cfg.qbo_env == "sandbox" else "quickbooks"
        self.base = f"https://{host}.api.intuit.com/v3/company/{self.realm}"
        self.refresh_token = cfg.qbo_refresh_token
        self.access = None

    def _auth(self):
        self.access, self.refresh_token = refresh_access_token(
            TOKEN_URL, self.cfg.qbo_client_id, self.cfg.qbo_client_secret, self.refresh_token, self.timeout)

    def _query(self, sql: str) -> dict:
        if self.access is None:
            self._auth()
        def call():
            return requests.get(f"{self.base}/query", timeout=self.timeout,
                                headers={"Authorization": f"Bearer {self.access}", "Accept": "application/json"},
                                params={"query": sql, "minorversion": 65})
        r = call()
        if r.status_code == 401:               # access token expired → refresh once
            self._auth()
            r = call()
        r.raise_for_status()
        return r.json().get("QueryResponse", {})

    def list_orders(self, states) -> list[dict]:
        statuses = tuple(states) or ("Accepted",)
        rows = []
        for st in statuses:
            qr = self._query(f"SELECT * FROM {self.doc} WHERE TxnStatus = '{st}'")
            rows += orders_from_qbo(qr.get(self.doc, []), self.doc)
        return rows


def build(cfg: Config) -> Connector:
    return Connector(
        erp=QboClient(cfg),
        taktline=TaktlineClient(cfg.taktline_url, cfg.taktline_api_key),
        mapping=Mapping(cfg.product_mapping),
        source="quickbooks",
        order_states=cfg.order_states,
    )
