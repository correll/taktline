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


def connector_price() -> str:
    price = plans.price_ids().get("connector")
    if not price:
        raise HTTPException(503, f"No Stripe price configured for extra "
                                 f"connectors — set {plans.CONNECTOR_PRICE_ENV}")
    return price


def line_items(plan_code: str, on_premise: bool,
               connector_addons: int = 0) -> list[dict]:
    items = [{"price": price_for(plan_code), "quantity": 1}]
    if on_premise:
        items.append({"price": onprem_price(), "quantity": 1})
    if connector_addons > 0:
        # A quantity, not N separate lines: Stripe prorates a quantity change
        # the same way it prorates a plan change, so going from two extra
        # connectors to one behaves like any other downgrade.
        items.append({"price": connector_price(), "quantity": connector_addons})
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
                     company_id: str, success_url: str, cancel_url: str,
                     connector_addons: int = 0):
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
        line_items=line_items(plan_code, on_premise, connector_addons),
        # Software subscriptions are taxed inconsistently by state; switching
        # this on retroactively after a year of sales is expensive and
        # unpleasant. See pricing.md.
        automatic_tax={"enabled": True},
        customer_update={"address": "auto", "name": "auto"},
        subscription_data={"metadata": {"companyId": company_id,
                                        "planCode": plan_code,
                                        "onPremise": str(on_premise).lower(),
                                        "connectorAddons": str(connector_addons)}},
        success_url=success_url,
        cancel_url=cancel_url,
    )


#: Bump when the feature set in `_portal_configuration_id` changes: a new
#: configuration is then created and used, rather than editing one that live
#: portal sessions may still be holding.
_PORTAL_CONFIG_MARKER = "taktline-portal-v1"

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
            # At period end, not immediately: they paid for the month, they
            # keep the month. The `customer.subscription.deleted` webhook then
            # starts the grace clock and refunds any credit balance.
            "subscription_cancel": {
                "enabled": True, "mode": "at_period_end",
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


# ─── Plan changes ────────────────────────────────────────────────────────────

def change_plan(*, subscription_id: str, plan_code: str, on_premise: bool,
                upgrading: bool, connector_addons: int = 0):
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
        items=deletions + line_items(plan_code, on_premise, connector_addons),
        proration_behavior="always_invoice" if upgrading else "create_prorations",
        payment_behavior="allow_incomplete",
        metadata={"planCode": plan_code, "onPremise": str(on_premise).lower(),
                  "connectorAddons": str(connector_addons)},
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


def plan_from_subscription(obj) -> tuple[str, bool, int]:
    """Read (planCode, onPremise, connectorAddons) off a Stripe subscription.

    Prefers the price ids on the live line items over the metadata, because
    metadata is what *we* last wrote and the items are what Stripe will
    actually bill. When they disagree, the items are the truth.
    """
    ids = plans.price_ids()
    by_price = {v: k for k, v in ids.items() if v}
    plan_code, on_premise, addons = None, False, 0
    for item in obj.get("items", {}).get("data", []):
        code = by_price.get(item.get("price", {}).get("id"))
        if code == "onprem":
            on_premise = True
        elif code == "connector":
            addons = int(item.get("quantity", 0) or 0)
        elif code:
            plan_code = code
    if plan_code is None:
        meta = obj.get("metadata") or {}
        plan_code = meta.get("planCode") or plans.TRIAL
        on_premise = on_premise or (meta.get("onPremise") == "true")
        addons = addons or int(meta.get("connectorAddons") or 0)
    return plan_code, on_premise, addons
