"""Billing: what plan am I on, what can I move to, and how do I pay.

Every authenticated endpoint here is built on `get_current_user` +
`load_membership` rather than `get_active_company`, which is what keeps them
reachable from a **locked** account. That is not incidental: a paywall whose
payment page is behind the paywall is a lock with the key inside.

`test_entitlements.py` asserts this deliberately, via the `UNGATED` list — so
the exemption is written down rather than being a property of which dependency
happened to be imported.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import billing_stripe, entitlements, plans
from ..core.config import settings
from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import (BillingEvent, Company, Station as StationRow, Subscription,
                         User)
from ..deps.auth import get_current_user, load_membership
from ..models.common import utcnow

router = APIRouter(prefix="/billing", tags=["billing"])


# ─── Shapes ──────────────────────────────────────────────────────────────────

class PricingOut(BaseModel):
    """The whole price list — one metered plan, so this is arithmetic, not a
    table of tiers. The client renders from these numbers rather than from
    prose, and the same numbers build the Stripe price (`plans.station_tiers`)."""
    freeStations: int
    perStationCents: int
    minimumCents: int
    capCents: int
    #: Where the floor stops and the cap starts biting, for display.
    minStations: int
    capStations: int
    onpremCents: int


class UsageOut(BaseModel):
    stations: int
    stationLimit: Optional[int]


class SubscriptionOut(BaseModel):
    plan: str
    planLabel: str
    state: str
    reason: Optional[str] = None
    onPremise: bool
    stationLimit: Optional[int] = None
    integrations: bool
    #: What this account costs at its current station count — the number the
    #: billing tab shows next to "N stations × $2".
    monthlyCents: int
    currentPeriodEnd: Optional[str] = None
    graceEndsAt: Optional[str] = None
    settling: bool = False
    usage: UsageOut
    billingEnabled: bool
    #: True once there is a Stripe customer, i.e. the portal is worth showing.
    hasPaymentMethod: bool = False


class CheckoutIn(BaseModel):
    onPremise: bool = False


class OnPremiseIn(BaseModel):
    enabled: bool


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _owner(company_id: str, user: User, session: AsyncSession):
    """Billing is a super-admin action, resolved from the URL path so it never
    passes through the entitlement gate."""
    return await load_membership(session, user, company_id, min_role="super_admin")


async def _subscription(session: AsyncSession, company_uuid) -> Subscription:
    row = (await session.execute(
        select(Subscription).where(Subscription.companyId == company_uuid)
    )).scalars().first()
    if row is None:
        row = await entitlements.ensure_subscription(session, company_uuid)
    return row


def _iso(v):
    return v.isoformat() if v is not None else None


async def _station_count(session: AsyncSession, company_uuid) -> int:
    return (await session.execute(
        select(func.count()).select_from(StationRow)
        .where(StationRow.companyId == company_uuid)
    )).scalar_one()


# ─── Read ────────────────────────────────────────────────────────────────────

@router.get("/plans", response_model=PricingOut)
async def pricing():
    """The price list. Public to any signed-in user — it is on the website too."""
    return PricingOut(
        freeStations=plans.FREE_STATIONS,
        perStationCents=plans.PER_STATION_CENTS,
        minimumCents=plans.MIN_CENTS, capCents=plans.CAP_CENTS,
        minStations=plans.MIN_STATIONS, capStations=plans.CAP_STATIONS,
        onpremCents=plans.ONPREM_CENTS,
    )


@router.get("/{company_id}/subscription", response_model=SubscriptionOut)
async def get_subscription(company_id: str, user: User = Depends(get_current_user),
                           session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Plan, state and usage — everything the billing tab and the ceiling nag
    need, in one call. Readable by any member: an operator seeing "43 of 50
    stations" is how a ceiling gets noticed before it is hit."""
    await load_membership(session, user, company_id)
    company_uuid = require_uuid(company_id, "Company not found")
    row = await _subscription(session, company_uuid)
    ent = await entitlements.resolve(session, company_uuid, user=user)
    used = await _station_count(session, company_uuid)

    # What this account costs: the metered clamp at its current count, plus
    # the add-on. Free (and sandbox, self-hosted, comped) accounts cost 0.
    monthly = 0
    if ent.plan.code == plans.PAID and row.stripeSubscriptionId:
        monthly = plans.monthly_cents_for(used)
        if ent.on_premise:
            monthly += plans.ONPREM_CENTS

    return SubscriptionOut(
        plan=ent.plan.code, planLabel=ent.plan.label, state=ent.state,
        reason=ent.reason, onPremise=ent.on_premise,
        stationLimit=ent.station_limit, integrations=ent.integrations,
        monthlyCents=monthly,
        currentPeriodEnd=_iso(row.currentPeriodEnd),
        graceEndsAt=_iso(row.graceEndsAt), settling=ent.settling,
        usage=UsageOut(stations=used, stationLimit=ent.station_limit),
        billingEnabled=settings.billing_enabled,
        hasPaymentMethod=bool(row.stripeCustomerId),
    )


# ─── Buying and changing ─────────────────────────────────────────────────────
#
# There is nothing to choose. The paid plan is the station count the company
# already has, at $2 each within the floor and the cap — so checkout carries a
# quantity, not a plan code, and there is no downgrade to refuse: a shop that
# removes stations simply pays less next period.

@router.post("/{company_id}/checkout")
async def start_checkout(company_id: str, body: CheckoutIn, request: Request,
                         user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """A hosted Stripe checkout for this line. Returns a URL to send them to."""
    await _owner(company_id, user, session)
    company_uuid = require_uuid(company_id, "Company not found")

    row = await _subscription(session, company_uuid)
    # A live subscription — even one whose payment is failing — is managed in
    # the portal. A second checkout here would mint a second subscription; the
    # recovery path for past_due is a new card, not a new purchase.
    if row.stripeSubscriptionId and row.stripeStatus in ("active", "incomplete",
                                                         "past_due"):
        raise HTTPException(409, "Already subscribed — manage it in the portal")
    stations = await _station_count(session, company_uuid)
    company = await session.get(Company, company_uuid)
    customer = billing_stripe.ensure_customer(row, company.name if company else "", user.email)
    await session.flush()

    base = settings.frontend_base_url.rstrip("/")
    sess = billing_stripe.checkout_session(
        customer_id=customer, stations=stations, on_premise=body.onPremise,
        company_id=str(company_uuid),
        success_url=f"{base}/settings?tab=billing&checkout=done",
        cancel_url=f"{base}/settings?tab=billing&checkout=cancelled",
    )
    return {"url": sess.url}


@router.post("/{company_id}/portal")
async def open_portal(company_id: str, user: User = Depends(get_current_user),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Stripe's portal: payment method, invoices, cancellation."""
    await _owner(company_id, user, session)
    company_uuid = require_uuid(company_id, "Company not found")
    row = await _subscription(session, company_uuid)
    if not row.stripeCustomerId:
        raise HTTPException(409, "No billing account yet — choose a plan first")
    base = settings.frontend_base_url.rstrip("/")
    sess = billing_stripe.portal_session(
        customer_id=row.stripeCustomerId, return_url=f"{base}/settings?tab=billing")
    return {"url": sess.url}


@router.post("/{company_id}/on-premise", response_model=SubscriptionOut)
async def toggle_on_premise(company_id: str, body: OnPremiseIn,
                            user: User = Depends(get_current_user),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Add or drop the on-premise add-on — the one plan change that exists.

    Adding is invoiced now (the licence is granted now); removing credits
    forward. Station count is not touched here: it follows the floor
    automatically (`entitlements.report_station_count`).
    """
    await _owner(company_id, user, session)
    company_uuid = require_uuid(company_id, "Company not found")

    row = await _subscription(session, company_uuid)
    if not row.stripeSubscriptionId:
        raise HTTPException(409, "No active subscription — start a checkout instead")

    obj = billing_stripe.set_on_premise(row.stripeSubscriptionId, body.enabled)
    _apply_subscription(row, obj)
    await session.flush()
    return await get_subscription(company_id, user, session)


# ─── Webhook ─────────────────────────────────────────────────────────────────

def _apply_subscription(row: Subscription, obj) -> None:
    """Write a Stripe subscription object onto our row.

    Only ever called with an object fetched *now* from Stripe, never with the
    copy embedded in a webhook — Stripe does not guarantee delivery order, so
    an older event arriving late would otherwise overwrite a newer state.
    """
    from datetime import datetime, timezone

    _stations, on_premise = billing_stripe.shape_of_subscription(obj)
    # A live Stripe subscription IS the paid plan; there is nothing else it
    # could be. The station quantity is not copied anywhere — the stations
    # table is the truth and Stripe's quantity is the report of it.
    row.planCode = plans.PAID
    row.onPremise = on_premise
    row.stripeSubscriptionId = obj["id"]
    row.stripeStatus = obj["status"]
    period_end = obj.get("current_period_end")
    if period_end:
        row.currentPeriodEnd = datetime.fromtimestamp(period_end, tz=timezone.utc)
    if obj["status"] in ("active", "trialing"):
        row.graceEndsAt = None          # whatever went wrong is over
    row.updatedAt = utcnow()


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request,
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Stripe's callback. Unauthenticated by design, verified by signature.

    Deliberately never rate-limited: Stripe retries a failing endpoint for
    three days and then disables it, so a 429 during a traffic spike is how you
    lose the endpoint entirely.

    Idempotent on Stripe's own event id — a redelivery inserts nothing and does
    nothing. `billing_events` carries no foreign key on purpose, so deleting a
    company cannot destroy the record that its events were handled.
    """
    payload = await request.body()
    event = billing_stripe.verify(payload, request.headers.get("stripe-signature", ""))

    # Claim the event. ON CONFLICT DO NOTHING is the idempotency: a second
    # delivery of the same id finds the row already there and returns.
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    claimed = (await session.execute(
        pg_insert(BillingEvent)
        .values(stripeEventId=event["id"], type=event["type"], payload={})
        .on_conflict_do_nothing(index_elements=["stripeEventId"])
        .returning(BillingEvent.id)
    )).scalar()
    if claimed is None:
        # The claim only sticks once processing succeeded. A delivery that
        # errored may be retried — otherwise a crash marks the event handled
        # forever, and even a dashboard "Resend" after the fix does nothing.
        claimed = (await session.execute(
            BillingEvent.__table__.update()
            .where(BillingEvent.stripeEventId == event["id"],
                   BillingEvent.processedAt.is_(None),
                   BillingEvent.error.isnot(None))
            .values(error=None)
            .returning(BillingEvent.id)
        )).scalar()
    if claimed is None:
        return {"received": True, "duplicate": True}

    if event["type"] not in billing_stripe.HANDLED:
        return {"received": True, "ignored": event["type"]}

    try:
        await _handle(session, event)
    except HTTPException:
        raise
    except Exception as exc:                       # noqa: BLE001
        # Record and acknowledge. Returning 500 makes Stripe retry, and a
        # deterministic bug would then retry for three days and disable the
        # endpoint for every other customer's events too.
        await session.execute(
            BillingEvent.__table__.update()
            .where(BillingEvent.id == claimed)
            .values(error=str(exc)[:500])
        )
        return {"received": True, "error": True}

    await session.execute(
        BillingEvent.__table__.update()
        .where(BillingEvent.id == claimed)
        .values(processedAt=utcnow())
    )
    return {"received": True}


async def _company_for(session: AsyncSession, *, customer_id=None,
                       subscription_id=None) -> Optional[Subscription]:
    if subscription_id:
        row = (await session.execute(select(Subscription).where(
            Subscription.stripeSubscriptionId == subscription_id))).scalars().first()
        if row is not None:
            return row
    if customer_id:
        return (await session.execute(select(Subscription).where(
            Subscription.stripeCustomerId == customer_id))).scalars().first()
    return None


async def _handle(session: AsyncSession, event) -> None:
    obj = event["data"]["object"]
    kind = event["type"]

    if kind == "charge.dispute.created":
        row = await _company_for(session, customer_id=obj.get("customer"))
        if row is not None:
            # A dispute is not a failed payment: the money was taken and is now
            # being clawed back. Treat it as one for entitlement purposes so the
            # account does not keep running for free while it is resolved.
            row.graceEndsAt = entitlements.grace_deadline()
            row.stripeStatus = "past_due"
        return

    if kind.startswith("invoice."):
        row = await _company_for(session, customer_id=obj.get("customer"),
                                 subscription_id=obj.get("subscription"))
        if row is None:
            return
        if kind == "invoice.paid":
            row.graceEndsAt = None
        else:
            # payment_failed / payment_action_required. Stripe is already
            # retrying and sending its own dunning email; we start the clock.
            if row.graceEndsAt is None:
                row.graceEndsAt = entitlements.grace_deadline()
        if obj.get("subscription"):
            _apply_subscription(row, billing_stripe.fetch_subscription(obj["subscription"]))
        row.updatedAt = utcnow()
        return

    # checkout.session.completed and every customer.subscription.* event.
    subscription_id = (obj.get("subscription") if kind.startswith("checkout.")
                       else obj.get("id"))
    if not subscription_id:
        return

    row = await _company_for(session, customer_id=obj.get("customer"),
                             subscription_id=subscription_id)
    if row is None:
        # First purchase: the row is found by customer id, or failing that by
        # the companyId we put in the subscription's metadata at checkout.
        meta = (obj.get("metadata") or {})
        company_id = meta.get("companyId")
        if company_id:
            row = (await session.execute(select(Subscription).where(
                Subscription.companyId == require_uuid(company_id, "unknown company")
            ))).scalars().first()
    if row is None:
        return

    if kind == "customer.subscription.deleted":
        # Cancelled. They keep the data. A line that still fits the free tier
        # simply becomes free — a three-station shop that stops paying is
        # exactly who the free tier is for. A bigger line keeps its grace
        # window and then pauses; nothing is deleted either way.
        stations = (await session.execute(
            select(func.count()).select_from(StationRow)
            .where(StationRow.companyId == row.companyId))).scalar_one()
        if stations <= plans.FREE_STATIONS:
            row.planCode = plans.FREE
            row.graceEndsAt = None
        else:
            row.graceEndsAt = entitlements.grace_deadline()
        row.stripeStatus = "canceled"
        row.stripeSubscriptionId = None
        row.updatedAt = utcnow()
        # An earlier credit (an on-premise removal, a Stripe-side adjustment)
        # would only ever apply to future invoices — of which there are now
        # none. Give it back. (A cancellation through our own code path —
        # company deletion — refunds inside `billing_stripe.cancel`; a portal
        # cancellation arrives here instead. The refund is idempotent: a zero
        # balance returns without doing anything.) Row fields are set first so
        # a Stripe failure here — recorded on the billing event by the
        # endpoint — still leaves the cancellation applied.
        if row.stripeCustomerId:
            billing_stripe.refund_credit_balance(row.stripeCustomerId)
        return

    _apply_subscription(row, billing_stripe.fetch_subscription(subscription_id))


# ─── On-premise licence ──────────────────────────────────────────────────────

class LicenceIn(BaseModel):
    #: The whole signed document, exactly as issued.
    licence: dict
    signature: str


@router.get("/licence")
async def read_licence(user: User = Depends(get_current_user)):
    """What licence this box is running under. Any signed-in user, because the
    answer an operator needs when the board goes read-only is on this page."""
    from ..core import licence as licence_mod

    if settings.is_cloud:
        return {"onPremise": False, "licence": None}
    lic = licence_mod.load()
    return {"onPremise": True,
            "licence": lic.as_dict() if lic else None,
            "graceDays": licence_mod.GRACE_DAYS}


@router.post("/licence")
async def install_licence(body: LicenceIn, user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Install a licence file by hand.

    Exists so an air-gapped shop is never dependent on our reachability — the
    file arrives by email and is pasted in. Any signed-in user may install one:
    it is signed, so the worst a hostile one can do is fail verification, and
    requiring an admin would mean a locked-out plant needs the right person
    awake to come back.
    """
    from ..core import licence as licence_mod

    if settings.is_cloud:
        raise HTTPException(400, "This is a hosted deployment; billing is by "
                                 "subscription, not by licence file")
    try:
        lic = licence_mod.install({"licence": body.licence, "signature": body.signature})
    except licence_mod.LicenceError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"licence": lic.as_dict()}


