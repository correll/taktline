"""Scoped API-key auth on the integration endpoints."""

from tests.helpers import bootstrap_admin


def _widget(a):
    s = a.req("POST", "/stations/", {"name": "WSrc"}).json()["_id"]
    w = a.req("POST", "/stations/", {"name": "WWh"}).json()["_id"]
    p = a.req("POST", "/processes/", {"name": "WP"}).json()["_id"]
    a.req("POST", "/routes/", {"processId": p, "load": s, "unload": w, "quantity": 1})
    return a.req("POST", "/lot-templates/", {"name": "Widget", "startStationId": s, "processId": p}).json()["_id"]


def _svc(actor, key):
    """A key-authenticated caller (no session cookie)."""
    s = actor()
    return lambda method, path, body=None: s.req(method, path, json=body,
                                                 headers={"Authorization": f"Bearer {key}"})


def test_api_key_create_and_use(actor):
    admin = actor(); bootstrap_admin(admin)
    tmpl = _widget(admin)
    created = admin.req("POST", "/api-keys/", {"name": "odoo", "scopes": ["orders"]}).json()
    assert created["key"].startswith("tk_") and created["prefix"].startswith("tk_")
    svc = _svc(actor, created["key"])
    assert svc("POST", "/orders/", {"productTemplateId": tmpl, "quantity": 1,
                                    "source": "odoo", "externalRef": "K1"}).status_code == 201
    assert svc("GET", "/orders/outbox").status_code == 200
    # listing keys never re-exposes the secret
    listed = admin.req("GET", "/api-keys/").json()
    assert listed[0]["prefix"].startswith("tk_") and "key" not in listed[0]


def test_revoked_key_is_rejected(actor):
    admin = actor(); bootstrap_admin(admin); tmpl = _widget(admin)
    created = admin.req("POST", "/api-keys/", {"name": "k"}).json()
    admin.req("DELETE", f"/api-keys/{created['id']}")
    svc = _svc(actor, created["key"])
    assert svc("POST", "/orders/", {"productTemplateId": tmpl, "quantity": 1}).status_code == 401


def test_key_without_orders_scope_forbidden(actor):
    admin = actor(); bootstrap_admin(admin); tmpl = _widget(admin)
    # a valid key that simply lacks the 'orders' scope
    created = admin.req("POST", "/api-keys/", {"name": "k", "scopes": ["reports"]}).json()
    svc = _svc(actor, created["key"])
    assert svc("POST", "/orders/", {"productTemplateId": tmpl, "quantity": 1}).status_code == 403


def test_key_cannot_manage_keys(actor):
    admin = actor(); bootstrap_admin(admin)
    created = admin.req("POST", "/api-keys/", {"name": "k"}).json()
    svc = _svc(actor, created["key"])
    assert svc("POST", "/api-keys/", {"name": "evil"}).status_code == 401   # needs an admin session


def test_key_is_company_scoped(actor):
    a = actor(); bootstrap_admin(a, "A"); tmpl = _widget(a)
    key = a.req("POST", "/api-keys/", {"name": "k"}).json()["key"]
    b = actor(); bootstrap_admin(b, "B")
    svc = _svc(actor, key)
    assert svc("POST", "/orders/", {"productTemplateId": tmpl, "quantity": 1, "externalRef": "S1"}).status_code == 201
    assert b.req("GET", "/orders/").json() == []            # B can't see A's order
    assert len(a.req("GET", "/orders/").json()) == 1
