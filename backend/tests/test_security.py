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


def test_ws_accepts_same_origin_without_cors_config(actor):
    """Single-service hosting: the page that opened the socket is served by this
    very service, so the handshake is same-site by definition and must be
    accepted without the operator restating their own URL in CORS_ORIGINS.
    Getting this wrong costs every live board, with an amber light as the only
    clue."""
    a = actor(); bootstrap_admin(a)
    with a.tc.websocket_connect(f"/ws/events?companyId={a.company}",
                                headers={"origin": "https://taktline.onrender.com",
                                         "host": "taktline.onrender.com"}) as ws:
        assert ws is not None


def test_ws_still_rejects_a_foreign_origin_on_the_same_host(actor):
    """The same-origin allowance must compare against OUR host, not merely
    accept any Origin that happens to arrive with a Host header."""
    a = actor(); bootstrap_admin(a)
    with pytest.raises(WebSocketDisconnect):
        with a.tc.websocket_connect(f"/ws/events?companyId={a.company}",
                                    headers={"origin": "https://evil.example.com",
                                             "host": "taktline.onrender.com"}) as ws:
            ws.receive_text()


# ─── Deployment: the connection string a host actually hands out ─────────────

def test_managed_postgres_urls_are_normalized_for_asyncpg():
    """Render wires `postgresql://…`, Neon appends `?sslmode=require&
    channel_binding=…`, older tooling says `postgres://`. All three reach
    asyncpg broken — the bare driver resolves to psycopg2 (not installed) and
    the libpq-only query params are forwarded into `asyncpg.connect()` as
    unexpected keywords. A correct, copy-pasted production URL would fail at
    boot, so they are normalized instead of hand-edited."""
    from app.db.connection import normalize_db_url

    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert normalize_db_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    # sslmode → ssl, same vocabulary, so the TLS posture is carried across
    assert normalize_db_url(
        "postgresql://u:p@h/db?sslmode=require&channel_binding=require"
    ) == "postgresql+asyncpg://u:p@h/db?ssl=require"
    assert normalize_db_url(
        "postgresql://u:p@h/db?sslmode=verify-full"
    ) == "postgresql+asyncpg://u:p@h/db?ssl=verify-full"
    # already-correct URLs are left alone
    for good in ("postgresql+asyncpg://localhost:5432/taktline",
                 "postgresql+asyncpg://u:p@h/db?ssl=require"):
        assert normalize_db_url(good) == good


def test_normalized_url_actually_builds_an_asyncpg_engine():
    """The proof that matters: the normalized URL must produce a working engine
    with connect args asyncpg accepts."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.db.connection import normalize_db_url

    engine = create_async_engine(normalize_db_url("postgresql://u:p@h/db?sslmode=require"))
    assert engine.dialect.driver == "asyncpg"
    _, connect_args = engine.dialect.create_connect_args(engine.url)
    assert "sslmode" not in connect_args and "channel_binding" not in connect_args
    assert connect_args["ssl"] == "require"
