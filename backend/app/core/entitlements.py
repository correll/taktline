"""What a company is allowed to do right now.

Every gate in the app asks this module one question and gets one answer. The
answer is **derived** from the subscription row and the clock, never read from a
stored status column — because a stored status is only as current as the last
background job that ran, and the two ways that fails are both bad: a lapsed
company keeps full service silently, or a paying one is locked out by a job that
crashed at 3am.

Three states, and the boundaries between them are product decisions, not
technical ones:

``ok``          everything works.
``read_only``   they can see and export everything, but not change anything.
                This is where a failed payment lands for `GRACE_DAYS`. It exists
                because "your data is yours" has to stay true at exactly the
                moment it is least convenient for us.
``locked``      402 on everything except auth, company listing and billing. The
                data is kept, indefinitely. Nothing is deleted, ever, for
                non-payment — only an unconverted *trial* is deleted, and that
                is announced five times first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.common import utcnow
from . import plans
from .config import settings
from .plans import Plan

OK = "ok"
READ_ONLY = "read_only"
LOCKED = "locked"

# Stripe statuses that mean "we have their money, or will have it shortly".
# `incomplete` is in here for ACH: a bank debit sits in `processing` for 3–5
# business days after a successful checkout, and refusing service in the
# meantime would punish the customer for choosing the payment method we prefer.
_LIVE = {"active", "trialing", "incomplete"}
_SETTLING = {"incomplete"}


@dataclass(frozen=True)
class Entitlement:
    company_id: str
    plan: Plan
    on_premise: bool
    state: str
    #: Machine-readable cause, surfaced to the client so it can render a path
    #: forward rather than an apology. None when state is ok.
    reason: Optional[str]
    trial_ends_at: Optional[object] = None
    period_end: Optional[object] = None
    grace_ends_at: Optional[object] = None
    #: Money is moving but has not settled (ACH). Service is on; the UI says so.
    settling: bool = False

    @property
    def writable(self) -> bool:
        return self.state == OK

    @property
    def blocked(self) -> bool:
        return self.state == LOCKED

    @property
    def station_limit(self) -> Optional[int]:
        """None = uncapped."""
        return self.plan.stations

    @property
    def integrations(self) -> bool:
        return self.plan.integrations

    def as_dict(self) -> dict:
        return {
            "plan": self.plan.code,
            "planLabel": self.plan.label,
            "state": self.state,
            "reason": self.reason,
            "onPremise": self.on_premise,
            "stationLimit": self.plan.stations,
            "integrations": self.plan.integrations,
            "monthlyCents": plans.monthly_cents(self.plan.code, self.on_premise),
            "trialEndsAt": self.trial_ends_at,
            "currentPeriodEnd": self.period_end,
            "graceEndsAt": self.grace_ends_at,
            "settling": self.settling,
        }


def _unlimited(company_id: str, reason: str) -> Entitlement:
    """A company that is deliberately not metered.

    Used for on-premise deployments (entitlement comes from a licence file, not
    from us) and for self-hosted installs with no Stripe key configured. Both
    get a real Plan rather than a special case, so every downstream limit check
    reads the same shape — one whose station cap is None, meaning uncapped.
    """
    return Entitlement(
        company_id=company_id, plan=plans.PLANS[plans.SELF_HOSTED], on_premise=True,
        state=OK, reason=reason,
    )


async def resolve(session: AsyncSession, company_id, *, user=None) -> Entitlement:
    """The company's current entitlement. One indexed query."""
    from ..db.tables import Subscription

    cid = str(company_id)

    # The sandbox is checked FIRST, before any "we do not meter this
    # deployment" shortcut. Its quotas are not a billing limit — they are what
    # stops an unauthenticated public endpoint from being used as free storage,
    # and that reason holds just as well on a self-hosted box with no Stripe
    # key. Ordering this after the shortcuts silently uncapped the sandbox on
    # every deployment except taktline.com.
    if user is not None and getattr(user, "isSandbox", False):
        return Entitlement(company_id=cid, plan=plans.PLANS[plans.SANDBOX],
                           on_premise=False, state=OK, reason=None)

    # A customer's own box is governed by its licence file, not by a row in a
    # database they administer. Metering it here would be theatre: they can edit
    # the row. See the note in pricing.md.
    if not settings.is_cloud:
        return _unlimited(cid, "on_premise")

    # Self-hosted or dev with no payment provider configured: the gate must not
    # invent a paywall nobody can pay.
    if not settings.billing_enabled:
        return _unlimited(cid, "billing_disabled")

    row = (await session.execute(
        select(Subscription).where(Subscription.companyId == company_id)
    )).scalars().first()

    if row is None:
        # Should not happen — every company-creation path makes one. If it does,
        # a usable-but-visibly-temporary plan is the least harmful guess: it
        # neither bricks a paying customer nor hands out the top tier.
        return Entitlement(company_id=cid, plan=plans.get(plans.TRIAL),
                           on_premise=False, state=OK, reason="no_subscription")

    return _derive(cid, row)


def _derive(cid: str, row) -> Entitlement:
    now = utcnow()
    plan = plans.get(row.planCode)
    common = dict(
        company_id=cid, plan=plan, on_premise=row.onPremise,
        trial_ends_at=row.trialEndsAt, period_end=row.currentPeriodEnd,
        grace_ends_at=row.graceEndsAt,
    )

    if row.planCode in plans.FREE:
        # A trial has no grace period and no read-only tail: it ends, and then
        # the account is deleted on day 15. The five emails are the warning.
        if row.trialEndsAt is not None and now >= row.trialEndsAt:
            return Entitlement(**common, state=LOCKED, reason="trial_expired")
        return Entitlement(**common, state=OK, reason=None)

    # A paid plan with no Stripe subscription is a comped account — staff granted
    # it by hand. Honour it.
    if row.stripeStatus is None:
        return Entitlement(**common, state=OK, reason=None)

    if row.stripeStatus in _LIVE:
        return Entitlement(**common, state=OK, reason=None,
                           settling=row.stripeStatus in _SETTLING)

    # Payment failed. Stripe is retrying and sending its own reminders; we give
    # them the grace window read-only, then lock.
    if row.graceEndsAt is not None and now < row.graceEndsAt:
        return Entitlement(**common, state=READ_ONLY, reason="payment_failed")

    return Entitlement(**common, state=LOCKED, reason="payment_failed")


def grace_deadline():
    return utcnow() + timedelta(days=plans.GRACE_DAYS)


def trial_deadline():
    return utcnow() + timedelta(days=plans.TRIAL_DAYS)


# ─── Creating the row ────────────────────────────────────────────────────────

async def ensure_subscription(session: AsyncSession, company_id, *,
                              plan_code: str = plans.TRIAL):
    """Give a company a subscription row if it has none.

    Called from every path that creates a company — there are four, and missing
    one means a company that is silently ungated forever.

    It deliberately does **not** start the trial clock. Starting a trial is a
    grant against a person, not a property of a company, and it happens in
    exactly one place (`start_trial_if_unstarted`). When this function could
    also start one, there were two paths that set a deadline and only one that
    recorded the grant — so a second company got a second free fortnight.
    """
    from ..db.tables import Subscription

    existing = (await session.execute(
        select(Subscription).where(Subscription.companyId == company_id)
    )).scalars().first()
    if existing is not None:
        return existing

    row = Subscription(companyId=company_id, planCode=plan_code, trialEndsAt=None)
    session.add(row)
    await session.flush()
    return row


async def start_trial_if_unstarted(session: AsyncSession, user) -> None:
    """Start the 14-day clock on first verified login, for every company where
    this user is the sole super_admin and the trial has not begun.

    Also records the grant against the **email**, which is what stops a deleted
    trial from being restarted forever: `User` rows do not cascade with a
    company, so without this a verified user can create a new company on day 16
    and get another fortnight, indefinitely.
    """
    from ..db.tables import Membership, Subscription, TrialGrant

    if not settings.billing_enabled or getattr(user, "isSandbox", False):
        return

    rows = (await session.execute(
        select(Subscription)
        .join(Membership, Membership.companyId == Subscription.companyId)
        .where(Membership.userId == user.id,
               Membership.role == "super_admin",
               Subscription.planCode == plans.TRIAL,
               Subscription.trialEndsAt.is_(None))
    )).scalars().all()
    if not rows:
        return

    used = (await session.execute(
        select(TrialGrant).where(TrialGrant.email == user.email)
    )).scalars().first()

    for row in rows:
        if used is None:
            row.trialEndsAt = trial_deadline()
        else:
            # Second trial on the same email: it starts already over, so the
            # account is read-only-then-locked rather than silently free. They
            # keep everything they made and can buy a plan at any time.
            row.trialEndsAt = utcnow()

    if used is None:
        session.add(TrialGrant(email=user.email))
    await session.flush()


# ─── Quotas ──────────────────────────────────────────────────────────────────

#: Resource name → the plan attribute that caps it. Keyed on an explicit name
#: rather than `__tablename__` so a table rename cannot silently drop a limit.
_QUOTAS = {"stations": "stations"}

#: Everything the sandbox caps, which is more than the paid plans do — a
#: throwaway account is also a free-storage vector.
SANDBOX_LIMITS = {"stations": 40, "cards": 200, "lot_templates": 40, "processes": 10}


def limit_for(ent: Entitlement, resource: str) -> Optional[int]:
    if ent.plan.code == plans.SANDBOX:
        return SANDBOX_LIMITS.get(resource)
    attr = _QUOTAS.get(resource)
    return getattr(ent.plan, attr) if attr else None


async def count_of(session: AsyncSession, company_id, table) -> int:
    return (await session.execute(
        select(func.count()).select_from(table).where(table.companyId == company_id)
    )).scalar_one()


async def ensure_quota(session: AsyncSession, ctx, table, resource: str,
                       *, adding: int = 1, ent: Optional[Entitlement] = None) -> None:
    """Refuse a create that would take the company past its plan's limit."""
    if ent is None:
        ent = await resolve(session, ctx.company_id, user=getattr(ctx, "user", None))
    limit = limit_for(ent, resource)
    if limit is None:
        return
    count = await count_of(session, ctx.company_id, table)
    if count + adding > limit:
        pretty = resource.replace("_", " ")
        raise HTTPException(403, {
            "message": (f"Your {ent.plan.label} plan covers {limit} {pretty}. "
                        f"You have {count}." if adding == 1 else
                        f"Your {ent.plan.label} plan covers {limit} {pretty}. "
                        f"You have {count} and this would add {adding}."),
            "code": "plan_limit",
            "resource": resource,
            "plan": ent.plan.code,
            "limit": limit,
            "used": count,
        })


# ─── Which endpoints survive which state ─────────────────────────────────────
#
# Declared **on the endpoint**, not in a list somewhere else, for two reasons:
# whoever edits the endpoint can see the exemption, and `test_entitlements.py`
# can walk the route table and assert every non-GET route either passes the gate
# or carries a marker. An exemption that exists only because its author happened
# to pick a different dependency is not a design — it is an accident that
# survived review.

_READ_ONLY_OK = "_tk_works_read_only"
_LOCKED_OK = "_tk_works_when_locked"


def works_read_only(fn):
    """This write must keep working while the account is read-only.

    Reserved for writes that are not "using the product" — closing a work
    session that is already open, acknowledging an ERP delivery that has already
    happened. Blocking those does not apply pressure to pay; it corrupts data.
    """
    setattr(fn, _READ_ONLY_OK, True)
    return fn


def works_when_locked(fn):
    """This endpoint answers even for a locked account — the way out, or the
    way to get your data back."""
    setattr(fn, _LOCKED_OK, True)
    setattr(fn, _READ_ONLY_OK, True)
    return fn


def allows(endpoint, marker: str) -> bool:
    return bool(getattr(endpoint, marker, False))


def check_request(ent: Entitlement, request) -> None:
    """The gate. Raises 402 when this request is not allowed in this state."""
    if ent.state == OK:
        return

    endpoint = request.scope.get("endpoint")
    method = request.method.upper()

    if ent.state == LOCKED and not allows(endpoint, _LOCKED_OK):
        raise HTTPException(402, {
            "message": _locked_message(ent),
            "code": "subscription_required",
            "plan": ent.plan.code,
            "reason": ent.reason,
        })

    if ent.state == READ_ONLY:
        # DELETE stays open on purpose. The way off an over-limit plan is to
        # remove what does not fit — refusing deletes creates a deadlock where
        # the only escape from read-only is an action read-only forbids.
        if method in ("GET", "HEAD", "OPTIONS", "DELETE"):
            return
        if allows(endpoint, _READ_ONLY_OK):
            return
        raise HTTPException(402, {
            "message": ("This account is read-only until its payment goes through. "
                        "You can still see and export everything."),
            "code": "read_only",
            "plan": ent.plan.code,
            "reason": ent.reason,
            "graceEndsAt": str(ent.grace_ends_at) if ent.grace_ends_at else None,
        })


def _locked_message(ent: Entitlement) -> str:
    if ent.reason == "trial_expired":
        return ("Your trial has ended. Choose a plan to carry on — your line is "
                "exactly as you left it.")
    return ("This account is paused because a payment did not go through. "
            "Your data is safe; update your payment method to continue.")


def ensure_integrations(ent: Entitlement) -> None:
    """Refuse an ERP/shop binding on a plan that does not include them."""
    if ent.integrations:
        return
    raise HTTPException(403, {
        "message": (f"Integrations are part of Professional. "
                    f"Your plan is {ent.plan.label}."),
        "code": "plan_limit",
        "resource": "integrations",
        "plan": ent.plan.code,
    })
