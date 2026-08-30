"""Vouchers and staff-set plans — the two ways an account gets a paid tier
without a Stripe checkout.

A voucher (e.g. CAMA2026) is minted by a platform owner and grants a paid plan
free for N calendar months; redeeming stamps the subscription row and the
entitlement gate derives "back to Free" from the clock. A staff-set plan is the
mechanism behind "Plant and Enterprise are set on the subscription by staff" —
no clock, honoured until staff change it, never demoted by a webhook.

The properties pinned here are the ones that cost money when wrong: a voucher
is once per company and its cap cannot be raced past; the grant ends by itself
with no lock and no grace theatre; a real subscription supersedes the clock but
keeps the attribution; and none of the platform surface exists for non-staff.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core import plans
from app.core.config import settings
from app.models.common import utcnow
from tests.helpers import Actor, add_member, bootstrap_admin


@pytest.fixture
def billing_on(monkeypatch):
    """Billing enabled, so the gate reads the subscription row instead of
    answering "self-hosted, unmetered". No Stripe API is reached — the voucher
    path deliberately never talks to Stripe."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(settings, "deployment", "cloud", raising=False)


@pytest.fixture
def owner(billing_on):
    """An actor whose email is on the PLATFORM_OWNER_EMAILS allowlist."""
    a = Actor()
    email = bootstrap_admin(a, company="Owner HQ")
    old = settings.platform_owner_emails
    settings.platform_owner_emails = email
    yield a
    settings.platform_owner_emails = old


def _set_sub(company_id: str, **fields):
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import Subscription

    async def go():
        async with SessionLocal() as s:
            row = (await s.execute(select(Subscription).where(
                Subscription.companyId == uuid.UUID(company_id)))).scalars().first()
            for k, v in fields.items():
                setattr(row, k, v)
            await s.commit()
    asyncio.run(go())


def _mint(owner: Actor, code=None, **over) -> dict:
    # Vouchers are platform-global and the tests share one database, so every
    # test mints its own code unless it is asserting something about a name.
    code = code or f"V{uuid.uuid4().hex[:8].upper()}"
    body = {"code": code, "plan": "shop", "months": 6, **over}
    r = owner.req("POST", "/platform/vouchers", body)
    assert r.status_code == 201, r.text
    return r.json()


def _redeem(a: Actor, code: str):
    return a.req("POST", f"/billing/{a.company}/voucher", {"code": code})


# ─── The platform surface ────────────────────────────────────────────────────

def test_non_staff_get_404_on_every_voucher_endpoint(billing_on):
    a = Actor()
    bootstrap_admin(a)
    assert a.req("GET", "/platform/vouchers").status_code == 404
    assert a.req("POST", "/platform/vouchers",
                 {"code": "X123", "plan": "shop", "months": 6}).status_code == 404
    assert a.req("DELETE", f"/platform/vouchers/{uuid.uuid4()}").status_code == 404
    assert a.req("PUT", f"/platform/companies/{a.company}/plan",
                 {"plan": "enterprise"}).status_code == 404


def test_support_may_list_but_not_mint(owner):
    support = Actor()
    email = bootstrap_admin(support, company="Support Home")
    target = [u for u in owner.req("GET", "/platform/users").json()
              if u["email"] == email][0]
    r = owner.req("PUT", f"/platform/users/{target['id']}/platform-role",
                  {"role": "support"})
    assert r.status_code == 204, r.text

    assert support.req("GET", "/platform/vouchers").status_code == 200
    assert support.req("POST", "/platform/vouchers",
                       {"code": "X123", "plan": "shop", "months": 6}).status_code == 404
    assert support.req("PUT", f"/platform/companies/{support.company}/plan",
                       {"plan": "plant"}).status_code == 404


def test_a_voucher_grants_only_a_paid_tier(owner):
    for plan in ("free", "sandbox", "self_hosted", "nonsense"):
        r = owner.req("POST", "/platform/vouchers",
                      {"code": f"BAD{plan[:4].upper()}", "plan": plan, "months": 6})
        assert r.status_code == 400, plan


def test_a_duplicate_code_is_refused_case_insensitively(owner):
    code = _mint(owner)["code"]
    r = owner.req("POST", "/platform/vouchers",
                  {"code": f"#{code.lower()}", "plan": "shop", "months": 3})
    assert r.status_code == 409


# ─── Redemption ──────────────────────────────────────────────────────────────

def test_a_company_redeems_shop_free_for_six_months(owner):
    code = _mint(owner, note="CAMA members, 2026 campaign")["code"]

    a = Actor()
    bootstrap_admin(a, company="CAMA Member Shop")
    # As printed on the flyer: with the #, in lowercase. Both are noise.
    r = _redeem(a, f"#{code.lower()}")
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub["plan"] == "shop" and sub["state"] == "ok"
    assert sub["stationLimit"] == plans.SHOP_STATIONS
    assert sub["integrations"] is True
    assert sub["monthlyCents"] == 0            # free is the whole point
    assert sub["hasPaymentMethod"] is False    # and no card was ever asked for
    assert sub["voucherCode"] == code

    ends = datetime.fromisoformat(sub["compedUntil"])
    months_out = (ends.year - utcnow().year) * 12 + ends.month - utcnow().month
    assert months_out == 6

    listed = [v for v in owner.req("GET", "/platform/vouchers").json()
              if v["code"] == code][0]
    assert listed["redeemedCount"] == 1


def test_a_voucher_is_once_per_company(owner):
    code = _mint(owner)["code"]
    a = Actor()
    bootstrap_admin(a)
    assert _redeem(a, code).status_code == 200
    # Expire the grant, so the account is back on Free — the second redeem is
    # refused by the ledger, not by "already on Shop".
    _set_sub(a.company, compedUntil=utcnow() - timedelta(days=1))
    r = _redeem(a, code)
    assert r.status_code == 400
    assert "already been used" in r.json()["detail"]


def test_a_capped_voucher_stops_at_its_cap(owner):
    code = _mint(owner, maxRedemptions=1)["code"]
    first, second = Actor(), Actor()
    bootstrap_admin(first, company="First in line")
    bootstrap_admin(second, company="Second in line")
    assert _redeem(first, code).status_code == 200
    r = _redeem(second, code)
    assert r.status_code == 400
    assert "fully redeemed" in r.json()["detail"]


def test_an_expired_code_and_an_unknown_code(owner):
    code = _mint(owner,
                 expiresAt=(utcnow() - timedelta(days=1)).isoformat())["code"]
    a = Actor()
    bootstrap_admin(a)
    assert _redeem(a, code).status_code == 400
    assert _redeem(a, "NOSUCHCODE").status_code == 404
    assert _redeem(a, "#").status_code == 404


def test_only_a_super_admin_may_redeem(owner):
    code = _mint(owner)["code"]
    admin, member = Actor(), Actor()
    bootstrap_admin(admin)
    add_member(admin, member, role="admin")
    r = member.req("POST", f"/billing/{admin.company}/voucher", {"code": code})
    assert r.status_code == 403


def test_a_sandbox_cannot_redeem(owner):
    code = _mint(owner)["code"]
    a = Actor()
    r = a.req("POST", "/auth/sandbox")
    assert r.status_code == 200
    a.company = r.json()["companyId"]
    assert _redeem(a, code).status_code == 403


def test_a_subscribed_account_is_refused(owner):
    code = _mint(owner)["code"]
    a = Actor()
    bootstrap_admin(a)
    _set_sub(a.company, planCode=plans.SHOP, stripeStatus="active",
             stripeSubscriptionId="sub_live", stripeCustomerId="cus_live")
    r = _redeem(a, code)
    assert r.status_code == 400
    assert "already has a subscription" in r.json()["detail"]


# ─── The grant ends by itself ────────────────────────────────────────────────

def test_the_grant_ends_by_itself_with_no_lock_and_no_grace(owner):
    code = _mint(owner)["code"]
    a = Actor()
    bootstrap_admin(a)
    assert _redeem(a, code).status_code == 200

    _set_sub(a.company, compedUntil=utcnow() - timedelta(minutes=1))
    sub = a.req("GET", f"/billing/{a.company}/subscription").json()
    # Simply Free again: writable, nothing paused, nothing deleted. The reason
    # says why, so the UI can explain instead of looking broken.
    assert sub["plan"] == "free" and sub["state"] == "ok"
    assert sub["reason"] == "voucher_expired"
    assert sub["stationLimit"] == plans.FREE_STATIONS
    assert sub["integrations"] is False


def test_deleting_a_voucher_keeps_grants_already_made(owner):
    v = _mint(owner)
    a = Actor()
    bootstrap_admin(a)
    assert _redeem(a, v["code"]).status_code == 200
    assert owner.req("DELETE", f"/platform/vouchers/{v['id']}").status_code == 204

    b = Actor()
    bootstrap_admin(b, company="Too late")
    assert _redeem(b, v["code"]).status_code == 404          # no new redemptions
    sub = a.req("GET", f"/billing/{a.company}/subscription").json()
    assert sub["plan"] == "shop" and sub["state"] == "ok"    # promise kept


def test_a_real_subscription_supersedes_the_clock_but_keeps_attribution(monkeypatch):
    from app.core import billing_stripe
    from app.db.tables import Subscription
    from app.routers.billing import _apply_subscription

    monkeypatch.setattr(billing_stripe, "shape_of_subscription", lambda obj: (1, False))
    row = Subscription(planCode=plans.SHOP, onPremise=False,
                       compedUntil=utcnow() + timedelta(days=90),
                       voucherCode="CAMA2026")
    _apply_subscription(row, {"id": "sub_1", "status": "active"})
    assert row.compedUntil is None
    assert row.voucherCode == "CAMA2026"       # how conversions get counted
    assert row.planCode == plans.SHOP and row.stripeStatus == "active"


def test_six_months_from_aug_31_is_feb_28(monkeypatch):
    from app.routers import billing as billing_router

    monkeypatch.setattr(billing_router, "utcnow",
                        lambda: datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc))
    assert billing_router._months_from_now(6) == datetime(
        2027, 2, 28, 12, 0, tzinfo=timezone.utc)


# ─── Staff-set plans ─────────────────────────────────────────────────────────

def test_owner_sets_a_plan_by_hand_and_the_gate_honours_it(owner):
    a = Actor()
    bootstrap_admin(a, company="Big Plant Deal")
    r = owner.req("PUT", f"/platform/companies/{a.company}/plan",
                  {"plan": "enterprise"})
    assert r.status_code == 200, r.text

    sub = a.req("GET", f"/billing/{a.company}/subscription").json()
    assert sub["plan"] == "enterprise" and sub["state"] == "ok"
    assert sub["stationLimit"] is None         # uncapped, not a big sentinel
    assert sub["integrations"] is True

    actions = [e["action"] for e in owner.req("GET", "/platform/audit").json()]
    assert "company_plan_set" in actions


def test_a_hand_set_plan_replaces_a_voucher_clock(owner):
    code = _mint(owner)["code"]
    a = Actor()
    bootstrap_admin(a)
    assert _redeem(a, code).status_code == 200
    assert owner.req("PUT", f"/platform/companies/{a.company}/plan",
                     {"plan": "plant"}).status_code == 200
    sub = a.req("GET", f"/billing/{a.company}/subscription").json()
    assert sub["plan"] == "plant" and sub["compedUntil"] is None


def test_staff_cannot_set_a_plan_nobody_should_hold(owner):
    a = Actor()
    bootstrap_admin(a)
    for plan in ("sandbox", "self_hosted", "taktline", "nonsense"):
        r = owner.req("PUT", f"/platform/companies/{a.company}/plan", {"plan": plan})
        assert r.status_code == 400, plan


def test_a_webhook_never_demotes_a_staff_set_plan(monkeypatch):
    """The `Plan.self_serve` guard: a Plant account has a real, hand-made
    Stripe subscription, and the next subscription event must refresh its
    billing state without touching its plan code."""
    from app.core import billing_stripe
    from app.db.tables import Subscription
    from app.routers.billing import _apply_subscription

    monkeypatch.setattr(billing_stripe, "shape_of_subscription", lambda obj: (40, False))
    row = Subscription(planCode=plans.PLANT, onPremise=False)
    _apply_subscription(row, {"id": "sub_neg", "status": "active"})
    assert row.planCode == plans.PLANT
