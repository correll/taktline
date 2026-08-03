"""Billing: the metered price, checkout, the station-count report, the webhook.

Stripe is stubbed. That is not a shortcut — the things worth pinning here are
*our* decisions, and every one of them is a way to lose money or a customer:

  - the clamp ($29 floor, $2 a station, $399 cap) and the Stripe tiers must be
    the same function, or the invoice disagrees with the pricing page,
  - the station count must be reported when the floor changes, without ever
    blocking the floor change on Stripe being up,
  - a webhook redelivered twice must do the work once,
  - an out-of-order webhook must not overwrite newer state,
  - a cancellation must give back what is owed and never delete anything,
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

    def subscription(self, sub_id, *, status="active", stations=10,
                     on_premise=False, period_end=None):
        ids = plans.price_ids()
        items = [{"id": "si_1", "price": {"id": ids["taktline"]},
                  "quantity": stations}]
        if on_premise:
            items.append({"id": "si_2", "price": {"id": ids["onprem"]},
                          "quantity": 1})
        obj = {
            "id": sub_id, "status": status,
            "items": {"data": items},
            "current_period_end": int((period_end or (utcnow() + timedelta(days=30))).timestamp()),
            "metadata": {"onPremise": str(on_premise).lower()},
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
    monkeypatch.setattr(settings, "stripe_price_taktline", "price_station", raising=False)
    monkeypatch.setattr(settings, "stripe_price_onprem", "price_onprem", raising=False)

    monkeypatch.setattr(billing_stripe, "fetch_subscription",
                        lambda sid: fake.subscriptions[sid])

    def _checkout(**kw):
        fake.calls.append(("checkout", kw))
        return type("S", (), {"url": "https://checkout.stripe.test/abc"})()
    monkeypatch.setattr(billing_stripe, "checkout_session", _checkout)

    def _customer(sub, name, email):
        sub.stripeCustomerId = sub.stripeCustomerId or "cus_fake"
        return sub.stripeCustomerId
    monkeypatch.setattr(billing_stripe, "ensure_customer", _customer)

    def _quantity(sub_id, quantity):
        fake.calls.append(("update_station_quantity", sub_id, quantity))
        return fake.subscriptions.get(sub_id)
    monkeypatch.setattr(billing_stripe, "update_station_quantity", _quantity)

    def _onprem(sub_id, enabled):
        fake.calls.append(("set_on_premise", sub_id, enabled))
        prev = fake.subscriptions[sub_id]
        ids = plans.price_ids()
        stations = next((i.get("quantity", 1) for i in prev["items"]["data"]
                         if i["price"]["id"] == ids["taktline"]), 1)
        return fake.subscription(sub_id, stations=stations, on_premise=enabled)
    monkeypatch.setattr(billing_stripe, "set_on_premise", _onprem)

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


# ─── The price itself ────────────────────────────────────────────────────────

def test_the_clamp_is_the_price_list():
    """The published table, verbatim: the floor bites below 15, the cap at
    200, and in between it is just $2 a station."""
    for stations, cents in [(1, 2900), (3, 2900), (14, 2900),   # floor
                            (15, 3000), (50, 10000), (100, 20000),
                            (199, 39800),                        # last metered
                            (200, 39900), (250, 39900), (100_000, 39900)]:
        assert plans.monthly_cents_for(stations) == cents, stations


def _stripe_volume_price(tiers, quantity):
    """What Stripe's volume mode charges: the tier containing the total
    applies to all units."""
    for tier in tiers:
        if tier["up_to"] == "inf" or quantity <= tier["up_to"]:
            return (tier.get("flat_amount", 0)
                    + tier.get("unit_amount", 0) * quantity)
    raise AssertionError("no tier matched")


def test_the_stripe_tiers_and_the_clamp_are_the_same_function():
    """The one that costs money if it drifts: plans.py computes what the UI
    shows and Stripe computes what the card is charged. They must be equal at
    every station count, including both boundaries."""
    tiers = plans.station_tiers()
    for n in range(1, 301):
        assert _stripe_volume_price(tiers, n) == plans.monthly_cents_for(n), n


def test_the_pricing_endpoint_reports_the_numbers(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Pricing co")
    body = a.req("GET", "/billing/plans").json()
    assert body["freeStations"] == 3
    assert body["perStationCents"] == 200
    assert body["minimumCents"] == 2900 and body["capCents"] == 39900
    assert body["minStations"] == 15 and body["capStations"] == 200
    assert body["onpremCents"] == 19900


def test_line_items_carry_the_station_count_as_quantity(stripe):
    items = billing_stripe.line_items(42, True)
    assert items[0] == {"price": "price_station", "quantity": 42}
    assert items[1]["price"] == "price_onprem"
    # Zero stations still buys the floor — and Stripe refuses quantity 0.
    assert billing_stripe.line_items(0, False)[0]["quantity"] == 1


# ─── Reading the plan ────────────────────────────────────────────────────────

def test_subscription_reports_state_usage_and_price(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Usage co")
    a.req("POST", "/stations/", {**STATION, "name": "Cutting"})
    body = a.req("GET", f"/billing/{a.company}/subscription").json()
    assert body["plan"] == "free"
    assert body["usage"] == {"stations": 1, "stationLimit": 3}
    assert body["monthlyCents"] == 0
    assert body["billingEnabled"] is True

    _set_plan(a.company, planCode="taktline", stripeStatus="active",
              stripeSubscriptionId="sub_u", stripeCustomerId="cus_u")
    body = a.req("GET", f"/billing/{a.company}/subscription").json()
    assert body["plan"] == "taktline"
    assert body["usage"] == {"stations": 1, "stationLimit": None}
    assert body["monthlyCents"] == 2900          # one station = the floor


def test_billing_is_reachable_from_a_paused_account(stripe, actor):
    """The whole point. A paywall whose payment page is behind the paywall is
    a lock with the key inside. A paused account (cancelled, grace over) buys
    again through checkout; one merely past_due fixes its card in the portal."""
    a = actor()
    bootstrap_admin(a, "Locked co")
    _set_plan(a.company, planCode="taktline", stripeStatus="canceled",
              stripeCustomerId="cus_l",
              graceEndsAt=utcnow() - timedelta(days=1))

    assert a.req("POST", "/stations/", {**STATION, "name": "X"}).status_code == 402
    assert a.req("GET", f"/billing/{a.company}/subscription").status_code == 200
    assert a.req("GET", "/billing/plans").status_code == 200
    assert a.req("POST", f"/billing/{a.company}/checkout", {}).status_code == 200
    assert a.req("POST", f"/billing/{a.company}/portal", {}).status_code == 200


def test_only_a_super_admin_can_spend_money(stripe, actor):
    from tests.helpers import add_member
    admin, member = actor(), actor()
    bootstrap_admin(admin, "Roles co")
    add_member(admin, member, role="admin")
    assert member.req("POST", f"/billing/{admin.company}/checkout",
                      {}).status_code == 403
    # But any member may READ the plan — that is how a ceiling gets noticed.
    assert member.req("GET", f"/billing/{admin.company}/subscription").status_code == 200


# ─── Buying ──────────────────────────────────────────────────────────────────

def test_checkout_carries_the_current_station_count(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Checkout co")
    a.req("POST", "/stations/", {**STATION, "name": "A"})
    a.req("POST", "/stations/", {**STATION, "name": "B"})
    r = a.req("POST", f"/billing/{a.company}/checkout", {"onPremise": True})
    assert r.status_code == 200 and r.json()["url"].startswith("https://")
    kind, kw = stripe.calls[-1]
    assert kind == "checkout"
    assert kw["stations"] == 2 and kw["on_premise"] is True


def test_a_live_subscription_cannot_buy_a_second_one(stripe, actor):
    """Even past_due: the recovery path for a failing card is the portal, and
    a second checkout would quietly mint a second subscription."""
    a = actor()
    bootstrap_admin(a, "Double co")
    for status in ("active", "incomplete", "past_due"):
        _set_plan(a.company, planCode="taktline", stripeStatus=status,
                  stripeSubscriptionId="sub_d", stripeCustomerId="cus_d")
        assert a.req("POST", f"/billing/{a.company}/checkout",
                     {}).status_code == 409, status


# ─── The station count follows the floor ─────────────────────────────────────

def test_creating_and_deleting_a_station_reports_the_count(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Metered co")
    _set_plan(a.company, planCode="taktline", stripeStatus="active",
              stripeSubscriptionId="sub_m", stripeCustomerId="cus_m")
    stripe.subscription("sub_m", stations=1)

    st = a.req("POST", "/stations/", {**STATION, "name": "A"}).json()["_id"]
    assert ("update_station_quantity", "sub_m", 1) in stripe.calls

    a.req("POST", "/stations/", {**STATION, "name": "B"})
    assert ("update_station_quantity", "sub_m", 2) in stripe.calls

    a.req("DELETE", f"/stations/{st}")
    assert stripe.calls[-1] == ("update_station_quantity", "sub_m", 1)


def test_a_free_account_reports_nothing(stripe, actor):
    """No subscription, nothing to report — and no Stripe call to fail."""
    a = actor()
    bootstrap_admin(a, "Free co")
    a.req("POST", "/stations/", {**STATION, "name": "A"})
    assert not any(c[0] == "update_station_quantity" for c in stripe.calls)


def test_stripe_being_down_never_blocks_the_floor(stripe, actor, monkeypatch):
    """The report is best-effort by design: a shop must be able to draw its
    line while Stripe has a bad day. The count self-corrects on the next
    change."""
    a = actor()
    bootstrap_admin(a, "Resilient co")
    _set_plan(a.company, planCode="taktline", stripeStatus="active",
              stripeSubscriptionId="sub_r", stripeCustomerId="cus_r")

    def boom(sub_id, quantity):
        raise RuntimeError("stripe is having a day")
    monkeypatch.setattr(billing_stripe, "update_station_quantity", boom)

    assert a.req("POST", "/stations/", {**STATION, "name": "A"}).status_code == 201


# ─── The one plan change: on-premise ─────────────────────────────────────────

def test_toggling_on_premise(stripe, actor):
    a = actor()
    bootstrap_admin(a, "Onprem co")
    _set_plan(a.company, planCode="taktline", stripeStatus="active",
              stripeSubscriptionId="sub_o", stripeCustomerId="cus_o")
    stripe.subscription("sub_o", stations=5)

    r = a.req("POST", f"/billing/{a.company}/on-premise", {"enabled": True})
    assert r.status_code == 200, r.text
    assert ("set_on_premise", "sub_o", True) in stripe.calls
    assert r.json()["onPremise"] is True

    r = a.req("POST", f"/billing/{a.company}/on-premise", {"enabled": False})
    assert r.json()["onPremise"] is False


def test_on_premise_needs_a_subscription(stripe, actor):
    a = actor()
    bootstrap_admin(a, "No sub co")
    assert a.req("POST", f"/billing/{a.company}/on-premise",
                 {"enabled": True}).status_code == 409


# ─── The webhook ─────────────────────────────────────────────────────────────

def _event(kind, obj, event_id="evt_1"):
    return {"id": event_id, "type": kind, "data": {"object": obj}}


def test_a_redelivered_webhook_does_the_work_once(stripe, actor, monkeypatch):
    a = actor()
    bootstrap_admin(a, "Idempotent co")
    _set_plan(a.company, stripeCustomerId="cus_9")
    stripe.subscription("sub_9", stations=7)

    ev = _event("customer.subscription.updated",
                {"id": "sub_9", "customer": "cus_9"}, "evt_dup")
    first = _webhook(a, ev, monkeypatch)
    second = _webhook(a, ev, monkeypatch)

    assert first.status_code == 200 and first.json().get("duplicate") is None
    assert second.json()["duplicate"] is True
    assert _read_plan(a.company).planCode == "taktline"


def test_the_webhook_reads_stripe_rather_than_trusting_the_payload(stripe, actor,
                                                                   monkeypatch):
    """Stripe does not guarantee delivery order. Acting on the object embedded
    in the event lets a stale `subscription.updated` overwrite a newer one — so
    every handler re-fetches the authoritative object and writes that."""
    a = actor()
    bootstrap_admin(a, "Ordering co")
    _set_plan(a.company, stripeCustomerId="cus_10")
    # Stripe's current truth carries the on-premise add-on …
    stripe.subscription("sub_10", stations=30, on_premise=True)
    # … while a late event carries an older shape without it.
    stale = _event("customer.subscription.updated",
                   {"id": "sub_10", "customer": "cus_10",
                    "items": {"data": [{"id": "si", "quantity": 4,
                                        "price": {"id": "price_station"}}]},
                    "metadata": {"onPremise": "false"}}, "evt_stale")
    _webhook(a, stale, monkeypatch)
    row = _read_plan(a.company)
    assert row.planCode == "taktline" and row.onPremise is True


def test_a_failed_invoice_starts_the_grace_clock_and_paying_clears_it(stripe, actor,
                                                                      monkeypatch):
    a = actor()
    bootstrap_admin(a, "Dunning co")
    _set_plan(a.company, planCode="taktline", stripeStatus="active",
              stripeSubscriptionId="sub_11", stripeCustomerId="cus_11")
    stripe.subscription("sub_11", status="past_due")

    _webhook(a, _event("invoice.payment_failed",
                       {"customer": "cus_11", "subscription": "sub_11"},
                       "evt_fail"), monkeypatch)
    row = _read_plan(a.company)
    assert row.graceEndsAt is not None
    assert entitlements._derive(a.company, row).state == entitlements.READ_ONLY

    stripe.subscription("sub_11", status="active")
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
    _set_plan(a.company, planCode="taktline", stripeStatus="active",
              stripeCustomerId="cus_12")
    _webhook(a, _event("charge.dispute.created", {"customer": "cus_12"},
                       "evt_dispute"), monkeypatch)
    assert _read_plan(a.company).graceEndsAt is not None


# ─── Cancelling ──────────────────────────────────────────────────────────────

def test_a_cancelled_small_line_simply_becomes_free(stripe, actor, monkeypatch):
    """A line that fits the free tier IS the free tier's audience. No grace
    window, no pause — and the credit balance comes back."""
    a = actor()
    bootstrap_admin(a, "Small co")
    a.req("POST", "/stations/", {**STATION, "name": "One"})
    _set_plan(a.company, planCode="taktline", stripeStatus="active",
              stripeSubscriptionId="sub_14", stripeCustomerId="cus_14")
    refunded = []
    monkeypatch.setattr(billing_stripe, "refund_credit_balance", refunded.append)

    _webhook(a, _event("customer.subscription.deleted",
                       {"id": "sub_14", "customer": "cus_14"}, "evt_gone"),
             monkeypatch)

    row = _read_plan(a.company)
    assert row.planCode == "free" and row.graceEndsAt is None
    assert row.stripeSubscriptionId is None
    assert refunded == ["cus_14"]
    assert entitlements._derive(a.company, row).state == entitlements.OK


def test_a_cancelled_big_line_pauses_after_grace_and_is_never_deleted(stripe, actor,
                                                                      monkeypatch):
    a = actor()
    bootstrap_admin(a, "Big co")
    _set_plan(a.company, planCode="taktline", stripeStatus="active",
              stripeSubscriptionId="sub_15", stripeCustomerId="cus_15")
    stripe.subscription("sub_15", stations=1)
    for i in range(4):                              # one more than free covers
        assert a.req("POST", "/stations/",
                     {**STATION, "name": f"S{i}"}).status_code == 201
    refunded = []
    monkeypatch.setattr(billing_stripe, "refund_credit_balance", refunded.append)

    _webhook(a, _event("customer.subscription.deleted",
                       {"id": "sub_15", "customer": "cus_15"}, "evt_gone2"),
             monkeypatch)

    row = _read_plan(a.company)
    assert row.planCode == "taktline" and row.stripeStatus == "canceled"
    assert row.graceEndsAt is not None
    assert refunded == ["cus_15"]
    assert entitlements._derive(a.company, row).state == entitlements.READ_ONLY
    # After the week: paused, not deleted. The stations are all still there.
    _set_plan(a.company, graceEndsAt=utcnow() - timedelta(minutes=1))
    row = _read_plan(a.company)
    assert entitlements._derive(a.company, row).state == entitlements.LOCKED
    assert a.req("GET", "/stations/").status_code == 402   # paused, but present


def test_the_portal_cannot_switch_plans(monkeypatch):
    """There is no plan to switch to any more, but the property still matters:
    the portal must not be able to edit the subscription's items — the station
    quantity is *reported* by the app, and a customer hand-editing it in
    Stripe's UI would disconnect the price from the floor. The configuration
    is pinned in code because the Dashboard default is editable."""
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


# ─── Webhook plumbing ────────────────────────────────────────────────────────

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
           "items": {"data": [{"id": "si", "price": {"id": "price_station"},
                               "quantity": 42},
                              {"id": "si2", "price": {"id": "price_onprem"}}]},
           "metadata": {"onPremise": "false"}}
    assert billing_stripe.shape_of_subscription(obj) == (42, True)


def test_metadata_is_the_fallback_when_prices_are_unrecognised(stripe):
    obj = {"id": "sub_y", "status": "active",
           "items": {"data": [{"id": "si", "price": {"id": "price_from_last_year"}}]},
           "metadata": {"onPremise": "true"}}
    assert billing_stripe.shape_of_subscription(obj) == (None, True)
