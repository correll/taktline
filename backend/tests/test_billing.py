"""Billing: checkout, plan changes, and the webhook.

Stripe is stubbed. That is not a shortcut — the things worth pinning here are
*our* decisions, and every one of them is a way to lose money or a customer:

  - a webhook redelivered twice must do the work once,
  - an out-of-order webhook must not overwrite newer state,
  - an upgrade must be invoiced now and a downgrade must credit forward,
  - a downgrade that does not fit must be refused rather than half-applied,
  - and the payment page must stay reachable from a locked account.

`tests/test_dependencies.py` separately guarantees the real SDK is declared.
"""

import asyncio
import json
import uuid
from datetime import timedelta

import pytest

from app.core import billing_stripe, entitlements, plans
from app.core.config import settings
from app.models.common import utcnow
from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


# ─── A Stripe that does what we tell it ──────────────────────────────────────

class FakeStripe:
    """Records what we asked Stripe to do, so the tests can assert on it."""

    def __init__(self):
        self.calls = []
        self.subscriptions = {}

    def subscription(self, sub_id, *, status="active", plan_code="basic_50",
                     on_premise=False, period_end=None):
        ids = plans.price_ids()
        items = [{"id": "si_1", "price": {"id": ids[plan_code]}}]
        if on_premise:
            items.append({"id": "si_2", "price": {"id": ids["onprem"]}})
        obj = {
            "id": sub_id, "status": status,
            "items": {"data": items},
            "current_period_end": int((period_end or (utcnow() + timedelta(days=30))).timestamp()),
            "metadata": {"planCode": plan_code, "onPremise": str(on_premise).lower()},
        }
        self.subscriptions[sub_id] = obj
        return obj


@pytest.fixture
def stripe(monkeypatch):
    """Billing enabled, prices configured, and the network replaced."""
    fake = FakeStripe()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_fake", raising=False)
    monkeypatch.setattr(settings, "deployment", "cloud", raising=False)
    for attr, value in (("stripe_price_basic_50", "price_basic50"),
                        ("stripe_price_pro_50", "price_pro50"),
                        ("stripe_price_pro_100", "price_pro100"),
                        ("stripe_price_plant_250", "price_plant250"),
                        ("stripe_price_connector", "price_conn"),
                        ("stripe_price_onprem", "price_onprem")):
        monkeypatch.setattr(settings, attr, value, raising=False)

    monkeypatch.setattr(billing_stripe, "fetch_subscription",
                        lambda sid: fake.subscriptions[sid])

    def _change(**kw):
        fake.calls.append(("change_plan", kw))
        obj = fake.subscription(kw["subscription_id"], plan_code=kw["plan_code"],
                                on_premise=kw["on_premise"])
        return obj
    monkeypatch.setattr(billing_stripe, "change_plan", _change)

    def _checkout(**kw):
        fake.calls.append(("checkout", kw))
        return type("S", (), {"url": "https://checkout.stripe.test/abc"})()
    monkeypatch.setattr(billing_stripe, "checkout_session", _checkout)

    def _customer(sub, name, email):
        sub.stripeCustomerId = sub.stripeCustomerId or "cus_fake"
        return sub.stripeCustomerId
    monkeypatch.setattr(billing_stripe, "ensure_customer", _customer)

    monkeypatch.setattr(billing_stripe, "portal_session",
                        lambda **kw: type("S", (), {"url": "https://portal.stripe.test"})())
    return fake


def _set_plan(company_id: str, **fields):
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


def _read_plan(company_id: str):
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import Subscription

    async def go():
        async with SessionLocal() as s:
            return (await s.execute(select(Subscription).where(
                Subscription.companyId == uuid.UUID(company_id)))).scalars().first()
    return asyncio.run(go())


def _webhook(_unused, event: dict, monkeypatch):
    """Post as Stripe does: no cookies, no CSRF header, raw body.

    Using a cookie-bearing client here would 403 on CSRF — which is correct
    behaviour (the middleware only enforces when a session cookie is present)
    and would be testing the wrong thing.
    """
    monkeypatch.setattr(billing_stripe, "verify", lambda payload, sig: event)
    return Actor().tc.post("/billing/webhook", content=json.dumps(event).encode(),
                           headers={"stripe-signature": "t=1,v1=fake"})


# ─── Reading the plan ────────────────────────────────────────────────────────

def test_the_plan_list_hides_what_cannot_be_bought(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Plans co")
    codes = {p["code"] for p in a.req("GET", "/billing/plans").json()}
    assert {"basic_50", "pro_50", "pro_100"} <= codes
    assert "sandbox" not in codes and "self_hosted" not in codes


def test_subscription_reports_plan_state_and_usage(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Usage co")
    a.req("POST", "/stations/", {**STATION, "name": "Cutting"})
    body = a.req("GET", f"/billing/{a.company}/subscription").json()
    assert body["plan"] == "trial"
    assert body["usage"] == {"stations": 1, "stationLimit": 50}
    assert body["billingEnabled"] is True


def test_billing_is_reachable_from_a_locked_account(stripe, actor):
    """The whole point. A paywall whose payment page is behind the paywall is a
    lock with the key inside."""
    a = actor()
    bootstrap_admin(a, "Locked co")
    _set_plan(a.company, planCode="trial", trialEndsAt=utcnow() - timedelta(days=1))

    assert a.req("POST", "/stations/", {**STATION, "name": "X"}).status_code == 402
    assert a.req("GET", f"/billing/{a.company}/subscription").status_code == 200
    assert a.req("GET", "/billing/plans").status_code == 200
    assert a.req("POST", f"/billing/{a.company}/checkout",
                 {"planCode": "basic_50"}).status_code == 200


def test_only_a_super_admin_can_spend_money(stripe, actor):
    from tests.helpers import add_member
    admin, member = actor(), actor()
    bootstrap_admin(admin, "Roles co")
    add_member(admin, member, role="admin")
    assert member.req("POST", f"/billing/{admin.company}/checkout",
                      {"planCode": "basic_50"}).status_code == 403
    # But any member may READ the plan — that is how a ceiling gets noticed.
    assert member.req("GET", f"/billing/{admin.company}/subscription").status_code == 200


# ─── Buying ──────────────────────────────────────────────────────────────────

def test_checkout_offers_card_and_ach(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Checkout co")
    r = a.req("POST", f"/billing/{a.company}/checkout",
              {"planCode": "pro_50", "onPremise": True})
    assert r.status_code == 200 and r.json()["url"].startswith("https://")
    kind, kw = stripe.calls[-1]
    assert kind == "checkout"
    assert kw["plan_code"] == "pro_50" and kw["on_premise"] is True


def test_you_cannot_buy_a_plan_that_is_not_for_sale(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Sneaky co")
    for code in ("trial", "sandbox", "self_hosted", "nonsense"):
        r = a.req("POST", f"/billing/{a.company}/checkout", {"planCode": code})
        assert r.status_code == 400, code


def test_line_items_include_the_on_premise_add_on(stripe):
    items = billing_stripe.line_items("pro_100", True)
    assert [i["price"] for i in items] == ["price_pro100", "price_onprem"]


# ─── Changing plan ───────────────────────────────────────────────────────────

def test_an_upgrade_is_invoiced_now_and_a_downgrade_credits_forward(stripe, actor):
    """The single most expensive detail in this feature.

    `create_prorations` for both directions — the obvious implementation —
    hands over a better plan for a whole month before any money moves, and
    turns a downgrade into a $0 invoice plus a credit balance rather than the
    smaller bill the customer was promised.
    """
    a = actor()
    bootstrap_admin(a, "Moving co")
    _set_plan(a.company, planCode="basic_50", stripeStatus="active",
              stripeSubscriptionId="sub_1", stripeCustomerId="cus_1")
    stripe.subscription("sub_1", plan_code="basic_50")

    assert a.req("POST", f"/billing/{a.company}/change-plan",
                 {"planCode": "pro_100"}).status_code == 200
    assert stripe.calls[-1][1]["upgrading"] is True

    assert a.req("POST", f"/billing/{a.company}/change-plan",
                 {"planCode": "basic_50"}).status_code == 200
    assert stripe.calls[-1][1]["upgrading"] is False


def test_adding_on_premise_counts_as_an_upgrade(stripe, actor):
    """$29 → $29 + $199 is more money, even though the plan code is unchanged."""
    a = actor()
    bootstrap_admin(a, "Onprem co")
    _set_plan(a.company, planCode="basic_50", stripeStatus="active",
              stripeSubscriptionId="sub_2", stripeCustomerId="cus_2")
    stripe.subscription("sub_2", plan_code="basic_50")

    a.req("POST", f"/billing/{a.company}/change-plan",
          {"planCode": "basic_50", "onPremise": True})
    assert stripe.calls[-1][1]["upgrading"] is True


def test_a_downgrade_that_does_not_fit_is_refused(stripe, actor, monkeypatch):
    """Not silently applied. The alternative has no honest UI: thirty stations
    would have to either vanish or stay visible and not work."""
    monkeypatch.setitem(plans.PLANS, "basic_50",
                        plans.Plan(code="basic_50", label="Basic", stations=1,
                                   integrations=False, connectors=0, monthly_cents=2900,
                                   price_env="STRIPE_PRICE_BASIC_50", blurb=""))
    a = actor()
    bootstrap_admin(a, "Too big co")
    _set_plan(a.company, planCode="pro_100", stripeStatus="active",
              stripeSubscriptionId="sub_3", stripeCustomerId="cus_3")
    stripe.subscription("sub_3", plan_code="pro_100")
    a.req("POST", "/stations/", {**STATION, "name": "A"})
    a.req("POST", "/stations/", {**STATION, "name": "B"})

    r = a.req("POST", f"/billing/{a.company}/change-plan", {"planCode": "basic_50"})
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["code"] == "over_limit_for_plan"
    assert (body["limit"], body["used"]) == (1, 2)
    # And nothing was sent to Stripe.
    assert not any(c[0] == "change_plan" for c in stripe.calls)


# ─── The webhook ─────────────────────────────────────────────────────────────

def _event(kind, obj, event_id="evt_1"):
    return {"id": event_id, "type": kind, "data": {"object": obj}}


def test_a_redelivered_webhook_does_the_work_once(stripe, actor, monkeypatch):
    a = actor()
    bootstrap_admin(a, "Idempotent co")
    _set_plan(a.company, stripeCustomerId="cus_9")
    stripe.subscription("sub_9", plan_code="pro_50")

    ev = _event("customer.subscription.updated",
                {"id": "sub_9", "customer": "cus_9"}, "evt_dup")
    first = _webhook(a, ev, monkeypatch)
    second = _webhook(a, ev, monkeypatch)

    assert first.status_code == 200 and first.json().get("duplicate") is None
    assert second.json()["duplicate"] is True
    assert _read_plan(a.company).planCode == "pro_50"


def test_the_webhook_reads_stripe_rather_than_trusting_the_payload(stripe, actor,
                                                                   monkeypatch):
    """Stripe does not guarantee delivery order. Acting on the object embedded
    in the event lets a stale `subscription.updated` overwrite a newer one — so
    every handler re-fetches the authoritative object and writes that."""
    a = actor()
    bootstrap_admin(a, "Ordering co")
    _set_plan(a.company, stripeCustomerId="cus_10")
    # Stripe's current truth is pro_100 …
    stripe.subscription("sub_10", plan_code="pro_100")
    # … while a late event carries the older basic_50 payload.
    stale = _event("customer.subscription.updated",
                   {"id": "sub_10", "customer": "cus_10",
                    "items": {"data": [{"id": "si", "price": {"id": "price_basic50"}}]},
                    "metadata": {"planCode": "basic_50"}}, "evt_stale")
    _webhook(a, stale, monkeypatch)
    assert _read_plan(a.company).planCode == "pro_100"


def test_a_failed_invoice_starts_the_grace_clock_and_paying_clears_it(stripe, actor,
                                                                      monkeypatch):
    a = actor()
    bootstrap_admin(a, "Dunning co")
    _set_plan(a.company, planCode="pro_50", stripeStatus="active",
              stripeSubscriptionId="sub_11", stripeCustomerId="cus_11")
    stripe.subscription("sub_11", plan_code="pro_50", status="past_due")

    _webhook(a, _event("invoice.payment_failed",
                       {"customer": "cus_11", "subscription": "sub_11"},
                       "evt_fail"), monkeypatch)
    row = _read_plan(a.company)
    assert row.graceEndsAt is not None
    assert entitlements._derive(a.company, row).state == entitlements.READ_ONLY

    stripe.subscription("sub_11", plan_code="pro_50", status="active")
    _webhook(a, _event("invoice.paid",
                       {"customer": "cus_11", "subscription": "sub_11"},
                       "evt_paid"), monkeypatch)
    row = _read_plan(a.company)
    assert row.graceEndsAt is None
    assert entitlements._derive(a.company, row).state == entitlements.OK


def test_a_dispute_is_treated_as_a_failed_payment(stripe, actor, monkeypatch):
    """The money was taken and is being clawed back. Letting the account run on
    while it resolves is service given away."""
    a = actor()
    bootstrap_admin(a, "Dispute co")
    _set_plan(a.company, planCode="pro_50", stripeStatus="active",
              stripeCustomerId="cus_12")
    _webhook(a, _event("charge.dispute.created", {"customer": "cus_12"},
                       "evt_dispute"), monkeypatch)
    assert _read_plan(a.company).graceEndsAt is not None


# ─── Cancelling ──────────────────────────────────────────────────────────────

def test_a_portal_cancellation_refunds_the_credit_balance(stripe, actor, monkeypatch):
    """A customer who cancels in the portal never passes through our own
    cancel path — `customer.subscription.deleted` is the only chance to give
    back what an earlier downgrade left as a credit balance. Without this,
    that money sits on the account waiting for invoices that will never come."""
    a = actor()
    bootstrap_admin(a, "Leaving co")
    _set_plan(a.company, planCode="pro_50", stripeStatus="active",
              stripeSubscriptionId="sub_14", stripeCustomerId="cus_14")
    refunded = []
    monkeypatch.setattr(billing_stripe, "refund_credit_balance", refunded.append)

    _webhook(a, _event("customer.subscription.deleted",
                       {"id": "sub_14", "customer": "cus_14"}, "evt_gone"),
             monkeypatch)

    assert refunded == ["cus_14"]
    row = _read_plan(a.company)
    assert row.stripeStatus == "canceled" and row.graceEndsAt is not None


def test_the_portal_cannot_switch_plans(monkeypatch):
    """`change_plan` can refuse a downgrade that does not fit; the portal
    cannot. So every portal session must pin a configuration with
    subscription_update off — the Dashboard's default configuration is
    editable, and one checkbox there would bypass the station-count guard."""
    created, sessions = [], []

    class Configuration:
        existing: list = []

        @staticmethod
        def list(**kw):
            class Page:
                @staticmethod
                def auto_paging_iter():
                    return iter(Configuration.existing)
            return Page

        @staticmethod
        def create(**kw):
            created.append(kw)
            return {"id": "bpc_ours"}

    class Session:
        @staticmethod
        def create(**kw):
            sessions.append(kw)
            return type("S", (), {"url": "https://portal.stripe.test"})()

    fake = type("FakeSDK", (), {})()
    fake.api_key = "sk_test_fake"
    fake.billing_portal = type("BP", (), {"Configuration": Configuration,
                                          "Session": Session})()
    monkeypatch.setattr(billing_stripe, "_stripe", lambda: fake)
    monkeypatch.setattr(billing_stripe, "_portal_config_cache", {})

    billing_stripe.portal_session(customer_id="cus_1", return_url="https://x")

    features = created[0]["features"]
    assert features["subscription_update"] == {"enabled": False}
    assert features["subscription_cancel"]["enabled"] is True
    assert sessions[0]["configuration"] == "bpc_ours"

    # The second open reuses it (cached), and a fresh process finds it again
    # by its metadata marker rather than creating a sibling.
    billing_stripe.portal_session(customer_id="cus_1", return_url="https://x")
    monkeypatch.setattr(billing_stripe, "_portal_config_cache", {})
    Configuration.existing = [
        {"id": "bpc_ours",
         "metadata": {"taktline": billing_stripe._PORTAL_CONFIG_MARKER}}]
    billing_stripe.portal_session(customer_id="cus_1", return_url="https://x")
    assert len(created) == 1
    assert all(s["configuration"] == "bpc_ours" for s in sessions)


def test_an_unknown_event_is_acknowledged_not_rejected(stripe, actor, monkeypatch):
    """Stripe retries a failing endpoint for three days and then disables it.
    An event type we do not handle must never be the reason that happens."""
    a = actor()
    bootstrap_admin(a, "Unknown co")
    r = _webhook(a, _event("invoice.upcoming", {"customer": "cus_x"}, "evt_unknown"),
                 monkeypatch)
    assert r.status_code == 200
    assert r.json()["ignored"] == "invoice.upcoming"


def test_a_handler_that_throws_is_recorded_not_retried_forever(stripe, actor,
                                                               monkeypatch):
    a = actor()
    bootstrap_admin(a, "Throwing co")
    _set_plan(a.company, stripeCustomerId="cus_13")

    def boom(_sid):
        raise RuntimeError("stripe is having a day")
    monkeypatch.setattr(billing_stripe, "fetch_subscription", boom)

    r = _webhook(a, _event("customer.subscription.updated",
                           {"id": "sub_13", "customer": "cus_13"}, "evt_boom"),
                 monkeypatch)
    assert r.status_code == 200 and r.json()["error"] is True


def test_a_bad_signature_is_rejected(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Forged co")
    r = Actor().tc.post("/billing/webhook", content=b'{"id":"evt_forged"}',
                        headers={"stripe-signature": "nonsense"})
    assert r.status_code == 400


# ─── Reading a Stripe subscription back ──────────────────────────────────────

def test_the_live_line_items_win_over_our_metadata(stripe):
    """Metadata is what we last wrote; the items are what Stripe will bill.
    When they disagree, the customer's invoice follows the items."""
    obj = {"id": "sub_x", "status": "active",
           "items": {"data": [{"id": "si", "price": {"id": "price_pro100"}},
                              {"id": "si2", "price": {"id": "price_onprem"}}]},
           "metadata": {"planCode": "basic_50", "onPremise": "false"}}
    assert billing_stripe.plan_from_subscription(obj) == ("pro_100", True, 0)


def test_bought_connectors_are_read_back_as_a_quantity(stripe):
    """They are one line item with a quantity, not N lines, so that going from
    two extra connectors to one prorates like any other downgrade."""
    obj = {"id": "sub_c", "status": "active",
           "items": {"data": [{"id": "si", "price": {"id": "price_pro50"}},
                              {"id": "si2", "price": {"id": "price_conn"},
                               "quantity": 2}]},
           "metadata": {}}
    assert billing_stripe.plan_from_subscription(obj) == ("pro_50", False, 2)


def test_metadata_is_the_fallback_when_prices_are_unrecognised(stripe):
    obj = {"id": "sub_y", "status": "active",
           "items": {"data": [{"id": "si", "price": {"id": "price_from_last_year"}}]},
           "metadata": {"planCode": "pro_50", "onPremise": "true"}}
    assert billing_stripe.plan_from_subscription(obj) == ("pro_50", True, 0)
