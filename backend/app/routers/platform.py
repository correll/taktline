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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.traffic import traffic
from ..core.usage import month_bucket
from ..db.connection import get_session, require_uuid
from ..db.tables import (
    AuthSession, Card, CardEvent, Company, Membership, PlatformAudit,
    Station, SupportGrant, UsageCounter, User, WorkSession,
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
                          session: AsyncSession = Depends(get_session)):
    async def count(stmt) -> int:
        return (await session.execute(stmt)).scalar_one()

    now = utcnow()
    users_total = await count(select(func.count()).select_from(User))
    companies_total = await count(select(func.count()).select_from(Company))
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
    }


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_platform_users(user: User = Depends(require_platform_staff),
                              session: AsyncSession = Depends(get_session)):
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
                            session: AsyncSession = Depends(get_session)):
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
                               session: AsyncSession = Depends(get_session)):
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
                                  session: AsyncSession = Depends(get_session)):
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
    } for c in companies]


class DeleteCompanyBody(BaseModel):
    confirmName: str


@router.delete("/companies/{company_id}", status_code=204)
async def delete_platform_company(company_id: str, body: DeleteCompanyBody,
                                  actor: User = Depends(require_platform_staff),
                                  session: AsyncSession = Depends(get_session)):
    company = await session.get(Company, require_uuid(company_id, "Company not found"))
    if company is None:
        raise HTTPException(404, "Company not found")
    if body.confirmName.strip() != company.name:
        raise HTTPException(400, "Type the company's exact name to confirm deletion")
    member_count = (await session.execute(
        select(func.count()).select_from(Membership).where(Membership.companyId == company.id)
    )).scalar_one()
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
                              session: AsyncSession = Depends(get_session)):
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
                            session: AsyncSession = Depends(get_session)):
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
                     session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(PlatformAudit).order_by(PlatformAudit.createdAt.desc()).limit(min(limit, 500))
    )).scalars().all()
    return [{
        "id": str(r.id), "actorEmail": r.actorEmail, "action": r.action,
        "targetType": r.targetType, "targetId": r.targetId,
        "detail": r.detail, "createdAt": r.createdAt,
    } for r in rows]
