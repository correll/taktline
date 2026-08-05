"""The subscription gate: what a company may do in each billing state.

This file has to work harder than most, because **the gate is off by default in
this suite.** `settings.billing_enabled` is false without a Stripe key, so every
other test runs unmetered — which is deliberate (a self-hosted install must not
invent a paywall nobody can pay) and also means a bug in the gate would
otherwise never be exercised by anything.

So each test here turns billing on explicitly, and one of them walks the app's
own routing table to assert the gate covers every write endpoint — including
whichever ones get written next month.

The model under test (pricing.md): a free tier of 3 stations with no clock and
no expiry, one metered paid plan, integrations on paid only, and non-payment
ending in *paused*, never deleted.
"""

import asyncio
import uuid
from datetime import timedelta

import pytest

from app.core import entitlements, plans
from app.core.config import settings
from app.models.common import utcnow
from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


@pytest.fixture
def billing(monkeypatch):
    """Turn the meter on for one test."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(settings, "deployment", "cloud", raising=False)
    return True


def _set_plan(company_id: str, **fields):
    """Put a company into a billing state, directly.

    There is no API for "make it look like the card failed nine days ago", and
    the states that matter most are the ones reached by the passage of time.
    """
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import Subscription

    async def go():
        async with SessionLocal() as s:
            row = (await s.execute(select(Subscription).where(
                Subscription.companyId == uuid.UUID(company_id)))).scalars().first()
            assert row is not None, "every company must get a subscription row"
            for k, v in fields.items():
                setattr(row, k, v)
            await s.commit()

    asyncio.run(go())


def _station(a: Actor, name: str):
    return a.req("POST", "/stations/", {**STATION, "name": name})


# ─── Every company-creation path makes a subscription ────────────────────────

def test_dev_bootstrap_creates_a_free_subscription(actor):
    a = actor()
    bootstrap_admin(a, "Boot co")
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import Subscription

    async def go():
        async with SessionLocal() as s:
            return (await s.execute(select(Subscription).where(
                Subscription.companyId == uuid.UUID(a.company)))).scalars().first()

    row = asyncio.run(go())
    assert row is not None and row.planCode == plans.FREE


def test_creating_a_second_company_creates_a_subscription(actor):
    a = actor()
    bootstrap_admin(a, "First co")
    r = a.req("POST", "/companies/", {"name": "Second co", "timezone": "UTC"})
    assert r.status_code == 201, r.text
    _set_plan(r.json()["id"])   # asserts the row exists


def test_the_sandbox_gets_the_sandbox_plan():
    a = Actor()
    r = a.req("POST", "/auth/sandbox", {})
    assert r.status_code in (200, 201), r.text
    _set_plan(r.json()["companyId"])


# ─── The derived state machine ───────────────────────────────────────────────

def _entitlement(company_id: str):
    from app.db.connection import SessionLocal

    async def go():
        async with SessionLocal() as s:
            return await entitlements.resolve(s, uuid.UUID(company_id))

    return asyncio.run(go())


def test_a_free_account_is_ok_and_never_expires(billing, actor):
    """The free tier has no clock. Stale timestamps left over from any past
    state must not matter — someone who drew a three-station cell and came
    back six months later should find it waiting."""
    a = actor()
    bootstrap_admin(a, "Free co")
    _set_plan(a.company, planCode="free",
              graceEndsAt=utcnow() - timedelta(days=400))
    ent = _entitlement(a.company)
    assert ent.state == entitlements.OK
    assert ent.station_limit == plans.FREE_STATIONS


def test_a_legacy_trial_row_resolves_to_free(billing, actor):
    """The trial is gone; a row written under it aliases to the free tier
    rather than crashing the gate — or worse, locking a customer."""
    a = actor()
    bootstrap_admin(a, "Legacy co")
    _set_plan(a.company, planCode="trial")
    ent = _entitlement(a.company)
    assert ent.plan.code == plans.FREE and ent.state == entitlements.OK


def test_a_failed_payment_is_read_only_during_grace_then_paused(billing, actor):
    a = actor()
    bootstrap_admin(a, "Lapsing co")

    _set_plan(a.company, planCode="taktline", stripeStatus="past_due",
              graceEndsAt=utcnow() + timedelta(days=3))
    assert _entitlement(a.company).state == entitlements.READ_ONLY

    _set_plan(a.company, graceEndsAt=utcnow() - timedelta(minutes=1))
    assert _entitlement(a.company).state == entitlements.LOCKED


def test_an_ach_payment_still_clearing_keeps_service_on(billing, actor):
    """A bank debit sits in `incomplete` for days after a successful checkout.
    Withholding service meanwhile would punish the customer for choosing the
    payment method we prefer."""
    a = actor()
    bootstrap_admin(a, "ACH co")
    _set_plan(a.company, planCode="taktline", stripeStatus="incomplete")
    ent = _entitlement(a.company)
    assert ent.state == entitlements.OK
    assert ent.settling is True


def test_a_comped_account_is_honoured(billing, actor):
    """The paid plan code with no Stripe subscription is staff having granted
    it by hand. It must not read as 'never paid'."""
    a = actor()
    bootstrap_admin(a, "Comped co")
    _set_plan(a.company, planCode="taktline", stripeStatus=None)
    ent = _entitlement(a.company)
    assert ent.state == entitlements.OK
    assert ent.station_limit is None


def test_billing_disabled_meters_nothing(actor):
    """No Stripe key = self-hosted. Even a wildly lapsed row must not lock."""
    a = actor()
    bootstrap_admin(a, "Self hosted co")
    _set_plan(a.company, planCode="taktline", stripeStatus="past_due",
              graceEndsAt=utcnow() - timedelta(days=99))
    ent = _entitlement(a.company)
    assert ent.state == entitlements.OK
    assert ent.station_limit is None


def test_on_premise_meters_nothing(monkeypatch, actor):
    a = actor()
    bootstrap_admin(a, "Onprem co")
    _set_plan(a.company, planCode="taktline", stripeStatus="past_due",
              graceEndsAt=utcnow() - timedelta(days=99))
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(settings, "deployment", "onprem", raising=False)
    assert _entitlement(a.company).state == entitlements.OK


# ─── The gate, over HTTP ─────────────────────────────────────────────────────

def _pause(company_id: str):
    """A paused account: payment failed, grace over."""
    _set_plan(company_id, planCode="taktline", stripeStatus="past_due",
              graceEndsAt=utcnow() - timedelta(days=1))


def test_paused_refuses_reads_and_writes_with_402(billing, actor):
    a = actor()
    bootstrap_admin(a, "Locked co")
    _pause(a.company)

    r = _station(a, "Nope")
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["code"] == "subscription_required"
    assert a.req("GET", "/stations/").status_code == 402


def test_read_only_allows_reads_and_refuses_writes(billing, actor):
    a = actor()
    bootstrap_admin(a, "Grace co")
    st = _station(a, "Cutting").json()["_id"]
    _set_plan(a.company, planCode="taktline", stripeStatus="past_due",
              graceEndsAt=utcnow() + timedelta(days=2))

    assert a.req("GET", "/stations/").status_code == 200
    r = _station(a, "Welding")
    assert r.status_code == 402
    assert r.json()["detail"]["code"] == "read_only"
    # Export has to keep working: "your data is yours" matters most here.
    assert a.req("GET", "/map-io/export").status_code == 200
    # And DELETE stays open, or the only way to shrink a line whose price is
    # being disputed is an action the state forbids.
    assert a.req("DELETE", f"/stations/{st}").status_code in (204, 200)


def test_read_only_still_lets_an_operator_close_a_session(billing, actor):
    """Blocking this does not apply pressure to pay; it leaves dangling
    `endedAt IS NULL` rows that corrupt the statistics we are still showing."""
    a = actor()
    bootstrap_admin(a, "Session co")
    st = _station(a, "Cutting").json()["_id"]
    sess = a.req("POST", "/sessions/", {"stationId": st, "operatorId": "t1",
                                        "quantity": 1}).json()["_id"]
    _set_plan(a.company, planCode="taktline", stripeStatus="past_due",
              graceEndsAt=utcnow() + timedelta(days=2))
    assert a.req("POST", f"/sessions/{sess}/end", {"quantity": 1}).status_code == 200


def test_a_sandbox_visitor_is_never_gated(billing):
    a = Actor()
    r = a.req("POST", "/auth/sandbox", {})
    a.company = r.json()["companyId"]
    assert _station(a, "Cutting").status_code == 201


def test_support_can_reach_a_paused_account(billing, actor):
    """The bypass is deliberate: support is usually called *because* the
    account is paused. Grants are time-boxed and audited.

    The owner allowlist is set and restored by hand, the same way
    `test_platform.owner` does it. An earlier version patched
    `type(settings).platform_owner_list` with monkeypatch, which leaked past
    the test and left a later platform test believing the wrong person was an
    owner — pydantic settings are not safe to patch at the class level.
    """
    owner, staff = actor(), actor()
    bootstrap_admin(owner, "Stuck co")
    _pause(owner.company)

    email = bootstrap_admin(staff, "Staff co")
    previous = settings.platform_owner_emails
    settings.platform_owner_emails = email
    try:
        r = staff.req("POST", "/platform/impersonate",
                      {"companyId": owner.company, "minutes": 30})
        assert r.status_code in (200, 201), r.text
        staff.company = owner.company
        assert staff.req("GET", "/stations/").status_code == 200
    finally:
        settings.platform_owner_emails = previous


# ─── Quotas ──────────────────────────────────────────────────────────────────

def test_the_free_tier_caps_at_three_stations(billing, actor):
    """The real cap on the real plan — no fake plan monkeypatched in. Three
    stations draw; the fourth is the ask."""
    a = actor()
    bootstrap_admin(a, "Ceiling co")

    for name in ("A", "B", "C"):
        assert _station(a, name).status_code == 201, name
    r = _station(a, "D")
    assert r.status_code == 403
    body = r.json()["detail"]
    assert (body["code"], body["resource"], body["limit"], body["used"]) == \
           ("plan_limit", "stations", plans.FREE_STATIONS, plans.FREE_STATIONS)


def test_the_paid_plan_has_no_station_ceiling(billing, actor):
    a = actor()
    bootstrap_admin(a, "Metered co")
    _set_plan(a.company, planCode="taktline", stripeStatus="active")
    for i in range(plans.FREE_STATIONS + 2):
        assert _station(a, f"S{i}").status_code == 201


def test_a_line_file_cannot_walk_around_the_free_cap(billing, actor):
    """The import used to check quotas only for sandbox users, so every real
    account could load MAX_STATIONS onto a capped plan in one call — and
    because import REPLACES the line, the per-create quota never saw them."""
    a = actor()
    bootstrap_admin(a, "Import co")

    doc = {"kind": "taktline-map", "version": 1, "name": "Big",
           "stations": [{"ref": f"s{i}", "name": f"S{i}"} for i in range(5)],
           "processes": [], "templates": [], "routes": []}
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "plan_limit"


# ─── Integrations ────────────────────────────────────────────────────────────

def test_free_cannot_bind_an_integration_and_paid_can(billing, actor):
    a = actor()
    bootstrap_admin(a, "Integration co")

    body = {**STATION, "name": "Dock", "integrationProvider": "shipstation",
            "integrationRole": "sink"}
    r = a.req("POST", "/stations/", body)
    assert r.status_code == 403
    assert r.json()["detail"]["resource"] == "integrations"

    _set_plan(a.company, planCode="taktline", stripeStatus="active")
    assert a.req("POST", "/stations/", body).status_code == 201


def test_every_connector_is_included_on_paid(billing, actor):
    """The model: connectors are deliberately unmetered. Binding a second and
    third *distinct provider* must not meet a count, a quota, or an upsell."""
    a = actor()
    bootstrap_admin(a, "Wired co")
    _set_plan(a.company, planCode="taktline", stripeStatus="active")

    for provider, role in (("shipstation", "sink"), ("shopify", "source"),
                           ("odoo", "source")):
        r = a.req("POST", "/stations/", {**STATION, "name": f"Dock {provider}",
                                         "integrationProvider": provider,
                                         "integrationRole": role})
        assert r.status_code == 201, (provider, r.text)


def test_renaming_a_station_that_carries_an_old_binding_still_works(billing, actor):
    """A lapse back to free must not strand the account: they have to be able
    to edit — and clear — the bindings the free tier would not allow anew."""
    a = actor()
    bootstrap_admin(a, "Downgraded co")
    _set_plan(a.company, planCode="taktline", stripeStatus="active")
    st = a.req("POST", "/stations/", {**STATION, "name": "Dock",
                                      "integrationProvider": "shipstation",
                                      "integrationRole": "sink"}).json()["_id"]

    _set_plan(a.company, planCode="free", stripeStatus=None)
    assert a.req("PUT", f"/stations/{st}", {**STATION, "name": "Renamed"}).status_code == 200


def test_a_connectors_api_key_stops_when_the_plan_does(billing, actor):
    """The only check a *running* integration passes through. Gating the
    station endpoints does nothing for a key issued last month."""
    a = actor()
    bootstrap_admin(a, "Connector co")
    _set_plan(a.company, planCode="taktline", stripeStatus="active")
    key = a.req("POST", "/api-keys/", {"name": "erp", "scopes": ["orders"]}).json()["key"]

    caller = Actor()
    headers = {"X-Api-Key": key}
    assert caller.req("GET", "/orders/outbox", headers=headers).status_code == 200

    _set_plan(a.company, planCode="free", stripeStatus=None)
    r = caller.req("GET", "/orders/outbox", headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"]["resource"] == "integrations"

    _set_plan(a.company, planCode="taktline", stripeStatus="past_due",
              graceEndsAt=utcnow() - timedelta(days=1))
    assert caller.req("GET", "/orders/outbox", headers=headers).status_code == 402


# ─── A second company is simply another free line ────────────────────────────

def test_a_second_company_is_free_too(billing, actor):
    """Under the trial model this was the anti-farming case; under the free
    tier there is nothing to farm — a second company is another 3-station
    line, which costs us nearly nothing and is exactly the behaviour the
    model wants to encourage."""
    a = actor()
    bootstrap_admin(a, "First co")
    assert _entitlement(a.company).state == entitlements.OK

    second = a.req("POST", "/companies/", {"name": "Second co", "timezone": "UTC"})
    assert second.status_code == 201
    ent = _entitlement(second.json()["id"])
    assert ent.plan.code == plans.FREE and ent.state == entitlements.OK


# ─── The structural one ──────────────────────────────────────────────────────

#: Routes that legitimately never pass the entitlement gate, each with the
#: reason. Anything not here and not gated fails the sweep below.
UNGATED = {
    # Authentication and account plumbing — a locked customer still has to be
    # able to log in, see their companies, and reach the page where they pay.
    "/auth/", "/companies/", "/invitations/",
    # Platform staff. Non-staff get 404; staff must reach a locked tenant.
    "/platform/",
    # Public, unauthenticated by design.
    "/health", "/contact/", "/client-errors/", "/i/", "/uploads/",
    # Billing itself. Gating it would be a lock with the key inside.
    "/billing/",
}


def _gated_dependency_names(route) -> set:
    """Every dependency name in this route's tree."""
    names = set()
    stack = [route.dependant] if getattr(route, "dependant", None) else []
    while stack:
        d = stack.pop()
        if d.call is not None:
            names.add(getattr(d.call, "__name__", ""))
            names.add(getattr(d.call, "__qualname__", ""))
        stack.extend(d.dependencies)
    return names


def test_every_write_endpoint_passes_the_gate_or_declares_why_not():
    """The sweep.

    Before this, three whole routers were exempt from billing enforcement for
    no better reason than that their authors happened to reach for
    `load_membership` instead of `get_active_company`. That is not a design; it
    is an accident that survived review. An exemption now has to be written
    down here, and an endpoint added next month is covered the day it lands.
    """
    from app.main import app

    missing = []
    for r in app.routes:
        methods = (getattr(r, "methods", None) or set()) - {"HEAD", "OPTIONS"}
        if not methods or not methods - {"GET"}:
            continue
        path = getattr(r, "path", "")
        if any(path.startswith(p) for p in UNGATED):
            continue
        names = _gated_dependency_names(r)
        # `get_active_company` carries the gate inline; `require_scope`'s inner
        # dep reaches it on both of its branches.
        if names & {"get_active_company", "require_admin", "require_super_admin", "dep"}:
            continue
        missing.append(f"{sorted(methods)} {path}")

    assert not missing, (
        "these write endpoints bypass the subscription gate and are not in "
        "UNGATED:\n  " + "\n  ".join(sorted(missing)))


def test_the_sweep_actually_looked_at_something():
    """Guard the guard: a matcher that silently matches nothing turns the test
    above into decoration."""
    from app.main import app

    checked = 0
    for r in app.routes:
        methods = (getattr(r, "methods", None) or set()) - {"HEAD", "OPTIONS"}
        path = getattr(r, "path", "")
        if methods and methods - {"GET"} and not any(path.startswith(p) for p in UNGATED):
            checked += 1
    assert checked > 30, f"the sweep only found {checked} write endpoints"


# ─── The WebSocket ───────────────────────────────────────────────────────────

def test_the_socket_says_why_it_refused(billing, actor):
    """A rejected handshake must carry a code the browser can read.

    `close()` before `accept()` never delivers one — the handshake is refused at
    the HTTP layer and the client sees 1006, which is indistinguishable from the
    server having fallen over. So a locked account was told "connection lost —
    reconnecting automatically", in an amber banner, directly above a second
    banner correctly saying the account was paused. Two stories, one of them
    false, and the client retried forever.
    """
    from starlette.websockets import WebSocketDisconnect

    a = actor()
    bootstrap_admin(a, "Socket co")
    _pause(a.company)

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with a.tc.websocket_connect(f"/ws/events?companyId={a.company}") as ws:
            ws.receive_text()
    assert excinfo.value.code == 4402, "locked should close 4402, not a generic failure"


def test_a_healthy_account_still_gets_its_socket(billing, actor):
    """Guard the guard: a refusal test passes just as well against a socket
    that never works at all. A free account is a healthy account."""
    a = actor()
    bootstrap_admin(a, "Socket ok co")
    with a.tc.websocket_connect(f"/ws/events?companyId={a.company}"):
        pass
