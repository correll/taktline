"""Authentication and tenancy dependencies.

These compose with the existing per-request transactional `get_session`:

    get_current_user   → resolves the httpOnly session cookie to a User (401)
    get_active_company → validates X-Company-Id membership → CompanyContext (403)
    require_admin       → CompanyContext but 403 unless role ≥ 'admin'
    require_super_admin → CompanyContext but 403 unless role == 'super_admin'

Three roles, ordered by privilege (see ROLE_RANK):

    user        — operator: run work sessions, merge, advance a lot along a
                  route, set working/done status. Read-only on the lot board.
    admin       — everything a user can do, PLUS create lots, pull precursors,
                  and release/cancel production orders (a production planner).
    super_admin — everything: all config (stations/routes/processes/templates/
                  floor plan/settings/API keys), member management, and the
                  structural lot ops (unconstrained move, unmerge, delete).

Also holds the session-cookie helpers and session-row factory shared by the
auth router, dev bootstrap, and invite accept-signup.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import usage
from ..core.config import settings
from ..core.security import generate_token, hash_token
from ..db.connection import get_session, parse_uuid
from ..db.tables import ApiKey, AuthSession, Membership, SupportGrant, User
from ..models.common import utcnow


# ── Session lifecycle helpers ──────────────────────────────────────────────────
async def create_auth_session(session: AsyncSession, user: User, request: Optional[Request] = None):
    """Insert a new auth session; return (raw_session_token, csrf_token)."""
    raw = generate_token()
    csrf = generate_token()
    now = utcnow()
    row = AuthSession(
        userId=user.id,
        tokenHash=hash_token(raw),
        csrfToken=csrf,
        createdAt=now,
        lastSeenAt=now,
        expiresAt=now + timedelta(seconds=settings.session_absolute_ttl),
        userAgent=(request.headers.get("user-agent") if request else None),
        ip=(request.client.host if request and request.client else None),
    )
    session.add(row)
    await session.flush()
    return raw, csrf


def set_auth_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    common = dict(
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
        max_age=settings.session_absolute_ttl,
    )
    response.set_cookie(settings.session_cookie_name, session_token, httponly=True, **common)
    # csrf cookie is readable by JS (double-submit); not httpOnly.
    response.set_cookie(settings.csrf_cookie_name, csrf_token, httponly=False, **common)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/", domain=settings.cookie_domain)
    response.delete_cookie(settings.csrf_cookie_name, path="/", domain=settings.cookie_domain)


# ── Dependencies ───────────────────────────────────────────────────────────────
async def get_current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User:
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        raise HTTPException(401, "Not authenticated")
    row = (await session.execute(
        select(AuthSession).where(AuthSession.tokenHash == hash_token(raw))
    )).scalars().first()
    now = utcnow()
    if row is None:
        raise HTTPException(401, "Not authenticated")
    idle_deadline = row.lastSeenAt + timedelta(seconds=settings.session_idle_ttl)
    if row.expiresAt <= now or idle_deadline <= now:
        await session.delete(row)
        raise HTTPException(401, "Session expired")
    row.lastSeenAt = now  # sliding idle window
    user = await session.get(User, row.userId)
    if user is None:
        await session.delete(row)
        raise HTTPException(401, "Not authenticated")
    return user


# Privilege ordering. A check "role ≥ X" is `ROLE_RANK[role] >= ROLE_RANK[X]`.
ROLE_RANK = {"user": 0, "admin": 1, "super_admin": 2}


def _rank(role: Optional[str]) -> int:
    return ROLE_RANK.get(role or "", -1)


@dataclass
class CompanyContext:
    company_id: uuid.UUID
    role: str
    user: Optional[User] = None   # None for API-key (service) principals

    def at_least(self, role: str) -> bool:
        return _rank(self.role) >= _rank(role)


# ── Sandbox restrictions ───────────────────────────────────────────────────────
SANDBOX_BLOCKED = ("Not available in the sandbox — create a free account to keep "
                   "your line and unlock this")

# Row caps for anonymous try-it companies: enough to build and run a realistic
# demo line, small enough that the endpoint can't be used to fill the database.
SANDBOX_LIMITS = {"stations": 40, "cards": 200, "lot_templates": 40, "processes": 10}


def is_sandbox(principal) -> bool:
    user = principal.user if isinstance(principal, CompanyContext) else principal
    return user is not None and getattr(user, "isSandbox", False)


def ensure_full_account(principal) -> None:
    """Reject sandbox principals on capability endpoints (floor-plan upload,
    invitations, API keys, orders, company creation). Accepts a User or a
    CompanyContext; API-key principals (user=None) pass — keys can't be
    created from a sandbox in the first place."""
    if is_sandbox(principal):
        raise HTTPException(403, SANDBOX_BLOCKED)


async def ensure_sandbox_quota(session: AsyncSession, ctx: "CompanyContext", table) -> None:
    """Cap how many rows an anonymous sandbox company may create, so the public
    endpoint can't be turned into unbounded storage. No-op for real accounts."""
    if not is_sandbox(ctx):
        return
    from sqlalchemy import func
    limit = SANDBOX_LIMITS.get(table.__tablename__)
    if limit is None:
        return
    count = (await session.execute(
        select(func.count()).select_from(table).where(table.companyId == ctx.company_id)
    )).scalar_one()
    if count >= limit:
        raise HTTPException(
            403, f"Sandbox limit reached ({limit} {table.__tablename__.replace('_', ' ')}) — "
                 "create a free account to keep building")


# ── Platform staff (customer service) ─────────────────────────────────────────
def platform_role_of(user: User) -> Optional[str]:
    """'owner' (env allowlist — not a DB value), 'support' (users.platformRole),
    or None for everyone else."""
    if user.email.lower() in settings.platform_owner_list:
        return "owner"
    return user.platformRole if user.platformRole == "support" else None


async def find_active_grant(session: AsyncSession, user: User, company_uuid) -> Optional[SupportGrant]:
    """The user's live impersonation grant for this company, if any."""
    if platform_role_of(user) is None:
        return None
    return (await session.execute(
        select(SupportGrant).where(
            SupportGrant.userId == user.id,
            SupportGrant.companyId == company_uuid,
            SupportGrant.endedAt.is_(None),
            SupportGrant.expiresAt > utcnow(),
        )
    )).scalars().first()


async def require_platform_staff(user: User = Depends(get_current_user)) -> User:
    """Owner or support. 404 (not 403) so the surface never advertises itself."""
    if platform_role_of(user) is None:
        raise HTTPException(404, "Not found")
    return user


async def require_platform_owner(user: User = Depends(get_current_user)) -> User:
    if platform_role_of(user) != "owner":
        raise HTTPException(404, "Not found")
    return user


async def get_active_company(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CompanyContext:
    company_uuid = parse_uuid(request.headers.get("X-Company-Id"))
    if company_uuid is None:
        raise HTTPException(400, "X-Company-Id header required")
    membership = (await session.execute(
        select(Membership).where(
            Membership.companyId == company_uuid,
            Membership.userId == user.id,
        )
    )).scalars().first()
    if membership is None:
        # Customer service with a live impersonation grant acts as super_admin.
        # Grants are explicit, time-boxed, and audited — never a silent bypass.
        if await find_active_grant(session, user, company_uuid) is not None:
            usage.bump_api(str(company_uuid))
            return CompanyContext(company_id=company_uuid, role="super_admin", user=user)
        raise HTTPException(403, "You are not a member of this company")
    # Meter only verified access, so no one can inflate another tenant's usage
    # by naming their company id in a header.
    usage.bump_api(str(company_uuid))
    return CompanyContext(company_id=company_uuid, role=membership.role, user=user)


async def require_admin(ctx: CompanyContext = Depends(get_active_company)) -> CompanyContext:
    """Admin or above — may manage lots and orders (create lots, pull precursors,
    release/cancel orders) on top of all operator actions."""
    if not ctx.at_least("admin"):
        raise HTTPException(403, "Admin role required")
    return ctx


async def require_super_admin(ctx: CompanyContext = Depends(get_active_company)) -> CompanyContext:
    """Super-admin only — process/floor configuration, member management, and the
    structural lot operations (unconstrained move, unmerge, delete)."""
    if not ctx.at_least("super_admin"):
        raise HTTPException(403, "Super-admin role required")
    return ctx


def _extract_api_key(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    return request.headers.get("X-Api-Key")


def require_scope(scope: str, *, session_role: str = "admin"):
    """Dependency factory for integration-facing endpoints: accept a company-
    scoped API key carrying ``scope`` (via ``Authorization: Bearer`` / ``X-Api-Key``),
    OR an authenticated session whose role is **at least** ``session_role``
    (``'user'`` | ``'admin'`` | ``'super_admin'``). A key resolves its own company,
    so ``X-Company-Id`` is ignored for key callers — automatic tenant isolation.
    """
    async def dep(request: Request, session: AsyncSession = Depends(get_session)) -> CompanyContext:
        raw = _extract_api_key(request)
        if raw is not None:
            key = (await session.execute(
                select(ApiKey).where(ApiKey.keyHash == hash_token(raw))
            )).scalars().first()
            if key is None or key.revokedAt is not None:
                raise HTTPException(401, "Invalid or revoked API key")
            if scope not in (key.scopes or []):
                raise HTTPException(403, f"API key lacks the '{scope}' scope")
            key.lastUsedAt = utcnow()
            usage.bump_api(str(key.companyId))   # verified key → real attribution
            # A scoped key acts as the 'admin' tier (release orders, run reports,
            # scan-to-advance) — never super-admin config.
            return CompanyContext(company_id=key.companyId, role="admin", user=None)

        # No key → fall back to an authenticated session, checked by rank.
        user = await get_current_user(request, session)
        ctx = await get_active_company(request, user, session)
        if not ctx.at_least(session_role):
            raise HTTPException(403, f"{session_role} role required")
        return ctx

    return dep


# The orders endpoints use this name; keep it as the canonical 'orders'-scoped dep.
require_orders_access = require_scope("orders")


async def load_membership(
    session: AsyncSession, user: User, company_id: uuid.UUID, *, min_role: str = "user"
) -> Membership:
    """Membership check for endpoints whose company comes from the URL path
    (companies/members/invitations) rather than the X-Company-Id header. Pass
    ``min_role`` to require at least that tier (member management is
    ``super_admin``)."""
    membership = (await session.execute(
        select(Membership).where(
            Membership.companyId == company_id,
            Membership.userId == user.id,
        )
    )).scalars().first()
    if membership is None:
        # Impersonating staff act as a (non-persisted) super_admin membership,
        # so support can e.g. appoint a replacement super admin.
        if await find_active_grant(session, user, company_id) is not None:
            return Membership(companyId=company_id, userId=user.id, role="super_admin")
        raise HTTPException(403, "You are not a member of this company")
    if _rank(membership.role) < _rank(min_role):
        raise HTTPException(403, f"{min_role} role required")
    return membership
