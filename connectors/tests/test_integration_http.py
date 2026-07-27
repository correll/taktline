"""Hermetic HTTP integration — real clients + real Connector over a live in-process
server standing in for both the ERP and Taktline. This exercises everything the
parsing tests don't: requests plumbing, auth headers, status handling, pagination,
the idempotent create/cancel/ack calls, OAuth token refresh, and the 401→retry path.

No external accounts, no running backend — the mock is the whole world.

The mock is deliberately **strict**: it enforces each ERP's real calling
convention (Odoo's ``execute_kw`` argument packing, Shopify's cursor `Link`
header, Woo's `X-WP-TotalPages`, NetSuite's `hasMore`) and only returns one page
at a time. A lenient mock would happily pass a client that the real system
rejects, which is exactly how a whole connector shipped broken.
"""
import json
import threading
import xmlrpc.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from taktline_connect import oauth, qbo, shipstation as ss_mod, xero as xero_mod  # noqa: E402
from taktline_connect.config import Config  # noqa: E402
from taktline_connect.core import Connector, Mapping  # noqa: E402
from taktline_connect.generic import GenericRestClient  # noqa: E402
from taktline_connect.netsuite import NetSuiteClient  # noqa: E402
from taktline_connect.odoo import OdooClient  # noqa: E402
from taktline_connect.qbo import QboClient  # noqa: E402
from taktline_connect.shipstation import ShipStationClient  # noqa: E402
from taktline_connect.shopify import ShopifyClient  # noqa: E402
from taktline_connect.taktline import TaktlineClient  # noqa: E402
from taktline_connect.woocommerce import WooClient  # noqa: E402
from taktline_connect.xero import XeroClient  # noqa: E402


class State:
    def __init__(self):
        # --- the Taktline side ---
        self.orders = {}          # (source, ref) -> order dict
        self.outbox = []          # completion events
        self.outbox_queries = []  # (status, source) seen by the server
        self.failed = []          # event ids reported as failed
        # --- the ERP side ---
        self.shopify = {"open_paid": [], "cancelled": [], "refunded": []}
        self.shopify_page_size = None    # set to force cursor pagination
        self.shopify_queries = []
        self.fulfilled = []
        self.woo = {}                    # status -> [orders]
        self.woo_page_size = 100
        self.woo_queries = []
        self.shipstation = []
        self.ss_page_size = 500
        self.ss_shipped = []
        self.xero_quotes = []
        self.xero_page_size = 100
        self.xero_queries = []
        self.ns_rows = []
        self.ns_builds = []              # existing assemblyBuilds, by work-order id
        self.ns_created = []
        self.ns_queries = []
        self.ns_page = 1000
        self.generic_rows = []
        self.generic_auth = None
        self.odoo_mos = []
        self.odoo_products = {}
        self.odoo_done = []
        self.odoo_cancelled = []
        self.qbo_token_calls = 0
        self.qbo_query_calls = 0
        self.qbo_docs = []
        self.xero_token_calls = 0
        self.token_401_once = False


def _page(rows, page, size):
    start = (page - 1) * size
    return rows[start:start + size]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence
        pass

    @property
    def st(self) -> State:
        return self.server.state       # type: ignore[attr-defined]

    def _send(self, code, obj=None, headers=None):
        body = b"" if obj is None else json.dumps(obj).encode()
        self.send_response(code)
        if obj is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _raw(self):   # always drain the body so keep-alive connections stay clean
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # --- reads ----------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path, st = u.path, self.st

        if path.endswith("/orders.json"):                       # Shopify list
            st.shopify_queries.append(q)
            status, fin = q.get("status", ""), q.get("financial_status", "")
            key = ("cancelled" if status == "cancelled"
                   else "refunded" if fin == "refunded" else "open_paid")
            rows = st.shopify[key]
            if st.shopify_page_size:                            # cursor pagination
                page = int(q.get("page_info", 1))
                out = _page(rows, page, st.shopify_page_size)
                hdrs = {}
                if page * st.shopify_page_size < len(rows):
                    nxt = f"http://{self.headers['Host']}{path}?page_info={page + 1}"
                    hdrs["Link"] = f'<{nxt}>; rel="next"'
                return self._send(200, {"orders": out}, hdrs)
            return self._send(200, {"orders": rows})

        if path.endswith("fulfillment_orders.json"):            # Shopify fulfil lookup
            return self._send(200, {"fulfillment_orders": [{"id": 555, "status": "open"}]})

        if path == "/wp-json/wc/v3/orders":                     # WooCommerce
            st.woo_queries.append(q)
            rows = st.woo.get(q.get("status"), [])
            page = int(q.get("page", 1))
            total = max(1, -(-len(rows) // st.woo_page_size))
            return self._send(200, _page(rows, page, st.woo_page_size),
                              {"X-WP-TotalPages": str(total)})

        if path == "/ss/orders":                                # ShipStation
            page = int(q.get("page", 1))
            rows = [o for o in st.shipstation if o.get("orderStatus") == q.get("orderStatus")]
            total = max(1, -(-len(rows) // st.ss_page_size))
            return self._send(200, {"orders": _page(rows, page, st.ss_page_size),
                                    "page": page, "pages": total})

        if path == "/api.xro/2.0/Quotes":                       # Xero
            st.xero_queries.append(q)
            page = int(q.get("page", 1))
            rows = [x for x in st.xero_quotes if x.get("Status") == q.get("Status")]
            return self._send(200, {"Quotes": _page(rows, page, st.xero_page_size)})

        if path.endswith("/query"):                             # QBO
            st.qbo_query_calls += 1
            if st.qbo_query_calls == 1:
                return self._send(401, {"fault": "token expired"})   # force refresh+retry
            sql = q.get("query", "")
            start = int(sql.split("STARTPOSITION")[1].split()[0]) if "STARTPOSITION" in sql else 1
            size = int(sql.split("MAXRESULTS")[1].split()[0]) if "MAXRESULTS" in sql else 1000
            return self._send(200, {"QueryResponse": {"Estimate": st.qbo_docs[start - 1:start - 1 + size]}})

        if path == "/generic/orders":                           # Generic REST
            st.generic_auth = self.headers.get("Authorization")
            return self._send(200, {"orders": st.generic_rows})

        if "/orders/outbox" in path:                            # Taktline outbox
            st.outbox_queries.append((q.get("status"), q.get("source")))
            src = q.get("source")
            return self._send(200, [e for e in st.outbox
                                    if e["status"] == (q.get("status") or "pending")
                                    and (src is None or (e["payload"] or {}).get("source") == src)])

        return self._send(404, {"detail": "no route"})

    # --- writes ---------------------------------------------------------
    def do_POST(self):
        u = urlparse(self.path)
        path, st = u.path, self.st
        raw = self._raw()                                       # drain regardless of content-type

        if path.startswith("/xmlrpc/2/"):                       # Odoo
            return self._xmlrpc(raw)

        if path.endswith("/tokens/bearer"):                     # QBO OAuth refresh
            st.qbo_token_calls += 1
            return self._send(200, {"access_token": f"tok-{st.qbo_token_calls}",
                                    "refresh_token": "rt-next"})
        if path == "/connect/token":                            # Xero OAuth refresh
            st.xero_token_calls += 1
            return self._send(200, {"access_token": f"xtok-{st.xero_token_calls}",
                                    "refresh_token": f"xrt-{st.xero_token_calls}"})

        if path == "/services/rest/query/v1/suiteql":           # NetSuite
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            sql = (json.loads(raw) or {}).get("q", "")
            st.ns_queries.append(sql)
            if "type = 'Build'" in sql:                          # the idempotency probe
                wo = sql.split("createdfrom =")[1].strip()
                return self._send(200, {"items": [{"id": "b1"}] if wo in st.ns_builds else [],
                                        "hasMore": False})
            offset, limit = int(q.get("offset", 0)), int(q.get("limit", st.ns_page))
            return self._send(200, {"items": st.ns_rows[offset:offset + limit],
                                    "hasMore": offset + limit < len(st.ns_rows)})

        if path == "/services/rest/record/v1/assemblyBuild":
            st.ns_created.append(str((json.loads(raw) or {}).get("workOrder", {}).get("id")))
            return self._send(204)

        if path == "/ss/orders/markasshipped":
            st.ss_shipped.append(str((json.loads(raw) or {}).get("orderId")))
            return self._send(200, {"orderId": (json.loads(raw) or {}).get("orderId")})

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

        if "/outbox/" in path and path.endswith("/fail"):       # Taktline fail
            eid = path.split("/outbox/")[1].split("/fail")[0]
            st.failed.append(eid)
            for e in st.outbox:
                if e["id"] == eid:
                    e["attempts"] = e.get("attempts", 0) + 1
                    return self._send(200, e)
            return self._send(404, {"detail": "Event not found"})

        if path.rstrip("/").endswith("/orders"):                # Taktline create
            key = (body["source"], body.get("externalRef"))
            if key in st.orders:
                return self._send(200, st.orders[key])          # already released
            st.orders[key] = {"id": f"ord-{len(st.orders)}", "status": "released",
                              "externalRef": body.get("externalRef"),
                              "quantity": body["quantity"], "lotCode": body.get("lotCode")}
            return self._send(201, st.orders[key])

        return self._send(404, {"detail": "no route"})

    def do_PUT(self):
        u = urlparse(self.path)
        body = json.loads(self._raw() or b"{}")
        if u.path.startswith("/wp-json/wc/v3/orders/"):
            oid = u.path.rsplit("/", 1)[-1]
            self.st.woo.setdefault("_completed", []).append(oid) if body.get("status") == "completed" else None
            return self._send(200, {"id": oid, "status": body.get("status")})
        return self._send(404, {"detail": "no route"})

    # --- Odoo XML-RPC, with Odoo's real calling convention enforced -------
    def _xmlrpc(self, raw):
        params, method = xmlrpc.client.loads(raw)
        try:
            result = (self._odoo(method, params),)
        except xmlrpc.client.Fault as f:
            result = f
        out = xmlrpc.client.dumps(result, methodresponse=True, allow_none=True).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    @staticmethod
    def _ids(args, call):
        """``args[0]`` must be a flat list of ids. Odoo browses it directly, so a
        doubly-nested list yields ``id IN (ARRAY[..])`` and a SQL type error."""
        if not args or not isinstance(args[0], list):
            raise xmlrpc.client.Fault(1, f"{call}: expected args[0] to be a list of ids")
        for i in args[0]:
            if not isinstance(i, int):
                raise xmlrpc.client.Fault(
                    1, f"{call}: expected a list of ids, got a nested "
                       f"{type(i).__name__} ({i!r}) — args[0] is doubly nested")
        return args[0]

    @staticmethod
    def _fields(args, kwargs, pos, call):
        """``fields`` is a keyword argument. Smuggling the options dict in
        positionally makes Odoo read it *as* the field list → "Invalid field"."""
        f = kwargs.get("fields", args[pos] if len(args) > pos else None)
        if f is not None and (not isinstance(f, list) or any(not isinstance(x, str) for x in f)):
            raise xmlrpc.client.Fault(
                1, f"{call}: Invalid field {list(f)[0]!r} — `fields` must be a list of "
                   f"names passed as a keyword argument")
        return f

    def _odoo(self, method, params):
        st = self.st
        if method == "authenticate":
            return 7                                     # uid
        if method != "execute_kw":
            raise xmlrpc.client.Fault(1, f"unknown method {method}")
        _db, _uid, _pw, model, call, args = params[:6]
        kwargs = params[6] if len(params) > 6 else {}

        if model == "mrp.production" and call == "search_read":
            domain = args[0] if args else []
            if not all(isinstance(c, (list, tuple)) and len(c) == 3 for c in domain):
                raise xmlrpc.client.Fault(1, "search_read: malformed domain")
            self._fields(args, kwargs, 1, "search_read")
            states = domain[0][2] if domain else []
            return [m for m in st.odoo_mos if m["state"] in states]
        if model == "mrp.production" and call == "read":
            ids = self._ids(args, "read")
            self._fields(args, kwargs, 1, "read")
            return [{"id": m["id"], "product_qty": m["product_qty"]}
                    for m in st.odoo_mos if m["id"] in ids]
        if model == "product.product" and call == "read":
            ids = self._ids(args, "read")
            self._fields(args, kwargs, 1, "read")
            return [{"id": i, **st.odoo_products.get(i, {})} for i in ids]
        if model == "mrp.production" and call == "write":
            ids = self._ids(args, "write")
            if len(args) < 2 or not isinstance(args[1], dict):
                raise xmlrpc.client.Fault(1, "write: expected args[1] to be the values dict")
            for m in st.odoo_mos:
                if m["id"] in ids:
                    m.update(args[1])
            return True
        if model == "mrp.production" and call in ("button_mark_done", "action_cancel"):
            sink = st.odoo_done if call == "button_mark_done" else st.odoo_cancelled
            sink.extend(self._ids(args, call))
            return True
        raise xmlrpc.client.Fault(1, f"unimplemented: {model}.{call}")


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.state = State()                                          # type: ignore[attr-defined]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        yield base, srv.state
    finally:
        srv.shutdown()


def _cfg(base, **kw):
    return Config(taktline_url=base, taktline_api_key="k",
                  product_mapping={"BIKE": "tmpl-1"}, **kw)


def _conn(base, erp, source):
    return Connector(erp, TaktlineClient(base, "k"), Mapping({"BIKE": "tmpl-1"}), source=source)


def _shopify_order(oid, line_id, sku, qty, financial="paid"):
    return {"id": oid, "financial_status": financial,
            "line_items": [{"id": line_id, "sku": sku, "title": sku, "quantity": qty}]}


# ── Shopify ─────────────────────────────────────────────────────────────

def test_shopify_full_loop(server):
    base, st = server
    st.shopify["open_paid"] = [_shopify_order(1001, 11, "BIKE", 2),
                               _shopify_order(2002, 22, "BIKE", 1)]

    cfg = _cfg(base, shopify_shop="x", shopify_fulfill=True)
    erp = ShopifyClient(cfg)
    erp.base = f"{base}/admin/api/2024-01"                       # point at the mock
    conn = _conn(base, erp, "shopify")

    # phase 1 — both paid orders release (one Taktline order per line item)
    released, cancelled, delivered = conn.run_once()
    assert released == 2 and cancelled == 0 and delivered == 0
    assert set(st.orders) == {("shopify", "1001:11"), ("shopify", "2002:22")}

    # phase 2 — shopper cancels 2002 and we finish 1001
    st.shopify["open_paid"] = [_shopify_order(1001, 11, "BIKE", 2)]
    st.shopify["cancelled"] = [_shopify_order(2002, 22, "BIKE", 1)]
    st.outbox = [{"id": "e1", "eventType": "order.completed", "status": "pending",
                  "payload": {"source": "shopify", "externalRef": "1001:11"}}]

    released, cancelled, delivered = conn.run_once()
    assert released == 0                                         # re-pushed, nothing new
    assert len(st.orders) == 2
    assert cancelled == 1 and st.orders[("shopify", "2002:22")]["status"] == "cancelled"
    assert delivered == 1 and st.outbox[0]["status"] == "delivered"
    assert len(st.fulfilled) == 1                               # completion fulfilled the order


def test_shopify_cancel_of_unreleased_is_benign(server):
    base, st = server
    st.shopify["cancelled"] = [_shopify_order(9, 9, "BIKE", 1)]   # never released in Taktline
    erp = ShopifyClient(_cfg(base, shopify_shop="x"))
    erp.base = f"{base}/admin/api/2024-01"
    conn = _conn(base, erp, "shopify")
    # cancel_by_ref returns False on 404 → counted as 0, no error
    assert conn.sync_cancellations() == 0


def test_shopify_follows_the_cursor_to_every_page(server):
    """One page is 250 orders. A shop past that never sees its newest work,
    because with fulfilment off nothing ever leaves the open+paid set."""
    base, st = server
    st.shopify["open_paid"] = [_shopify_order(i, i, "BIKE", 1) for i in range(1, 8)]
    st.shopify_page_size = 3                                     # → 3 pages
    erp = ShopifyClient(_cfg(base, shopify_shop="x"))
    erp.base = f"{base}/admin/api/2024-01"
    assert len(erp.list_orders(())) == 7
    assert len(st.shopify_queries) == 3


def test_shopify_bounds_the_cancellation_scan(server):
    # The cancelled/refunded sets only grow; rescanning all of history every poll
    # would spend the entire API budget re-cancelling settled orders.
    base, st = server
    erp = ShopifyClient(_cfg(base, shopify_shop="x", cancel_lookback_days=3))
    erp.base = f"{base}/admin/api/2024-01"
    erp.list_cancellations(())
    assert all("updated_at_min" in q for q in st.shopify_queries)


# ── WooCommerce ─────────────────────────────────────────────────────────

def _woo_order(oid, line_id, sku, qty, status="processing"):
    return {"id": oid, "number": str(oid), "status": status,
            "line_items": [{"id": line_id, "sku": sku, "quantity": qty}]}


def test_woo_full_loop(server):
    base, st = server
    st.woo = {"processing": [_woo_order(7001, 71, "BIKE", 2)], "cancelled": [], "refunded": []}
    erp = WooClient(_cfg(base, woo_url=base, woo_consumer_key="ck", woo_consumer_secret="cs"))
    conn = _conn(base, erp, "woocommerce")

    released, cancelled, delivered = conn.run_once()
    assert released == 1 and st.orders[("woocommerce", "7001:71")]["quantity"] == 2
    assert st.orders[("woocommerce", "7001:71")]["lotCode"] == "#7001"

    st.outbox = [{"id": "e1", "eventType": "order.completed", "status": "pending",
                  "payload": {"source": "woocommerce", "externalRef": "7001:71"}}]
    conn.run_once()
    assert st.woo["_completed"] == ["7001"]                      # PUT status=completed


def test_woo_reads_every_page_oldest_first(server):
    """Woo returns newest-first by default, and an order only leaves `processing`
    when Taktline completes it — so a single page of a >100 backlog would starve
    the oldest work forever."""
    base, st = server
    st.woo = {"processing": [_woo_order(i, i, "BIKE", 1) for i in range(1, 8)]}
    st.woo_page_size = 2                                         # → 4 pages
    erp = WooClient(_cfg(base, woo_url=base, woo_consumer_key="ck", woo_consumer_secret="cs"))
    assert len(erp.list_orders(())) == 7
    assert [q["page"] for q in st.woo_queries] == ["1", "2", "3", "4"]
    assert {q["order"] for q in st.woo_queries} == {"asc"}


# ── ShipStation ─────────────────────────────────────────────────────────

def test_shipstation_pages_and_ships(server, monkeypatch):
    base, st = server
    monkeypatch.setattr(ss_mod, "BASE", f"{base}/ss")
    st.shipstation = [{"orderId": 900 + i, "orderNumber": f"SS-{i}",
                       "orderStatus": "awaiting_shipment",
                       "items": [{"orderItemId": i, "sku": "BIKE", "quantity": 1}]}
                      for i in range(1, 6)]
    st.ss_page_size = 2                                          # → 3 pages
    erp = ShipStationClient(_cfg(base, shipstation_api_key="k", shipstation_api_secret="s"))
    assert len(erp.list_orders(())) == 5
    erp.mark_done("901:1")
    assert st.ss_shipped == ["901"]


# ── Xero ────────────────────────────────────────────────────────────────

def test_xero_pages_and_refreshes(server, monkeypatch):
    base, st = server
    monkeypatch.setattr(xero_mod, "TOKEN_URL", f"{base}/connect/token")
    monkeypatch.setattr(xero_mod, "API_BASE", f"{base}/api.xro/2.0")
    monkeypatch.setattr(xero_mod, "PAGE_SIZE", 2)
    st.xero_page_size = 2
    st.xero_quotes = [{"QuoteID": f"q{i}", "QuoteNumber": f"QU-{i}", "Status": "ACCEPTED",
                       "LineItems": [{"LineItemID": f"li{i}", "Item": {"Code": "BIKE"},
                                      "Quantity": 1}]}
                      for i in range(1, 6)]
    erp = XeroClient(_cfg(base, xero_client_id="c", xero_client_secret="s",
                          xero_refresh_token="rt0", xero_tenant_id="t"))
    rows = erp.list_orders(())
    assert len(rows) == 5                                        # 3 pages of 2
    assert rows[0]["id"] == "Quote:q1:li1" and rows[0]["lot_code"] == "QU-1"
    assert st.xero_token_calls == 1


# ── NetSuite ────────────────────────────────────────────────────────────

def _ns_client(base, st):
    erp = NetSuiteClient(_cfg(base, ns_account="acct", ns_consumer_key="ck",
                              ns_consumer_secret="cs", ns_token_id="ti", ns_token_secret="ts"))
    erp.base = f"{base}/services/rest"
    erp.auth = None                                              # skip OAuth1 signing
    return erp


def test_netsuite_pages_suiteql(server):
    base, st = server
    st.ns_rows = [{"id": str(i), "tranid": f"WO{i}", "status": "Work Order:Pending Build",
                   "product_ref": "BIKE", "qty": "1"} for i in range(1, 6)]
    st.ns_page = 1000
    erp = _ns_client(base, st)
    erp._suiteql = lambda q: (st.ns_queries.append(q) or st.ns_rows)   # noqa: SLF001
    rows = erp.list_orders(())
    assert len(rows) == 5 and rows[0]["lot_code"] == "WO1"
    # the assembly comes off the work order's mainline, never from `entity`
    assert "transactionLine" in st.ns_queries[0] and "t.entity" not in st.ns_queries[0]
    assert "ORDER BY" in st.ns_queries[0]                        # stable offset paging


def test_netsuite_mark_done_is_idempotent(server):
    """Delivery is at-least-once: a lost ack re-sends the completion. A second
    assemblyBuild would post the finished goods into inventory twice."""
    base, st = server
    erp = _ns_client(base, st)
    erp.mark_done("42")
    assert st.ns_created == ["42"]
    st.ns_builds.append("42")                                    # the build now exists
    erp.mark_done("42")                                          # redelivery
    assert st.ns_created == ["42"]                               # …no second build


# ── Odoo ────────────────────────────────────────────────────────────────

def test_odoo_full_loop_over_xmlrpc(server):
    """Regression for the argument packing: Odoo reads args[0] as the ids/domain
    and takes `fields`/`context` as keyword arguments. The mock enforces both, so
    the old packing (options dict passed positionally, ids doubly nested) faults."""
    base, st = server
    st.odoo_products = {31: {"default_code": "BIKE", "name": "Bike"}}
    st.odoo_mos = [{"id": 8801, "name": "MO/00042", "product_id": [31, "Bike"],
                    "product_qty": 4, "state": "confirmed"}]
    erp = OdooClient(_cfg(base, odoo_url=base, odoo_db="db", odoo_username="u", odoo_password="p"))
    conn = _conn(base, erp, "odoo")

    assert conn.sync_orders() == 1
    o = st.orders[("odoo", "8801")]
    assert o["quantity"] == 4 and o["lotCode"] == "MO/00042"

    st.outbox = [{"id": "e1", "eventType": "order.completed", "status": "pending",
                  "payload": {"source": "odoo", "externalRef": "8801"}}]
    assert conn.sync_completions() == 1
    assert st.odoo_done == [8801]

    erp.cancel("8801")
    assert st.odoo_cancelled == [8801]


# ── Generic REST ────────────────────────────────────────────────────────

def test_generic_maps_fields_and_sends_auth(server):
    base, st = server
    st.generic_rows = [{"orderNo": "G-1", "sku": "BIKE", "quantity": "2.000",
                        "state": "open", "orderName": "JOB-1"}]
    erp = GenericRestClient(_cfg(
        base, generic_orders_url=f"{base}/generic/orders",
        generic_auth_header="Bearer xyz",
        generic_fields=json.dumps({"id": "orderNo", "product_ref": "sku",
                                   "qty": "quantity", "lot_code": "orderName"})))
    conn = _conn(base, erp, "generic")
    assert conn.sync_orders() == 1
    assert st.generic_auth == "Bearer xyz"
    assert st.orders[("generic", "G-1")]["quantity"] == 2        # "2.000" → 2
    assert st.orders[("generic", "G-1")]["lotCode"] == "JOB-1"


# ── QBO ─────────────────────────────────────────────────────────────────

def test_qbo_oauth_refresh_and_401_retry(server, monkeypatch, tmp_path):
    base, st = server
    st.qbo_docs = [{"Id": "148", "TxnStatus": "Accepted", "Line": [
        {"Id": "1", "SalesItemLineDetail": {"ItemRef": {"name": "BIKE"}, "Qty": 3}},
    ]}]
    monkeypatch.setattr(qbo, "TOKEN_URL", f"{base}/oauth2/v1/tokens/bearer")
    monkeypatch.setenv("TOKEN_STORE", str(tmp_path / "tokens.json"))

    client = QboClient(_cfg(base, qbo_client_id="c", qbo_client_secret="s",
                            qbo_refresh_token="rt0", qbo_realm_id="123"))
    client.base = f"{base}/v3/company/123"                       # point at the mock

    rows = client.list_orders(())
    assert rows == [{"id": "Estimate:148:1", "product_ref": "BIKE", "qty": 3, "state": "Accepted"}]
    # initial auth + one refresh after the forced 401; query hit twice (401 then 200)
    assert st.qbo_token_calls == 2 and st.qbo_query_calls == 2
    assert client.refresh_token == "rt-next"                     # rotated token captured


def test_qbo_pages_through_estimates(server, monkeypatch):
    base, st = server
    monkeypatch.setattr(qbo, "TOKEN_URL", f"{base}/oauth2/v1/tokens/bearer")
    monkeypatch.setattr(qbo, "PAGE_SIZE", 2)
    st.qbo_docs = [{"Id": str(i), "TxnStatus": "Accepted", "Line": [
        {"Id": "1", "SalesItemLineDetail": {"ItemRef": {"name": "BIKE"}, "Qty": 1}}]}
        for i in range(1, 6)]
    client = QboClient(_cfg(base, qbo_client_id="c", qbo_client_secret="s",
                            qbo_refresh_token="rt0", qbo_realm_id="123"))
    client.base = f"{base}/v3/company/123"
    assert len(client.list_orders(())) == 5                      # 3 pages (the 401 costs one call)


# ── the Taktline contract itself ────────────────────────────────────────

def test_outbox_poll_is_scoped_to_this_connector(server):
    base, st = server
    st.odoo_mos = [{"id": 1, "name": "MO/1", "product_id": [31, "Bike"],
                    "product_qty": 1, "state": "confirmed"}]
    st.outbox = [
        {"id": "mine", "eventType": "order.completed", "status": "pending",
         "payload": {"source": "odoo", "externalRef": "1"}},
        {"id": "manual", "eventType": "order.completed", "status": "pending",
         "payload": {"source": "manual", "externalRef": "2"}},
    ]
    erp = OdooClient(_cfg(base, odoo_url=base, odoo_db="db", odoo_username="u", odoo_password="p"))
    conn = _conn(base, erp, "odoo")
    assert conn.sync_completions() == 1
    assert st.outbox_queries == [("pending", "odoo")]
    assert st.outbox[1]["status"] == "pending"                   # manual event untouched


def test_failed_delivery_is_reported_but_not_acked(server):
    base, st = server
    st.outbox = [{"id": "e1", "eventType": "order.completed", "status": "pending",
                  "payload": {"source": "odoo", "externalRef": "does-not-exist"}}]
    erp = OdooClient(_cfg(base, odoo_url=base, odoo_db="db", odoo_username="u", odoo_password="p"))
    erp.mark_done = lambda ref: (_ for _ in ()).throw(RuntimeError("ERP down"))
    conn = _conn(base, erp, "odoo")
    assert conn.sync_completions() == 0
    assert st.outbox[0]["status"] == "pending"                   # retried next cycle
    assert st.failed == ["e1"]                                   # attempt counted


# ── OAuth token persistence ─────────────────────────────────────────────

def test_rotated_refresh_token_survives_a_restart(server, monkeypatch, tmp_path):
    """Xero rotates the refresh token on every refresh and kills the old one, so
    a connector that only keeps it in memory can never restart."""
    base, st = server
    store = tmp_path / "tokens.json"
    monkeypatch.setenv("TOKEN_STORE", str(store))
    monkeypatch.setattr(xero_mod, "TOKEN_URL", f"{base}/connect/token")
    monkeypatch.setattr(xero_mod, "API_BASE", f"{base}/api.xro/2.0")

    cfg = _cfg(base, xero_client_id="c", xero_client_secret="s",
               xero_refresh_token="rt-from-env", xero_tenant_id="t")
    first = XeroClient(cfg)
    first.list_orders(())
    assert first.refresh_token == "xrt-1"
    assert json.loads(store.read_text())["xero"] == "xrt-1"

    restarted = XeroClient(cfg)                                  # same stale env value
    assert restarted.refresh_token == "xrt-1"                    # …picks up the rotated one
    assert oauth.load_refresh_token("nobody", "fallback") == "fallback"


def test_completion_for_a_deleted_erp_order_drains(server):
    """The MO was deleted in Odoo. There is nothing to close, so the event must
    drain — raising would re-deliver it on every poll for the life of the
    connector, and it would sit in the outbox window forever."""
    base, st = server
    st.odoo_mos = []
    st.outbox = [{"id": "e1", "eventType": "order.completed", "status": "pending",
                  "payload": {"source": "odoo", "externalRef": "999"}}]
    erp = OdooClient(_cfg(base, odoo_url=base, odoo_db="db", odoo_username="u", odoo_password="p"))
    conn = _conn(base, erp, "odoo")
    assert conn.sync_completions() == 1
    assert st.outbox[0]["status"] == "delivered" and st.failed == []
