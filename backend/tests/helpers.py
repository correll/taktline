"""Shared test helpers: an isolated API client (Actor) + setup shortcuts."""

import uuid

from fastapi.testclient import TestClient

SESSION_COOKIE = "taktline_session"
CSRF_COOKIE = "taktline_csrf"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


class Actor:
    """An independent API client with its own cookie jar; auto-attaches the CSRF
    header (from the readable cookie) and the active-company header."""

    def __init__(self):
        from app.main import app  # deferred so env is set before app import
        self.tc = TestClient(app)
        self.company = None

    def req(self, method, path, json=None, files=None, headers=None):
        h = dict(headers or {})
        csrf = self.tc.cookies.get(CSRF_COOKIE)
        if csrf and method.upper() in UNSAFE:
            h["X-CSRF-Token"] = csrf
        if self.company and "X-Company-Id" not in h:
            h["X-Company-Id"] = self.company
        return self.tc.request(method, path, json=json, files=files, headers=h)


def bootstrap_admin(a: Actor, company: str = "Acme") -> str:
    """Create a verified admin + company and log `a` in (dev-only fast path)."""
    email = f"admin-{uuid.uuid4().hex}@example.com"
    r = a.req("POST", "/auth/dev/bootstrap",
              {"email": email, "password": "password-abcdef", "companyName": company})
    assert r.status_code == 200, r.text
    a.company = r.json()["companyId"]
    return email


def add_member(admin: Actor, member: Actor, role: str = "user") -> str:
    """Invite a fresh user into admin's company and accept as `member`."""
    email = f"member-{uuid.uuid4().hex}@example.com"
    r = admin.req("POST", f"/companies/{admin.company}/invitations", {"email": email, "role": role})
    assert r.status_code == 201, r.text
    token = r.json()["devLink"].split("token=")[1]
    r = member.req("POST", f"/invitations/{token}/accept-signup", {"password": "password-abcdef"})
    assert r.status_code == 200, r.text
    member.company = admin.company
    return email


def png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
