"""The Stripe layer: checkout, the customer portal, plan changes, and webhooks.

Stripe collects; this module is the thin, testable seam between it and the
`subscriptions` table. Everything that decides *policy* lives in `plans.py` and
`entitlements.py` — what is here is the mechanics of talking to Stripe and the
handful of places where Stripe's behaviour is surprising enough to be worth
writing down.

Four of those, because each one is a way to lose money or a customer:

**1. Proration is not one setting.** `create_prorations` — the obvious choice,
and what most guides show — creates line items that are *not invoiced until the
next cycle*. Two days into a $116 month, switching to $29 produces a credit of
about $108 and a charge of about $27, netting to a $0 invoice and a ~$52 credit
balance. Not a $29 bill. And on an *upgrade* it hands over the better plan for
a whole month before any money moves. So upgrades use `always_invoice` (charge
the difference now) and downgrades use `create_prorations` (credit forward).

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


def price_for(plan_code: str) -> str:
    ids = plans.price_ids()
    price = ids.get(plan_code)
    if not price:
        raise HTTPException(
            503, f"No Stripe price configured for '{plan_code}' — set "
                 f"{plans.PLANS[plan_code].price_env}")
    return price


def onprem_price() -> str:
    price = plans.price_ids().get("onprem")
    if not price:
        raise HTTPException(503, f"No Stripe price configured for on-premise — "
                                 f"set {plans.ONPREM_PRICE_ENV}")
    return price


def line_items(plan_code: str, on_premise: bool) -> list[dict]:
    items = [{"price": price_for(plan_code), "quantity": 1}]
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

def checkout_session(*, customer_id: str, plan_code: str, on_premise: bool,
                     company_id: str, success_url: str, cancel_url: str):
    """A hosted checkout for a first purchase.

    Card **and** ACH. ACH is 0.8% capped at $5 against 2.9% + 30¢ for cards, so
    on anything above the entry tier it is worth several percent of revenue —
    and Stripe hosts the mandate flow, which is the part that is genuinely
    fiddly to build.
    """
    s = _stripe()
    return s.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=line_items(plan_code, on_premise),
        payment_method_types=["card", "us_bank_account"],
        # Software subscriptions are taxed inconsistently by state; switching
        # this on retroactively after a year of sales is expensive and
        # unpleasant. See pricing.md.
        automatic_tax={"enabled": True},
        customer_update={"address": "auto", "name": "auto"},
        subscription_data={"metadata": {"companyId": company_id,
                                        "planCode": plan_code,
                                        "onPremise": str(on_premise).lower()}},
        success_url=success_url,
        cancel_url=cancel_url,
    )


def portal_session(*, customer_id: str, return_url: str):
    """Stripe's own billing portal — payment method, invoices, cancellation.

    **Plan switching is deliberately not enabled here.** The portal talks
    straight to Stripe, so a customer with 80 stations could drop to a
    50-station plan in Stripe's UI and we would learn about it from a webhook,
    after the fact, with no way to refuse. Plan changes go through
    `change_plan` below, which can say "remove 30 stations first".
    """
    s = _stripe()
    return s.billing_portal.Session.create(customer=customer_id, return_url=return_url)


# ─── Plan changes ────────────────────────────────────────────────────────────

def change_plan(*, subscription_id: str, plan_code: str, on_premise: bool,
                upgrading: bool):
    """Move a live subscription to another plan, prorated to the day.

    See the module docstring for why `proration_behavior` differs by direction.
    `payment_behavior='allow_incomplete'` matters for ACH: an upgrade invoiced
    immediately would otherwise fail while the transfer is still clearing, and
    the customer would be told their upgrade was declined when it was merely
    slow.
    """
    s = _stripe()
    current = s.Subscription.retrieve(subscription_id, expand=["items"])
    # Replace every existing line rather than patching one: the on-premise
    # add-on may be arriving or leaving in the same change.
    deletions = [{"id": item.id, "deleted": True} for item in current["items"]["data"]]
    return s.Subscription.modify(
        subscription_id,
        items=deletions + line_items(plan_code, on_premise),
        proration_behavior="always_invoice" if upgrading else "create_prorations",
        payment_behavior="allow_incomplete",
        metadata={"planCode": plan_code, "onPremise": str(on_premise).lower()},
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


def _refund_credit_balance(s, customer_id: str) -> None:
    customer = s.Customer.retrieve(customer_id)
    balance = customer.get("balance", 0)
    if balance >= 0:                       # 0 or a debt they owe us
        return
    owed = -balance
    charges = s.Charge.list(customer=customer_id, limit=10)
    for charge in charges.auto_paging_iter():
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
        return s.Webhook.construct_event(payload, signature,
                                         settings.stripe_webhook_secret)
    except Exception as exc:                       # signature or parse failure
        raise HTTPException(400, f"Invalid webhook signature: {exc}") from None


def fetch_subscription(subscription_id: str):
    """The authoritative object. Never trust the copy inside the event."""
    return _stripe().Subscription.retrieve(subscription_id)


def plan_from_subscription(obj) -> tuple[str, bool]:
    """Read (planCode, onPremise) back off a Stripe subscription.

    Prefers the price ids on the live line items over the metadata, because
    metadata is what *we* last wrote and the items are what Stripe will
    actually bill. When they disagree, the items are the truth.
    """
    ids = plans.price_ids()
    by_price = {v: k for k, v in ids.items() if v}
    plan_code, on_premise = None, False
    for item in obj.get("items", {}).get("data", []):
        code = by_price.get(item.get("price", {}).get("id"))
        if code == "onprem":
            on_premise = True
        elif code:
            plan_code = code
    if plan_code is None:
        meta = obj.get("metadata") or {}
        plan_code = meta.get("planCode") or plans.TRIAL
        on_premise = on_premise or (meta.get("onPremise") == "true")
    return plan_code, on_premise
