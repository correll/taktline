"""The Stripe layer: checkout, the customer portal, plan changes, and webhooks.

Stripe collects; this module is the thin, testable seam between it and the
`subscriptions` table. Everything that decides *policy* lives in `plans.py` and
`entitlements.py` — what is here is the mechanics of talking to Stripe and the
handful of places where Stripe's behaviour is surprising enough to be worth
writing down.

Four of those, because each one is a way to lose money or a customer:

**1. Proration is not one setting — and the station quantity never prorates.**
A station count changes many times a month while someone draws their floor;
prorating each change would produce a drizzle of cent-sized line items and an
unreadable invoice, so quantity updates use `proration_behavior='none'` and
the count current at the period boundary is what the month costs. The
**on-premise add-on** is different: turning it on grants a licence *now*, so
it is invoiced now (`always_invoice`); turning it off credits forward
(`create_prorations` — the obvious single setting for both directions would
either hand out a licence free for a month or bill for one being returned).

**2. Webhooks are triggers, not payloads.** Stripe does not guarantee delivery
order, so acting on the object inside the event means a stale
`subscription.updated` can overwrite a newer one. Every handler re-fetches the
authoritative object and writes that. The event id gives idempotency; the
re-fetch gives ordering.

**3. ACH does not settle at checkout.** A bank debit leaves the subscription
`incomplete` for 3–5 business days, and a return can arrive up to 60 days later
(R05/R07/R10). Service is granted at checkout — refusing it would punish the
customer for choosing the payment method we prefer — and a later failure is
handled by the ordinary `invoice.payment_failed` path.

**4. A downgrade credit is not a refund.** Stripe holds it as a customer credit
balance and applies it to future invoices; it never returns it. On
cancellation we refund it explicitly, because keeping money for service we will
not deliver is not a thing this product does.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import HTTPException

from . import plans
from .config import settings


def _stripe():
    """The configured Stripe client, or a 503 explaining why there isn't one."""
    if not settings.billing_enabled:
        raise HTTPException(503, "Billing is not configured on this deployment")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


def _plain(obj):
    """A Stripe API object as plain dicts and lists.

    StripeObject stopped being a dict subclass in stripe v15, so `.get()` and
    every other dict idiom raises AttributeError — but only on real API
    objects, never in tests, whose doubles are plain dicts. Converting once at
    each retrieval keeps the rest of this module and the webhook handlers
    dict-shaped on every stripe version. (The first live webhook crashed on
    exactly this: `obj.get("customer")` on a v15 event object.)
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    for name in ("_to_dict_recursive", "to_dict_recursive", "to_dict"):
        fn = getattr(obj, name, None)
        if callable(fn):
            # Recurse through the result: to_dict can be shallow, leaving
            # StripeObjects nested inside.
            return _plain(fn())
    raise TypeError(f"cannot convert {type(obj).__name__} to plain data")


def station_price() -> str:
    price = plans.price_ids().get("taktline")
    if not price:
        raise HTTPException(
            503, f"No Stripe price configured — set {plans.STATION_PRICE_ENV}")
    return price


def onprem_price() -> str:
    price = plans.price_ids().get("onprem")
    if not price:
        raise HTTPException(503, f"No Stripe price configured for on-premise — "
                                 f"set {plans.ONPREM_PRICE_ENV}")
    return price


def line_items(stations: int, on_premise: bool) -> list[dict]:
    """One tiered price whose quantity is the station count, plus the add-on.

    The tiers on the price itself carry the floor and the cap, so Stripe does
    the whole clamp — see `plans.station_tiers()`. Quantity is at least 1: a
    company with no stations yet is still buying the floor, and Stripe refuses
    a zero-quantity line anyway.
    """
    items = [{"price": station_price(), "quantity": max(1, stations)}]
    if on_premise:
        items.append({"price": onprem_price(), "quantity": 1})
    return items


# ─── Customer ────────────────────────────────────────────────────────────────

def ensure_customer(sub, company_name: str, email: str) -> str:
    """The Stripe customer for this company, created once and reused.

    Keyed by our company id in metadata so a human in the Stripe dashboard can
    tell which account they are looking at, and so a webhook that has lost the
    thread can find its way back.
    """
    s = _stripe()
    if sub.stripeCustomerId:
        return sub.stripeCustomerId
    customer = s.Customer.create(
        name=company_name, email=email,
        metadata={"companyId": str(sub.companyId)},
    )
    sub.stripeCustomerId = customer.id
    return customer.id


# ─── Checkout ────────────────────────────────────────────────────────────────

def checkout_session(*, customer_id: str, stations: int, on_premise: bool,
                     company_id: str, success_url: str, cancel_url: str):
    """A hosted checkout for a first purchase.

    Card **and** ACH. ACH is 0.8% capped at $5 against 2.9% + 30¢ for cards, so
    on anything above the entry tier it is worth several percent of revenue —
    and Stripe hosts the mandate flow, which is the part that is genuinely
    fiddly to build.

    **`payment_method_types` is deliberately not passed.** Naming the methods
    here looks like it says "card and ACH" and actually says "card and ACH and
    nothing else, ever, until someone deploys". It pins the list at the moment
    the line was written: Link — Stripe's one-click, which is the single
    cheapest conversion win available to a checkout — is excluded, and so is
    every method added later. Omitting the parameter enables dynamic payment
    methods, which reads the eligible set from Dashboard → Payment methods and
    orders them per customer. The ACH argument above is unaffected: ACH is
    switched on in the Dashboard and then simply offered.
    """
    s = _stripe()
    return s.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=line_items(stations, on_premise),
        # Software subscriptions are taxed inconsistently by state; switching
        # this on retroactively after a year of sales is expensive and
        # unpleasant. See pricing.md.
        automatic_tax={"enabled": True},
        customer_update={"address": "auto", "name": "auto"},
        subscription_data={"metadata": {"companyId": company_id,
                                        "onPremise": str(on_premise).lower()}},
        success_url=success_url,
        cancel_url=cancel_url,
    )


#: Bump when the feature set in `_portal_configuration_id` changes: a new
#: configuration is then created and used, rather than editing one that live
#: portal sessions may still be holding.
#: v2: cancellation switched from at_period_end to immediate-with-proration.
#: The version is in the marker because a configuration already created on the
#: account (live has one) would otherwise be found and reused with the old
#: features forever — bumping the marker supersedes it without migrating it.
_PORTAL_CONFIG_MARKER = "taktline-portal-v2"

#: Configuration id per API key, so the lookup happens once per process rather
#: than once per portal open. Keyed by the key because test and live mode are
#: different accounts with different configuration ids.
_portal_config_cache: dict[str, str] = {}


def _portal_configuration_id(s) -> str:
    """The portal configuration with plan switching OFF, created on first use.

    **Passed explicitly because the Dashboard default is editable.** Without a
    `configuration` argument the portal uses whatever the default configuration
    in the Dashboard currently says, and anyone ticking "let customers switch
    plans" there silently bypasses the station-count guard in `change_plan` —
    a customer with 80 stations drops to a 50-station plan and we learn about
    it from a webhook, after the fact, with no way to refuse. Pinning the
    configuration in code makes the guard hold regardless of Dashboard state.

    Found again by its metadata marker rather than stored, for the same reason
    the tracking token is derived rather than stored: nothing to migrate and
    nothing to lose.
    """
    for cfg in s.billing_portal.Configuration.list(
            active=True, limit=100).auto_paging_iter():
        cfg = _plain(cfg)
        if (cfg.get("metadata") or {}).get("taktline") == _PORTAL_CONFIG_MARKER:
            return cfg["id"]
    created = s.billing_portal.Configuration.create(
        features={
            "payment_method_update": {"enabled": True},
            "invoice_history": {"enabled": True},
            # The billing address feeds automatic tax; a customer who moves
            # should be able to correct it without a support ticket.
            "customer_update": {"enabled": True,
                                "allowed_updates": ["email", "name", "address",
                                                    "phone"]},
            # Immediately, with the unused time returned — a cancellation that
            # keeps running to the period boundary reads as a subscription
            # that refused to die. The proration lands as a credit balance,
            # and the `customer.subscription.deleted` webhook refunds that
            # balance to the card — the same refund path every other credit
            # already takes.
            "subscription_cancel": {
                "enabled": True, "mode": "immediately",
                "proration_behavior": "create_prorations",
                "cancellation_reason": {
                    "enabled": True,
                    "options": ["too_expensive", "missing_features",
                                "switched_service", "unused", "too_complex",
                                "other"]},
            },
            # OFF, and stated rather than defaulted — this line is the whole
            # reason the configuration exists. Plan changes go through
            # `change_plan`, which can say "remove 30 stations first".
            "subscription_update": {"enabled": False},
        },
        metadata={"taktline": _PORTAL_CONFIG_MARKER},
    )
    return created["id"]


def portal_session(*, customer_id: str, return_url: str):
    """Stripe's own billing portal — payment method, invoices, cancellation.

    Plan switching is disabled via the pinned configuration above; plan
    changes go through `change_plan`.
    """
    s = _stripe()
    config_id = _portal_config_cache.get(s.api_key)
    if not config_id:
        config_id = _portal_configuration_id(s)
        _portal_config_cache[s.api_key] = config_id
    return s.billing_portal.Session.create(
        customer=customer_id, return_url=return_url, configuration=config_id)


# ─── Changing a live subscription ────────────────────────────────────────────

def update_station_quantity(subscription_id: str, quantity: int):
    """Report the current station count as the subscription's quantity.

    No proration — see the module docstring. The count at the period boundary
    is what the month costs, so drawing and redrawing a floor mid-cycle
    produces no invoice noise at all. Skips the API write when Stripe already
    has the number, since this is called on every station create/delete.
    """
    s = _stripe()
    current = _plain(s.Subscription.retrieve(subscription_id, expand=["items"]))
    price_id = station_price()
    for item in current["items"]["data"]:
        if item["price"]["id"] == price_id:
            if int(item.get("quantity", 0) or 0) == quantity:
                return current
            return _plain(s.Subscription.modify(
                subscription_id,
                items=[{"id": item["id"], "quantity": quantity}],
                proration_behavior="none",
            ))
    # No station item at all would mean the subscription predates this model;
    # add the line rather than silently reporting nothing.
    return _plain(s.Subscription.modify(
        subscription_id,
        items=[{"price": price_id, "quantity": quantity}],
        proration_behavior="none",
    ))


def set_on_premise(subscription_id: str, on_premise: bool):
    """Add or remove the on-premise add-on on a live subscription.

    Adding invoices now — the licence is granted now. Removing credits
    forward. `payment_behavior='allow_incomplete'` matters for ACH: an
    immediate invoice would otherwise fail while the transfer is still
    clearing, and the customer would be told their add-on was declined when
    it was merely slow.
    """
    s = _stripe()
    current = s.Subscription.retrieve(subscription_id, expand=["items"])
    price_id = onprem_price()
    existing = next((item for item in current["items"]["data"]
                     if item["price"]["id"] == price_id), None)
    if on_premise and existing is None:
        items = [{"price": price_id, "quantity": 1}]
        proration = "always_invoice"
    elif not on_premise and existing is not None:
        items = [{"id": existing["id"], "deleted": True}]
        proration = "create_prorations"
    else:
        return current                              # already as asked
    return s.Subscription.modify(
        subscription_id,
        items=items,
        proration_behavior=proration,
        payment_behavior="allow_incomplete",
        metadata={"onPremise": str(on_premise).lower()},
    )


def cancel(subscription_id: str, *, refund_credit_for: Optional[str] = None):
    """Cancel now, and give back any credit balance.

    A downgrade earlier in the life of the account leaves a negative customer
    balance that Stripe applies to future invoices. If there are no future
    invoices, that is simply money kept for service never delivered. When
    `refund_credit_for` (a customer id) is given, the balance is zeroed and
    refunded against their most recent charge.
    """
    s = _stripe()
    result = s.Subscription.cancel(subscription_id)
    if refund_credit_for:
        _refund_credit_balance(s, refund_credit_for)
    return result


def refund_credit_balance(customer_id: str) -> None:
    """Give back any credit balance without cancelling anything.

    The webhook path: a customer who cancels **in the portal** never passes
    through `cancel` above — the cancellation arrives as
    `customer.subscription.deleted`, and without this call their credit from an
    earlier downgrade would sit on the account forever, applied to future
    invoices that will never exist.
    """
    _refund_credit_balance(_stripe(), customer_id)


def _refund_credit_balance(s, customer_id: str) -> None:
    customer = _plain(s.Customer.retrieve(customer_id))
    balance = customer.get("balance", 0)
    if balance >= 0:                       # 0 or a debt they owe us
        return
    owed = -balance
    charges = s.Charge.list(customer=customer_id, limit=10)
    for charge in charges.auto_paging_iter():
        charge = _plain(charge)
        if charge.get("refunded") or not charge.get("paid"):
            continue
        amount = min(owed, charge["amount"] - charge.get("amount_refunded", 0))
        if amount <= 0:
            continue
        s.Refund.create(charge=charge["id"], amount=amount)
        owed -= amount
        if owed <= 0:
            break
    # Zero the balance whatever we managed to return, so it cannot be spent
    # twice — once as a refund and once against a future invoice.
    s.Customer.create_balance_transaction(
        customer_id, amount=-balance, currency="usd",
        description="Credit refunded on cancellation",
    )


# ─── Webhooks ────────────────────────────────────────────────────────────────

#: The events we act on. Anything else is acknowledged and ignored — Stripe
#: disables endpoints that keep erroring, so an unknown event must not 500.
HANDLED = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
    "invoice.payment_action_required",
    "charge.dispute.created",
}


def verify(payload: bytes, signature: str):
    """Parse a webhook, verifying Stripe's signature over the RAW body.

    The body must not be re-serialised before this: the signature covers the
    exact bytes Stripe sent, and a round trip through a Pydantic model changes
    key order and whitespace, so verification fails for reasons nobody can see.
    """
    s = _stripe()
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, "STRIPE_WEBHOOK_SECRET is not set")
    try:
        s.Webhook.construct_event(payload, signature,
                                  settings.stripe_webhook_secret)
    except Exception as exc:                       # signature or parse failure
        raise HTTPException(400, f"Invalid webhook signature: {exc}") from None
    # construct_event's return type changed shape across stripe versions; the
    # verified raw payload is the same data and is plain dicts on every one.
    return json.loads(payload)


def fetch_subscription(subscription_id: str):
    """The authoritative object. Never trust the copy inside the event."""
    return _plain(_stripe().Subscription.retrieve(subscription_id))


def shape_of_subscription(obj) -> tuple[Optional[int], bool]:
    """Read (stations, onPremise) off a Stripe subscription.

    Prefers the price ids on the live line items over the metadata, because
    metadata is what *we* last wrote and the items are what Stripe will
    actually bill. When they disagree, the items are the truth. `stations` is
    None when no station line was found at all — a shape this code never
    creates, reported as unknown rather than invented as zero.
    """
    ids = plans.price_ids()
    by_price = {v: k for k, v in ids.items() if v}
    stations, on_premise = None, False
    for item in obj.get("items", {}).get("data", []):
        code = by_price.get(item.get("price", {}).get("id"))
        if code == "onprem":
            on_premise = True
        elif code == "taktline":
            stations = int(item.get("quantity", 1) or 1)
    if stations is None:
        on_premise = on_premise or (
            (obj.get("metadata") or {}).get("onPremise") == "true")
    return stations, on_premise
