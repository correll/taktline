import pytest
from starlette.websockets import WebSocketDisconnect

from tests.helpers import bootstrap_admin, png_bytes


def test_security_headers_present(actor):
    a = actor()
    h = a.req("GET", "/health").headers
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert "referrer-policy" in {k.lower() for k in h}


def test_csrf_required_on_unsafe(actor):
    a = actor(); bootstrap_admin(a)
    # authenticated POST with the session cookie but no X-CSRF-Token header → 403
    r = a.tc.request("POST", "/stations/", json={"name": "x"}, headers={"X-Company-Id": a.company})
    assert r.status_code == 403


def _upload(a, filename, content, ctype="image/png"):
    return a.req("POST", "/map-settings/upload-floor-plan",
                 files={"file": (filename, content, ctype)})


def test_upload_rejects_bad_extension_and_content(actor):
    a = actor(); bootstrap_admin(a)
    assert _upload(a, "evil.html", b"<script>alert(1)</script>").status_code == 400   # extension
    assert _upload(a, "evil.svg", b"<svg onload=alert(1)>").status_code == 400          # svg blocked
    assert _upload(a, "x.png", b"<html>not really a png</html>").status_code == 400     # magic bytes
    r = _upload(a, "floor.png", png_bytes())
    assert r.status_code == 200
    # the served file carries nosniff + attachment (can't render as active content)
    served = a.req("GET", r.json()["url"])
    assert served.headers.get("x-content-type-options") == "nosniff"
    assert "attachment" in (served.headers.get("content-disposition") or "")


def test_upload_size_limit(actor, monkeypatch):
    a = actor(); bootstrap_admin(a)
    from app.core.config import settings
    monkeypatch.setattr(settings, "max_upload_bytes", 16)
    assert _upload(a, "big.png", png_bytes() + b"\x00" * 200).status_code == 413


def test_sql_and_xss_payloads_are_stored_literally(actor):
    a = actor(); bootstrap_admin(a)
    payload = "'; DROP TABLE stations; -- <script>alert(1)</script>"
    r = a.req("POST", "/stations/", {"name": payload})
    assert r.status_code == 201
    assert r.json()["name"] == payload            # verbatim → parameterized, not executed/encoded
    assert a.req("GET", "/stations/").status_code == 200   # table intact


def test_ws_rejects_disallowed_origin(actor):
    a = actor(); bootstrap_admin(a)
    with pytest.raises(WebSocketDisconnect):
        with a.tc.websocket_connect(f"/ws/events?companyId={a.company}",
                                    headers={"origin": "https://evil.example.com"}) as ws:
            ws.receive_text()


def test_ws_accepts_allowed_origin(actor):
    a = actor(); bootstrap_admin(a)
    with a.tc.websocket_connect(f"/ws/events?companyId={a.company}",
                                headers={"origin": "http://localhost:3000"}) as ws:
        assert ws is not None   # handshake accepted


def test_login_rate_limited(actor):
    from app.core.ratelimit import limiter
    a = actor()
    limiter.enabled = True
    try:
        codes = [a.req("POST", "/auth/login",
                       {"email": "nobody@example.com", "password": "password-abcdef"}).status_code
                 for _ in range(12)]
    finally:
        limiter.enabled = False
    assert 429 in codes
