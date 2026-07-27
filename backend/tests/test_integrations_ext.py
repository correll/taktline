"""Tier-2 integration surface: scope catalog, CSV import, cancel-by-ref,
scan-to-advance (key-authed), ZPL labels, and BI report feeds."""

from tests.helpers import bootstrap_admin


def _line(a):
    """S (source/template origin) → W (finished-goods leaf). Two templates so CSV
    name-resolution has something to match."""
    s = a.req("POST", "/stations/", {"name": "Src"}).json()["_id"]
    w = a.req("POST", "/stations/", {"name": "WH"}).json()["_id"]
    p = a.req("POST", "/processes/", {"name": "P"}).json()["_id"]
    a.req("POST", "/routes/", {"processId": p, "load": s, "unload": w, "quantity": 1})
    frame = a.req("POST", "/lot-templates/", {"name": "Frame", "startStationId": s, "processId": p}).json()["_id"]
    wheel = a.req("POST", "/lot-templates/", {"name": "Wheel", "startStationId": s, "processId": p}).json()["_id"]
    return {"s": s, "w": w, "p": p, "frame": frame, "wheel": wheel}


def _key(admin, *scopes):
    return admin.req("POST", "/api-keys/", {"name": "k", "scopes": list(scopes)}).json()["key"]


def _svc(actor, key):
    s = actor()
    return lambda m, p, **kw: s.req(m, p, headers={"Authorization": f"Bearer {key}"}, **kw)


# ── scope catalog / validation ──────────────────────────────────────────

def test_scope_catalog_and_validation(actor):
    admin = actor(); bootstrap_admin(admin)
    cat = admin.req("GET", "/api-keys/scopes").json()
    names = {c["scope"] for c in cat}
    assert {"orders", "cards:advance", "reports"} <= names
    # unknown scope rejected
    assert admin.req("POST", "/api-keys/", {"name": "x", "scopes": ["bogus"]}).status_code == 422
    # multi-scope key ok
    assert admin.req("POST", "/api-keys/", {"name": "x", "scopes": ["orders", "reports"]}).status_code == 201


# ── CSV import ──────────────────────────────────────────────────────────

def test_csv_import_releases_reports_and_is_idempotent(actor):
    admin = actor(); bootstrap_admin(admin); L = _line(admin)
    csv = (
        "product,quantity,source,externalRef\n"
        "Frame,5,csv,CSV-1\n"
        "Wheel,3,csv,CSV-2\n"
        "Nonexistent,2,csv,CSV-3\n"     # unknown product → error
        "Frame,,csv,CSV-4\n"            # bad quantity → error
    )
    r = admin.req("POST", "/orders/import", files={"file": ("orders.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    summ = r.json()["summary"]
    assert summ == {"total": 4, "released": 2, "duplicate": 0, "errors": 2}
    assert admin.req("GET", "/orders/").json().__len__() == 2   # only valid rows landed

    # re-import → the two good rows are now duplicates (idempotent on source+ref)
    r2 = admin.req("POST", "/orders/import", files={"file": ("orders.csv", csv, "text/csv")})
    assert r2.json()["summary"]["duplicate"] == 2
    assert r2.json()["summary"]["released"] == 0


def test_csv_import_accepts_template_id_and_aliases(actor):
    admin = actor(); bootstrap_admin(admin); L = _line(admin)
    csv = f"sku,qty,ref\n{L['frame']},4,R1\n"     # id + header aliases
    r = admin.req("POST", "/orders/import", files={"file": ("o.csv", csv, "text/csv")})
    assert r.json()["summary"]["released"] == 1
    assert admin.req("GET", "/orders/").json()[0]["externalRef"] == "R1"


def test_csv_import_via_orders_key(actor):
    admin = actor(); bootstrap_admin(admin); _line(admin)
    key = _key(admin, "orders")
    svc = _svc(actor, key)
    csv = "product,quantity\nFrame,2\n"
    r = svc("POST", "/orders/import", files={"file": ("o.csv", csv, "text/csv")})
    assert r.status_code == 200 and r.json()["summary"]["released"] == 1


# ── cancel by ref (Shopify/Woo cancel & refund path) ────────────────────

def test_cancel_by_ref(actor):
    admin = actor(); bootstrap_admin(admin); L = _line(admin)
    key = _key(admin, "orders"); svc = _svc(actor, key)
    svc("POST", "/orders/", json={"productTemplateId": L["frame"], "quantity": 3,
                                  "source": "shopify", "externalRef": "#1001"})
    r = svc("POST", "/orders/cancel", json={"source": "shopify", "externalRef": "#1001"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # in-flight lot scrapped; a cancel event enqueued
    assert admin.req("GET", "/cards/").json() == []
    events = svc("GET", "/orders/outbox?status=pending").json()
    assert any(e["eventType"] == "order.cancelled" and e["payload"]["externalRef"] == "#1001" for e in events)
    # unknown ref → 404
    assert svc("POST", "/orders/cancel", json={"source": "shopify", "externalRef": "nope"}).status_code == 404


# ── scan-to-advance (key-authed) + labels ───────────────────────────────

def test_scan_to_advance_with_key(actor):
    admin = actor(); bootstrap_admin(admin); L = _line(admin)
    ordkey = _key(admin, "orders")
    scankey = _key(admin, "cards:advance")
    _svc(actor, ordkey)("POST", "/orders/", json={"productTemplateId": L["frame"], "quantity": 2,
                                                   "source": "odoo", "externalRef": "MO-1"})
    card = admin.req("GET", "/cards/").json()[0]["_id"]
    scan = _svc(actor, scankey)
    # advance via the scan key (no session)
    r = scan("POST", f"/cards/{card}/advance", json={"fromStationId": L["s"], "toStationId": L["w"], "quantity": 2})
    assert r.status_code == 200, r.text
    # an orders-only key may NOT advance
    assert _svc(actor, ordkey)("POST", f"/cards/{card}/advance",
                               json={"fromStationId": L["s"], "toStationId": L["w"], "quantity": 1}).status_code == 403
    # a cards:advance key may NOT release orders
    assert scan("POST", "/orders/", json={"productTemplateId": L["frame"], "quantity": 1}).status_code == 403


def test_zpl_label(actor):
    admin = actor(); bootstrap_admin(admin); L = _line(admin)
    _svc(actor, _key(admin, "orders"))("POST", "/orders/", json={
        "productTemplateId": L["frame"], "quantity": 2, "source": "odoo", "externalRef": "MO-2"})
    card = admin.req("GET", "/cards/").json()[0]["_id"]
    scan = _svc(actor, _key(admin, "cards:advance"))
    r = scan("GET", f"/cards/{card}/label")
    assert r.status_code == 200
    body = r.text
    assert body.startswith("^XA") and body.endswith("^XZ")
    assert card in body           # barcode encodes the card id → scan-to-advance
    assert "Frame" in body


# ── BI reports ──────────────────────────────────────────────────────────

def test_reports_feed_and_scope(actor):
    admin = actor(); bootstrap_admin(admin); L = _line(admin)
    _svc(actor, _key(admin, "orders"))("POST", "/orders/", json={
        "productTemplateId": L["frame"], "quantity": 6, "source": "odoo", "externalRef": "MO-9"})
    repkey = _key(admin, "reports"); rep = _svc(actor, repkey)
    feed = rep("GET", "/reports/orders")
    assert feed.status_code == 200
    row = feed.json()[0]
    assert row["product"] == "Frame" and row["source"] == "odoo" and row["quantity"] == 6
    # complete it, then throughput shows a day bucket
    card = admin.req("GET", "/cards/").json()[0]["_id"]
    admin.req("POST", f"/cards/{card}/move", json={"fromStationId": L["s"], "toStationId": L["w"], "quantity": 6})
    tp = rep("GET", "/reports/throughput").json()
    assert len(tp) == 1 and tp[0]["orders"] == 1 and tp[0]["units"] == 6
    # an orders-only key cannot read reports
    assert _svc(actor, _key(admin, "orders"))("GET", "/reports/orders").status_code == 403
