"""Customer-service ("platform staff") endpoints.

Two tiers, both session-only (API keys can never reach these):

- owner   — from the PLATFORM_OWNER_EMAILS env allowlist (no API can add one);
            everything support can do, plus granting/revoking 'support'.
- support — users.platformRole == 'support'.

Ground rules baked in here:
- Non-staff get 404 on every route: the surface does not advertise itself.
- Impersonation is an explicit, time-boxed SupportGrant — visible in the UI
  banner/company switcher — never a silent membership bypass.
- Every consequential action writes a PlatformAudit row that survives the
  deletion of both actor and target.
"""

from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.traffic import traffic
from ..core.usage import month_bucket
from ..core import entitlements, plans
from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import (
    AuthSession, Card, CardEvent, ClientError as ClientErrorRow, Company, Membership,
    PlatformAudit, Station, Subscription, SupportGrant, UsageCounter, User, WorkSession,
)
from ..deps.auth import platform_role_of, require_platform_owner, require_platform_staff
from ..models.common import utcnow

router = APIRouter(prefix="/platform", tags=["platform"])

MAX_GRANT_MINUTES = 8 * 60


def _audit(session, actor: User, action: str, target_type: Optional[str] = None,
           target_id: Optional[str] = None, **detail) -> None:
    session.add(PlatformAudit(
        actorUserId=str(actor.id), actorEmail=actor.email, action=action,
        targetType=target_type, targetId=target_id, detail=detail,
    ))


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def platform_status(user: User = Depends(require_platform_staff),
                          session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    async def count(stmt) -> int:
        return (await session.execute(stmt)).scalar_one()

    now = utcnow()
    users_total = await count(select(func.count()).select_from(User))
    companies_total = await count(select(func.count()).select_from(Company))

    # Revenue, derived the same way the gate derives entitlement, so the number
    # on the dashboard and the service the customer receives cannot disagree.
    # The metered price needs each company's station count — one grouped query.
    sub_rows = (await session.execute(select(Subscription))).scalars().all()
    station_counts = dict((await session.execute(
        select(Station.companyId, func.count()).group_by(Station.companyId)
    )).all())
    mrr_cents = paying = free_lines = comped = at_risk = 0
    for row in sub_rows:
        ent = entitlements._derive(str(row.companyId), row)
        on_paid_plan = (plans.get(row.planCode).code == plans.PAID
                        and ent.state == entitlements.OK)
        if on_paid_plan and row.stripeSubscriptionId:
            mrr_cents += plans.monthly_cents_for(
                station_counts.get(row.companyId, 0))
            if row.onPremise:
                mrr_cents += plans.ONPREM_CENTS
            paying += 1
        elif on_paid_plan:
            # A paid plan with no Stripe subscription: staff granted it, or the
            # billing migration grandfathered them. Real service, no revenue —
            # and worth its own number rather than being hidden inside MRR.
            comped += 1
        elif plans.get(row.planCode).code == plans.FREE:
            free_lines += 1
        if ent.state in (entitlements.READ_ONLY, entitlements.LOCKED):
            at_risk += 1
    stations_total = await count(select(func.count()).select_from(Station))
    cards_total = await count(select(func.count()).select_from(Card))
    # Signed-in users: unexpired sessions seen within the idle window.
    idle_floor = now - timedelta(seconds=settings.session_idle_ttl)
    sessions_active = await count(select(func.count()).select_from(AuthSession).where(
        AuthSession.expiresAt > now, AuthSession.lastSeenAt > idle_floor))
    work_open = await count(select(func.count()).select_from(WorkSession).where(
        WorkSession.endedAt.is_(None)))
    events_24h = await count(select(func.count()).select_from(CardEvent).where(
        CardEvent.timestamp > now - timedelta(hours=24)))
    grants_active = await count(select(func.count()).select_from(SupportGrant).where(
        SupportGrant.endedAt.is_(None), SupportGrant.expiresAt > now))

    # Live WS connections — main.py owns the manager; import at call time
    # (main imports this router at module load).
    from ..main import ws_manager
    ws_connections = sum(len(v) for v in ws_manager._by_company.values())

    return {
        "uptimeSeconds": traffic.uptime_seconds(),
        "requestsTotal": traffic.total,
        "requestsPerMinute": traffic.per_minute(60),
        "wsConnections": ws_connections,
        "authSessionsActive": sessions_active,
        "workSessionsOpen": work_open,
        "cardEvents24h": events_24h,
        "supportGrantsActive": grants_active,
        "usersTotal": users_total,
        "companiesTotal": companies_total,
        "stationsTotal": stations_total,
        "cardsTotal": cards_total,
        "mrrCents": mrr_cents,
        "arrCents": mrr_cents * 12,
        "payingCompanies": paying,
        "compedCompanies": comped,
        "freeCompanies": free_lines,
        "atRiskCompanies": at_risk,
    }


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_platform_users(user: User = Depends(require_platform_staff),
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    users = (await session.execute(select(User).order_by(User.email))).scalars().all()
    memberships = (await session.execute(
        select(Membership, Company.name).join(Company, Company.id == Membership.companyId)
    )).all()
    last_seen = dict((await session.execute(
        select(AuthSession.userId, func.max(AuthSession.lastSeenAt)).group_by(AuthSession.userId)
    )).all())

    by_user: dict = {}
    for m, company_name in memberships:
        by_user.setdefault(m.userId, []).append(
            {"companyId": str(m.companyId), "companyName": company_name, "role": m.role})

    return [{
        "id": str(u.id),
        "email": u.email,
        "name": u.name,
        "emailVerified": u.emailVerified,
        "platformRole": platform_role_of(u),
        "createdAt": u.createdAt,
        "lastSeenAt": last_seen.get(u.id),
        "companies": by_user.get(u.id, []),
    } for u in users]


class PlatformRoleBody(BaseModel):
    role: Optional[str] = Field(None, pattern="^support$")


@router.put("/users/{user_id}/platform-role", status_code=204)
async def set_platform_role(user_id: str, body: PlatformRoleBody,
                            actor: User = Depends(require_platform_owner),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Owner-only: grant or revoke the customer-service tier."""
    target = await session.get(User, require_uuid(user_id, "User not found"))
    if target is None:
        raise HTTPException(404, "User not found")
    if platform_role_of(target) == "owner":
        raise HTTPException(400, "Owners are defined by PLATFORM_OWNER_EMAILS, not a role")
    target.platformRole = body.role
    target.updatedAt = utcnow()
    _audit(session, actor, "platform_role_set", "user", str(target.id),
           email=target.email, role=body.role)


@router.delete("/users/{user_id}", status_code=204)
async def delete_platform_user(user_id: str, actor: User = Depends(require_platform_staff),
                               session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Delete any account — including a company super_admin (this deliberately
    bypasses the tenant-side last-super-admin guard; that's the point of the
    support tier). Owners and yourself are off-limits."""
    target = await session.get(User, require_uuid(user_id, "User not found"))
    if target is None:
        raise HTTPException(404, "User not found")
    if target.id == actor.id:
        raise HTTPException(400, "You cannot delete your own account here")
    if platform_role_of(target) == "owner":
        raise HTTPException(400, "Platform owners cannot be deleted")
    roles = (await session.execute(
        select(Company.name, Membership.role)
        .join(Membership, Membership.companyId == Company.id)
        .where(Membership.userId == target.id)
    )).all()
    await session.delete(target)   # memberships/sessions/favorites cascade
    _audit(session, actor, "user_deleted", "user", user_id,
           email=target.email, memberships=[{"company": n, "role": r} for n, r in roles])


# ── Companies ─────────────────────────────────────────────────────────────────

@router.get("/companies")
async def list_platform_companies(user: User = Depends(require_platform_staff),
                                  session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    now = utcnow()
    companies = (await session.execute(select(Company).order_by(Company.name))).scalars().all()
    members = dict((await session.execute(
        select(Membership.companyId, func.count()).group_by(Membership.companyId))).all())
    stations = dict((await session.execute(
        select(Station.companyId, func.count()).group_by(Station.companyId))).all())
    cards = dict((await session.execute(
        select(Card.companyId, func.count()).group_by(Card.companyId))).all())
    last_event = dict((await session.execute(
        select(CardEvent.companyId, func.max(CardEvent.timestamp)).group_by(CardEvent.companyId))).all())

    # Active users per company: members with a signed-in session inside the
    # idle window (the same liveness definition the status tile uses).
    idle_floor = now - timedelta(seconds=settings.session_idle_ttl)
    active_users = dict((await session.execute(
        select(Membership.companyId, func.count(func.distinct(Membership.userId)))
        .join(AuthSession, AuthSession.userId == Membership.userId)
        .where(AuthSession.expiresAt > now, AuthSession.lastSeenAt > idle_floor)
        .group_by(Membership.companyId)
    )).all())

    # This calendar month's metered usage (API requests / WS messages).
    usage_rows = {r.companyId: r for r in (await session.execute(
        select(UsageCounter).where(UsageCounter.month == month_bucket())
    )).scalars().all()}

    # Live device connections (open sockets) per company.
    from ..main import ws_manager
    live = {cid: len(conns) for cid, conns in ws_manager._by_company.items()}

    # Billing. The effective state is derived rather than read from a column,
    # so this shows what the customer is actually experiencing right now — not
    # what a background job last wrote down.
    subs = {r.companyId: r for r in (await session.execute(
        select(Subscription))).scalars().all()}

    def _collected(row, ent) -> bool:
        return (ent.state == entitlements.OK
                and plans.get(row.planCode).code == plans.PAID
                and bool(row.stripeSubscriptionId))

    def _collected_cents(cid, row, ent) -> int:
        if not _collected(row, ent):
            return 0
        cents = plans.monthly_cents_for(stations.get(cid, 0))
        return cents + (plans.ONPREM_CENTS if row.onPremise else 0)

    def billing(cid):
        row = subs.get(cid)
        if row is None:
            return {"plan": None, "planState": None, "mrrCents": 0,
                    "renewsAt": None}
        ent = entitlements._derive(str(cid), row)
        return {
            "plan": ent.plan.code,
            "planState": ent.state,
            # Only money actually being collected. A free line, a locked
            # account and a **comped** one are all $0 of revenue — and comped
            # is the one that catches you out, because it wears the paid plan
            # code with no Stripe subscription behind it. Counting those once
            # put $1,972 of imaginary MRR on this dashboard.
            "mrrCents": _collected_cents(cid, row, ent),
            "renewsAt": row.currentPeriodEnd,
        }

    return [{
        "id": str(c.id),
        "name": c.name,
        "createdAt": c.createdAt,
        "members": members.get(c.id, 0),
        "activeUsers": active_users.get(c.id, 0),
        "stations": stations.get(c.id, 0),
        "cards": cards.get(c.id, 0),
        "devicesConnected": live.get(c.id, 0),
        "apiRequestsMonth": usage_rows[c.id].apiRequests if c.id in usage_rows else 0,
        "wsMessagesMonth": usage_rows[c.id].wsMessages if c.id in usage_rows else 0,
        "lastActivityAt": last_event.get(c.id),
        **billing(c.id),
    } for c in companies]


class DeleteCompanyBody(BaseModel):
    confirmName: str


@router.delete("/companies/{company_id}", status_code=204)
async def delete_platform_company(company_id: str, body: DeleteCompanyBody,
                                  actor: User = Depends(require_platform_staff),
                                  session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    company = await session.get(Company, require_uuid(company_id, "Company not found"))
    if company is None:
        raise HTTPException(404, "Company not found")
    if body.confirmName.strip() != company.name:
        raise HTTPException(400, "Type the company's exact name to confirm deletion")
    member_count = (await session.execute(
        select(func.count()).select_from(Membership).where(Membership.companyId == company.id)
    )).scalar_one()
    # Cancel at Stripe and remove the floor-plan files BEFORE the cascade takes
    # the rows that point at them. Afterwards there is nothing left to find the
    # live subscription with, and the customer keeps being billed.
    await entitlements.release_company(session, company.id)
    await session.delete(company)   # all domain rows cascade via companyId FKs
    _audit(session, actor, "company_deleted", "company", company_id,
           name=company.name, members=member_count)


# ── Impersonation ─────────────────────────────────────────────────────────────

class ImpersonateBody(BaseModel):
    companyId: str
    minutes: int = Field(60, ge=1, le=MAX_GRANT_MINUTES)


@router.post("/impersonate", status_code=201)
async def start_impersonation(body: ImpersonateBody,
                              actor: User = Depends(require_platform_staff),
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    company = await session.get(Company, require_uuid(body.companyId, "Company not found"))
    if company is None:
        raise HTTPException(404, "Company not found")
    grant = SupportGrant(
        userId=actor.id, companyId=company.id,
        expiresAt=utcnow() + timedelta(minutes=body.minutes),
    )
    session.add(grant)
    await session.flush()
    _audit(session, actor, "impersonation_started", "company", str(company.id),
           name=company.name, minutes=body.minutes, grantId=str(grant.id))
    return {"grantId": str(grant.id), "companyId": str(company.id),
            "companyName": company.name, "expiresAt": grant.expiresAt}


@router.delete("/impersonate/{company_id}", status_code=204)
async def end_impersonation(company_id: str, actor: User = Depends(require_platform_staff),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    grants = (await session.execute(
        select(SupportGrant).where(
            SupportGrant.userId == actor.id,
            SupportGrant.companyId == require_uuid(company_id, "Company not found"),
            SupportGrant.endedAt.is_(None),
        )
    )).scalars().all()
    for g in grants:
        g.endedAt = utcnow()
    if grants:
        _audit(session, actor, "impersonation_ended", "company", company_id)


# ── Audit trail ───────────────────────────────────────────────────────────────

@router.get("/audit")
async def list_audit(limit: int = 100, user: User = Depends(require_platform_staff),
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(PlatformAudit).order_by(PlatformAudit.createdAt.desc()).limit(min(limit, 500))
    )).scalars().all()
    return [{
        "id": str(r.id), "actorEmail": r.actorEmail, "action": r.action,
        "targetType": r.targetType, "targetId": r.targetId,
        "detail": r.detail, "createdAt": r.createdAt,
    } for r in rows]

@router.get("/client-errors/list")
async def list_client_errors(companyId: str | None = None, limit: int = 100,
                             _staff=Depends(require_platform_staff),
                             session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """The frontend error boundary's reports — what actually crashed on a
    customer's screen, answerable after the fact instead of lost to a reload.
    Newest first; filter by company to follow up a specific report."""
    stmt = select(ClientErrorRow).order_by(ClientErrorRow.createdAt.desc()).limit(min(limit, 500))
    cid = parse_uuid(companyId) if companyId else None
    if cid is not None:
        stmt = stmt.where(ClientErrorRow.companyId == cid)
    rows = (await session.execute(stmt)).scalars().all()
    return [{
        "id": str(r.id), "companyId": str(r.companyId) if r.companyId else None,
        "userEmail": r.userEmail, "message": r.message, "url": r.url,
        "componentStack": r.componentStack, "stack": r.stack,
        "userAgent": r.userAgent, "appVersion": r.appVersion,
        "createdAt": r.createdAt,
    } for r in rows]


@router.delete("/client-errors/{error_id}", status_code=204)
async def delete_client_error(error_id: str,
                              staff: User = Depends(require_platform_staff),
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Dismiss a crash report once it has been read, reported or fixed.

    These are diagnostics with a 30-day life, not an audit trail, so staff may
    clear them; the platform audit records who did. Idempotent — a row already
    gone is a 204, so a double-click is not an error."""
    row = await session.get(ClientErrorRow, require_uuid(error_id, "Report not found"))
    if row is not None:
        await session.delete(row)
        _audit(session, staff, "client_error.delete", target_type="client_error",
               target_id=error_id, message=(row.message or "")[:120])


@router.delete("/client-errors", status_code=200)
async def delete_client_errors(message: str | None = None,
                               staff: User = Depends(require_platform_staff),
                               session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Clear reports in bulk — all of them, or every copy of one message.

    The same crash from twenty browsers is twenty rows saying one thing, so
    dismissing them one at a time is busywork that leaves real reports buried."""
    stmt = delete(ClientErrorRow)
    if message:
        stmt = stmt.where(ClientErrorRow.message == message)
    result = await session.execute(stmt)
    removed = result.rowcount or 0
    _audit(session, staff, "client_error.delete_bulk",
           target_type="client_error", removed=removed, message=message)
    return {"removed": removed}
