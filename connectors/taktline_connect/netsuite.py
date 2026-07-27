"""NetSuite connector — Work Orders via SuiteTalk REST (SuiteQL) with
token-based auth (OAuth 1.0a, HMAC-SHA256).

NetSuite Work Order  ──(pending build)──►  Taktline pull order
Taktline order.completed  ──────────────►  NetSuite assembly build (WO closed)
Taktline order.cancelled  ──────────────►  NetSuite Work Order closed

The SuiteQL shape and the assemblyBuild body are account-configuration specific
(custom fields, subsidiaries, locations). Treat the queries here as a working
starting point and tune ``list_orders`` / ``mark_done`` for your instance — the
orchestration in :class:`~taktline_connect.core.Connector` does not change.

Auth uses Token-Based Authentication (TBA): a NetSuite integration record gives
you a consumer key/secret, and a per-user access token gives you token id/secret.
"""
from __future__ import annotations

import requests
from requests_oauthlib import OAuth1

from .config import Config
from .core import Connector, Mapping
from .taktline import TaktlineClient

DEFAULT_STATES = ("Work Order:Pending Build",)   # NetSuite WO status text; tune per account


class NetSuiteClient:
    def __init__(self, cfg: Config, timeout: float = 45.0):
        if not cfg.ns_account:
            raise RuntimeError("NETSUITE_ACCOUNT is required.")
        self.timeout = timeout
        host = cfg.ns_account.lower().replace("_", "-")
        self.base = f"https://{host}.suitetalk.api.netsuite.com/services/rest"
        # realm must be the UPPER-cased account id (e.g. 1234567 or 1234567_SB1)
        self.auth = OAuth1(
            cfg.ns_consumer_key, cfg.ns_consumer_secret,
            cfg.ns_token_id, cfg.ns_token_secret,
            signature_method="HMAC-SHA256", realm=cfg.ns_account.upper(),
        )

    def _suiteql(self, query: str) -> list[dict]:
        rows, offset = [], 0
        while True:
            r = requests.post(
                f"{self.base}/query/v1/suiteql?limit=1000&offset={offset}",
                auth=self.auth, timeout=self.timeout,
                headers={"Prefer": "transient", "Content-Type": "application/json"},
                json={"q": query},
            )
            r.raise_for_status()
            body = r.json()
            rows.extend(body.get("items", []))
            if not body.get("hasMore"):
                return rows
            offset += 1000

    def list_orders(self, states) -> list[dict]:
        states = tuple(states) or DEFAULT_STATES
        in_list = ",".join("'%s'" % s.replace("'", "''") for s in states)
        # Work orders (transaction type 'WorkOrd') with their assembly item + qty.
        rows = self._suiteql(
            "SELECT t.id AS id, t.tranid AS tranid, "
            "       BUILTIN.DF(t.status) AS status, "
            "       i.itemid AS product_ref, "
            "       t.quantity AS qty "
            "FROM transaction t "
            "JOIN item i ON i.id = t.custbody_assembly_item OR i.id = t.entity "
            f"WHERE t.type = 'WorkOrd' AND BUILTIN.DF(t.status) IN ({in_list})"
        )
        out = []
        for r in rows:
            out.append({
                "id": r.get("id"),
                "product_ref": r.get("product_ref"),
                "qty": int(float(r.get("qty") or 0)),
                "state": r.get("status"),
            })
        return out

    def mark_done(self, external_ref: str) -> None:
        # Build the assembly from the work order — transforms WO → assemblyBuild.
        r = requests.post(
            f"{self.base}/record/v1/assemblyBuild",
            auth=self.auth, timeout=self.timeout,
            headers={"Content-Type": "application/json"},
            json={"workOrder": {"id": str(external_ref)}},
        )
        r.raise_for_status()

    def cancel(self, external_ref: str) -> None:
        r = requests.patch(
            f"{self.base}/record/v1/workOrder/{external_ref}",
            auth=self.auth, timeout=self.timeout,
            headers={"Content-Type": "application/json"},
            json={"status": {"id": "H"}},   # 'H' = Closed on the WO status list
        )
        r.raise_for_status()


def build(cfg: Config) -> Connector:
    return Connector(
        erp=NetSuiteClient(cfg),
        taktline=TaktlineClient(cfg.taktline_url, cfg.taktline_api_key),
        mapping=Mapping(cfg.product_mapping),
        source="netsuite",
        order_states=cfg.order_states,
    )
