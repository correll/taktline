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

class PlanOut(BaseModel):
    code: str
    label: str
    stations: Optional[int]
    integrations: bool
    monthlyCents: int
    blurb: str
    purchasable: bool


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
    monthlyCents: int
    trialEndsAt: Optional[str] = None
    currentPeriodEnd: Optional[str] = None
    graceEndsAt: Optional[str] = None
    settling: bool = False
    usage: UsageOut
    billingEnabled: bool
    #: True once there is a Stripe customer, i.e. the portal is worth showing.
    hasPaymentMethod: bool = False


class CheckoutIn(BaseModel):
    planCode: str
    onPremise: bool = False


class ChangePlanIn(BaseModel):
    planCode: str
    onPremise: bool = False


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

@router.get("/plans", response_model=list[PlanOut])
async def list_plans():
    """The price list. Public to any signed-in user — it is on the website too."""
    out = []
    for code, plan in plans.PLANS.items():
        if code in (plans.SANDBOX, plans.SELF_HOSTED):
            continue
        out.append(PlanOut(
            code=plan.code, label=plan.label, stations=plan.stations,
            integrations=plan.integrations, monthlyCents=plan.monthly_cents,
            blurb=plan.blurb, purchasable=code in plans.PURCHASABLE,
        ))
    return out


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

    return SubscriptionOut(
        plan=ent.plan.code, planLabel=ent.plan.label, state=ent.state,
        reason=ent.reason, onPremise=ent.on_premise,
        stationLimit=ent.station_limit, integrations=ent.integrations,
        monthlyCents=plans.monthly_cents(ent.plan.code, ent.on_premise),
        trialEndsAt=_iso(row.trialEndsAt), currentPeriodEnd=_iso(row.currentPeriodEnd),
        graceEndsAt=_iso(row.graceEndsAt), settling=ent.settling,
        usage=UsageOut(stations=used, stationLimit=ent.station_limit),
        billingEnabled=settings.billing_enabled,
        hasPaymentMethod=bool(row.stripeCustomerId),
    )


# ─── Buying and changing ─────────────────────────────────────────────────────

async def _refuse_if_plan_is_too_small(session: AsyncSession, company_uuid,
                                       plan_code: str) -> None:
    """A downgrade that does not fit is refused, not silently applied.

    The alternative — accept it and disable whatever is over the line — has no
    honest UI. Twenty stations would have to either vanish or stay visible and
    not work, and this codebase already has a rule about that: an affordance
    that cannot work is worse than none.
    """
    plan = plans.get(plan_code)
    if plan.stations is None:
        return
    used = await _station_count(session, company_uuid)
    if used <= plan.stations:
        return
    raise HTTPException(409, {
        "message": (f"You have {used} stations and {plan.label} covers "
                    f"{plan.stations}. Remove {used - plan.stations} before "
                    f"switching."),
        "code": "over_limit_for_plan",
        "plan": plan_code, "limit": plan.stations, "used": used,
    })


def _validate_purchasable(plan_code: str) -> None:
    if plan_code not in plans.PURCHASABLE:
        raise HTTPException(400, f"'{plan_code}' is not a plan you can buy")


@router.post("/{company_id}/checkout")
async def start_checkout(company_id: str, body: CheckoutIn, request: Request,
                         user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """A hosted Stripe checkout for the chosen plan. Returns a URL to send them to."""
    await _owner(company_id, user, session)
    company_uuid = require_uuid(company_id, "Company not found")
    _validate_purchasable(body.planCode)
    await _refuse_if_plan_is_too_small(session, company_uuid, body.planCode)

    row = await _subscription(session, company_uuid)
    company = await session.get(Company, company_uuid)
    customer = billing_stripe.ensure_customer(row, company.name if company else "", user.email)
    await session.flush()

    base = settings.frontend_base_url.rstrip("/")
    sess = billing_stripe.checkout_session(
        customer_id=customer, plan_code=body.planCode, on_premise=body.onPremise,
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


@router.post("/{company_id}/change-plan", response_model=SubscriptionOut)
async def change_plan(company_id: str, body: ChangePlanIn,
                      user: User = Depends(get_current_user),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Move between plans, prorated to the day.

    An upgrade is invoiced immediately and a downgrade credits forward — see
    `core/billing_stripe` for why one setting for both is wrong in each
    direction.
    """
    await _owner(company_id, user, session)
    company_uuid = require_uuid(company_id, "Company not found")
    _validate_purchasable(body.planCode)
    await _refuse_if_plan_is_too_small(session, company_uuid, body.planCode)

    row = await _subscription(session, company_uuid)
    if not row.stripeSubscriptionId:
        raise HTTPException(409, "No active subscription — start a checkout instead")

    upgrading = (plans.monthly_cents(body.planCode, body.onPremise)
                 > plans.monthly_cents(row.planCode, row.onPremise))
    obj = billing_stripe.change_plan(
        subscription_id=row.stripeSubscriptionId, plan_code=body.planCode,
        on_premise=body.onPremise, upgrading=upgrading)

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

    plan_code, on_premise = billing_stripe.plan_from_subscription(obj)
    row.planCode = plan_code
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
        # Cancelled. They keep the data; the plan lapses at period end, which
        # `entitlements` derives from the row rather than from a job running.
        row.stripeStatus = "canceled"
        row.graceEndsAt = entitlements.grace_deadline()
        row.updatedAt = utcnow()
        return

    _apply_subscription(row, billing_stripe.fetch_subscription(subscription_id))


# ─── Trial opt-out ───────────────────────────────────────────────────────────
#
# The link in every trial email. **GET only describes; POST deletes.** A
# one-click destructive GET is deleted by the first mail scanner that prefetches
# links — corporate mail filters do this routinely — and the customer never
# even sees the message.

class TrialStopOut(BaseModel):
    companyName: str
    valid: bool
    stations: int
    lots: int


@router.get("/trial/stop", response_model=TrialStopOut)
async def describe_trial_stop(company: str, token: str,
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """What the opt-out link is about to destroy. Unauthenticated: the token in
    the email is the authorisation, and all it can do is show this page."""
    from sqlalchemy import func

    from ..core import lifecycle
    from ..db.tables import Card as CardRow

    company_uuid = require_uuid(company, "Not found")
    if not lifecycle.verify_token(str(company_uuid), token):
        raise HTTPException(404, "Not found")
    row = await session.get(Company, company_uuid)
    if row is None:
        raise HTTPException(404, "Not found")
    stations = await _station_count(session, company_uuid)
    lots = (await session.execute(
        select(func.count()).select_from(CardRow)
        .where(CardRow.companyId == company_uuid))).scalar_one()
    return TrialStopOut(companyName=row.name, valid=True, stations=stations, lots=lots)


@router.post("/trial/stop", status_code=204)
async def stop_trial(company: str, token: str,
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Delete the trial account, now, at the customer's request.

    Refuses once the company is paying — an opt-out link from a trial email
    must not be a way to destroy an account somebody has since bought.
    """
    from ..core import lifecycle

    company_uuid = require_uuid(company, "Not found")
    if not lifecycle.verify_token(str(company_uuid), token):
        raise HTTPException(404, "Not found")
    row = await session.get(Company, company_uuid)
    if row is None:
        return
    sub = await _subscription(session, company_uuid)
    if sub.planCode not in (plans.TRIAL,):
        raise HTTPException(409, "This account is on a paid plan — cancel it in "
                                 "Settings → Billing instead")
    await entitlements.release_company(session, company_uuid)
    await session.delete(row)
