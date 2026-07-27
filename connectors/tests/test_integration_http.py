"""Hermetic HTTP integration — real clients + real Connector over a live in-process
server standing in for both the ERP and Taktline. This exercises everything the
parsing tests don't: requests plumbing, auth headers, status handling, the
idempotent create/cancel/ack calls, OAuth token refresh, and the 401→retry path.

No external accounts, no running backend — the mock is the whole world.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from taktline_connect import qbo  # noqa: E402
from taktline_connect.config import Config  # noqa: E402
from taktline_connect.core import Connector, Mapping  # noqa: E402
from taktline_connect.qbo import QboClient  # noqa: E402
from taktline_connect.shopify import ShopifyClient  # noqa: E402
from taktline_connect.taktline import TaktlineClient  # noqa: E402


class State:
    def __init__(self):
        self.orders = {}          # (source, ref) -> order dict  (the "Taktline" side)
        self.outbox = []          # completion events
        self.shopify = {"open_paid": [], "cancelled": [], "refunded": []}
        self.fulfilled = []       # Shopify fulfillments created
        self.qbo_token_calls = 0
        self.qbo_query_calls = 0
        self.qbo_docs = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    @property
    def st(self) -> State:
        return self.server.state       # type: ignore[attr-defined]

    def _send(self, code, obj=None):
        self.send_response(code)
        if obj is not None:
            self.send_header("Content-Type", "application/json")
        self.end_headers()
        if obj is not None:
            self.wfile.write(json.dumps(obj).encode())

    def _raw(self):   # always drain the body so keep-alive connections stay clean
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # --- reads ----------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path, st = u.path, self.st
        if path.endswith("/orders.json"):                       # Shopify list
            status = (q.get("status") or [""])[0]
            fin = (q.get("financial_status") or [""])[0]
            key = "cancelled" if status == "cancelled" else ("refunded" if fin == "refunded" else "open_paid")
            return self._send(200, {"orders": st.shopify[key]})
        if path.endswith("fulfillment_orders.json"):            # Shopify fulfil lookup
            return self._send(200, {"fulfillment_orders": [{"id": 555, "status": "open"}]})
        if "/orders/outbox" in path:                            # Taktline outbox
            return self._send(200, [e for e in st.outbox if e["status"] == "pending"])
        if path.endswith("/query"):                             # QBO SuiteQL-ish
            st.qbo_query_calls += 1
            if st.qbo_query_calls == 1:
                return self._send(401, {"fault": "token expired"})   # force a refresh+retry
            return self._send(200, {"QueryResponse": {"Estimate": st.qbo_docs}})
        return self._send(404, {"detail": "no route"})

    # --- writes ---------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        st = self.st
        raw = self._raw()                                       # drain regardless of content-type
        if path.endswith("/tokens/bearer"):                     # QBO OAuth refresh (form-encoded)
            st.qbo_token_calls += 1
            return self._send(200, {"access_token": f"tok-{st.qbo_token_calls}", "refresh_token": "rt-next"})
        body = json.loads(raw) if raw else None                 # JSON routes below
        if path.endswith("/fulfillments.json"):                 # Shopify fulfil
            st.fulfilled.append(body)
            return self._send(201, {"fulfillment": {"status": "success"}})
        if path.endswith("/orders/cancel"):                     # Taktline cancel-by-ref
            o = st.orders.get((body["source"], body["externalRef"]))
            if not o:
                return self._send(404, {"detail": "Order not found"})
            o["status"] = "cancelled"
            return self._send(200, o)
        if "/outbox/" in path and path.endswith("/ack"):        # Taktline ack
            eid = path.split("/outbox/")[1].split("/ack")[0]
            for e in st.outbox:
                if e["id"] == eid:
                    e["status"] = "delivered"
            return self._send(204)
        if path.rstrip("/").endswith("/orders"):                # Taktline create (idempotent)
            key = (body["source"], body.get("externalRef"))
            if key not in st.orders:
                st.orders[key] = {"id": f"ord-{len(st.orders)}", "status": "released",
                                  "externalRef": body.get("externalRef"), "quantity": body["quantity"]}
            return self._send(201, st.orders[key])
        return self._send(404, {"detail": "no route"})


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.state = State()                                          # type: ignore[attr-defined]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        yield base, srv.state
    finally:
        srv.shutdown()


def _shopify_order(oid, line_id, sku, qty, financial="paid"):
    return {"id": oid, "financial_status": financial,
            "line_items": [{"id": line_id, "sku": sku, "title": sku, "quantity": qty}]}


# ── Shopify: full release → cancel → complete(=fulfil) loop over real HTTP ──

def test_shopify_full_loop(server):
    base, st = server
    st.shopify["open_paid"] = [_shopify_order(1001, 11, "BIKE", 2),
                               _shopify_order(2002, 22, "BIKE", 1)]

    cfg = Config(taktline_url=base, taktline_api_key="k",
                 product_mapping={"BIKE": "tmpl-1"},
                 shopify_shop="x", shopify_fulfill=True)
    erp = ShopifyClient(cfg)
    erp.base = f"{base}/admin/api/2024-01"                       # point at the mock
    conn = Connector(erp, TaktlineClient(base, "k"), Mapping(cfg.product_mapping), source="shopify")

    # phase 1 — both paid orders release (one Taktline order per line item)
    released, cancelled, delivered = conn.run_once()
    assert released == 2 and cancelled == 0 and delivered == 0
    assert set(st.orders) == {("shopify", "1001:11"), ("shopify", "2002:22")}

    # phase 2 — shopper cancels 2002 and pays-then-we-finish 1001
    st.shopify["open_paid"] = [_shopify_order(1001, 11, "BIKE", 2)]
    st.shopify["cancelled"] = [_shopify_order(2002, 22, "BIKE", 1)]
    st.outbox = [{"id": "e1", "eventType": "order.completed", "status": "pending",
                  "payload": {"source": "shopify", "externalRef": "1001:11"}}]

    released, cancelled, delivered = conn.run_once()
    assert released == 1                                         # 1001 re-pushed (idempotent server-side)
    assert len(st.orders) == 2                                  # …but no new Taktline order created
    assert cancelled == 1 and st.orders[("shopify", "2002:22")]["status"] == "cancelled"
    assert delivered == 1 and st.outbox[0]["status"] == "delivered"
    assert len(st.fulfilled) == 1                               # completion fulfilled the Shopify order


def test_shopify_cancel_of_unreleased_is_benign(server):
    base, st = server
    st.shopify["cancelled"] = [_shopify_order(9, 9, "BIKE", 1)]   # never released in Taktline
    cfg = Config(taktline_url=base, taktline_api_key="k", product_mapping={"BIKE": "tmpl-1"}, shopify_shop="x")
    erp = ShopifyClient(cfg); erp.base = f"{base}/admin/api/2024-01"
    conn = Connector(erp, TaktlineClient(base, "k"), Mapping(cfg.product_mapping), source="shopify")
    # cancel_by_ref returns False on 404 → counted as 0, no error
    assert conn.sync_cancellations() == 0


# ── QBO: OAuth refresh + 401-retry over real HTTP ───────────────────────

def test_qbo_oauth_refresh_and_401_retry(server, monkeypatch):
    base, st = server
    st.qbo_docs = [{"Id": "148", "TxnStatus": "Accepted", "Line": [
        {"Id": "1", "SalesItemLineDetail": {"ItemRef": {"name": "BIKE"}, "Qty": 3}},
    ]}]
    monkeypatch.setattr(qbo, "TOKEN_URL", f"{base}/oauth2/v1/tokens/bearer")

    cfg = Config(taktline_url=base, taktline_api_key="k",
                 qbo_client_id="c", qbo_client_secret="s",
                 qbo_refresh_token="rt0", qbo_realm_id="123")
    client = QboClient(cfg)
    client.base = f"{base}/v3/company/123"                       # point at the mock

    rows = client.list_orders(())
    assert rows == [{"id": "Estimate:148:1", "product_ref": "BIKE", "qty": 3, "state": "Accepted"}]
    # initial auth + one refresh after the forced 401; query hit twice (401 then 200)
    assert st.qbo_token_calls == 2 and st.qbo_query_calls == 2
    assert client.refresh_token == "rt-next"                     # rotated token captured
