"""Platform-staff (customer service) surface: role gating, impersonation
grants, destructive ops, and the audit trail."""

import uuid

import pytest

from app.core.config import settings
from tests.helpers import Actor, bootstrap_admin


@pytest.fixture
def owner():
    """An actor whose email is on the PLATFORM_OWNER_EMAILS allowlist."""
    a = Actor()
    email = bootstrap_admin(a, company="Owner HQ")
    old = settings.platform_owner_emails
    settings.platform_owner_emails = email
    yield a
    settings.platform_owner_emails = old


STATION_BODY = {
    "name": "S1", "description": "", "adapterType": None, "adapterConfig": {},
    "color": None, "icon": None,
    "position": {"x": 1, "y": 1, "width": 60, "height": 60},
}


def test_non_staff_gets_404_not_403():
    a = Actor()
    bootstrap_admin(a)
    for path in ("/platform/status", "/platform/users", "/platform/companies", "/platform/audit"):
        assert a.req("GET", path).status_code == 404


def test_owner_sees_status_and_users(owner):
    r = owner.req("GET", "/platform/status")
    assert r.status_code == 200
    body = r.json()
    assert body["usersTotal"] >= 1 and "requestsPerMinute" in body

    r = owner.req("GET", "/platform/users")
    assert r.status_code == 200
    me = [u for u in r.json() if u["platformRole"] == "owner"]
    assert me and me[0]["companies"][0]["role"] == "super_admin"

    r = owner.req("GET", "/platform/companies")
    assert r.status_code == 200
    mine = [c for c in r.json() if c["name"] == "Owner HQ"][0]
    # The owner just made requests, so they count as an active user; the usage
    # counters exist (they may still be zero until the first flush).
    assert mine["activeUsers"] >= 1 and mine["members"] == 1
    for field in ("stations", "cards", "devicesConnected", "apiRequestsMonth", "wsMessagesMonth"):
        assert field in mine


def test_owner_grants_support_and_support_can_enter(owner):
    support = Actor()
    bootstrap_admin(support, company="Support Home")
    support_id = [u for u in owner.req("GET", "/platform/users").json()
                  if u["companies"] and u["companies"][0]["companyName"] == "Support Home"][0]["id"]

    # Grant 'support' (owner-only).
    r = owner.req("PUT", f"/platform/users/{support_id}/platform-role", {"role": "support"})
    assert r.status_code == 204
    assert support.req("GET", "/platform/status").status_code == 200

    # But support cannot grant roles.
    r = support.req("PUT", f"/platform/users/{support_id}/platform-role", {"role": None})
    assert r.status_code == 404

    # Revoke → 404 again.
    assert owner.req("PUT", f"/platform/users/{support_id}/platform-role", {"role": None}).status_code == 204
    assert support.req("GET", "/platform/status").status_code == 404


def test_impersonation_grant_lifecycle(owner):
    tenant = Actor()
    bootstrap_admin(tenant, company="Tenant Co")
    company_id = tenant.company

    # Without a grant the owner is a stranger to the tenant (403).
    r = owner.req("GET", "/stations/", headers={"X-Company-Id": company_id})
    assert r.status_code == 403

    # Start impersonation → full super_admin inside the company.
    r = owner.req("POST", "/platform/impersonate", {"companyId": company_id, "minutes": 30})
    assert r.status_code == 201, r.text
    assert owner.req("GET", "/stations/", headers={"X-Company-Id": company_id}).status_code == 200
    assert owner.req("POST", "/stations/", STATION_BODY,
                     headers={"X-Company-Id": company_id}).status_code == 201

    # The grant shows up flagged in /auth/me for the banner + switcher.
    me = owner.req("GET", "/auth/me").json()
    flagged = [c for c in me["companies"] if c["id"] == company_id]
    assert flagged and flagged[0]["impersonated"] is True and flagged[0]["role"] == "super_admin"

    # End it → access revoked immediately.
    assert owner.req("DELETE", f"/platform/impersonate/{company_id}").status_code == 204
    assert owner.req("GET", "/stations/", headers={"X-Company-Id": company_id}).status_code == 403

    # Start/end are on the audit trail.
    actions = [a["action"] for a in owner.req("GET", "/platform/audit").json()]
    assert "impersonation_started" in actions and "impersonation_ended" in actions


def test_delete_company_requires_exact_name(owner):
    tenant = Actor()
    bootstrap_admin(tenant, company="Doomed Co")
    cid = tenant.company

    r = owner.req("DELETE", f"/platform/companies/{cid}", {"confirmName": "wrong"})
    assert r.status_code == 400
    r = owner.req("DELETE", f"/platform/companies/{cid}", {"confirmName": "Doomed Co"})
    assert r.status_code == 204
    assert all(c["id"] != cid for c in owner.req("GET", "/platform/companies").json())


def test_delete_super_admin_but_never_owner(owner):
    victim = Actor()
    victim_email = bootstrap_admin(victim, company="Victim Co")   # sole super_admin
    users = owner.req("GET", "/platform/users").json()
    victim_id = [u for u in users if u["email"] == victim_email][0]["id"]
    owner_id = [u for u in users if u["platformRole"] == "owner"][0]["id"]

    # The owner account is untouchable; so is deleting yourself.
    assert owner.req("DELETE", f"/platform/users/{owner_id}").status_code == 400

    # Deleting a company super_admin works (bypasses the tenant-side guard).
    assert owner.req("DELETE", f"/platform/users/{victim_id}").status_code == 204
    assert victim.req("GET", "/auth/me").status_code == 401   # sessions cascaded

    detail = [a for a in owner.req("GET", "/platform/audit").json()
              if a["action"] == "user_deleted" and a["targetId"] == victim_id]
    assert detail and detail[0]["detail"]["email"] == victim_email


def test_support_role_not_settable_by_tenant_admin():
    a = Actor()
    bootstrap_admin(a)
    fake_id = str(uuid.uuid4())
    assert a.req("PUT", f"/platform/users/{fake_id}/platform-role", {"role": "support"}).status_code == 404
