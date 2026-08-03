"""Authentication endpoints: signup, email verification, login/logout, session
introspection (`/me`), and password reset. Plus a dev-only bootstrap helper.
"""

import uuid
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.email import (
    send_password_reset_email,
    send_verification_email,
)
from ..core import entitlements, languages, plans
from ..core.ratelimit import limiter
from ..core.security import (dummy_verify, generate_token, hash_password, hash_token,
                             needs_rehash, verify_password)
from ..db.connection import SESSION_SCOPE, get_session
from ..db.tables import AuthSession, AuthToken, Company, Membership, SupportGrant, User
from ..deps.auth import (
    clear_auth_cookies,
    create_auth_session,
    get_current_user,
    platform_role_of,
    set_auth_cookies,
)
from .network import attribute_signup
from ..models.auth import (
    CompanyMembership,
    ForgotPasswordBody,
    LoginBody,
    MeResponse,
    MessageResponse,
    PreferencesPatch,
    ResendVerificationBody,
    ResetPasswordBody,
    SignupBody,
    UserPublic,
    VerifyEmailBody,
)
from ..models.common import utcnow

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Helpers ────────────────────────────────────────────────────────────────────
def _to_user_public(user: User) -> UserPublic:
    return UserPublic(id=str(user.id), email=user.email, emailVerified=user.emailVerified,
                      name=user.name, preferences=user.preferences or {},
                      platformRole=platform_role_of(user), isSandbox=user.isSandbox)


async def _me_response(session: AsyncSession, user: User) -> MeResponse:
    rows = (await session.execute(
        select(Membership, Company)
        .join(Company, Membership.companyId == Company.id)
        .where(Membership.userId == user.id)
        .order_by(Company.name)
    )).all()
    companies = []
    for (m, c) in rows:
        ent = await entitlements.resolve(session, c.id, user=user)
        companies.append(CompanyMembership(
            id=str(c.id), name=c.name, slug=c.slug, role=m.role, timezone=c.timezone,
            plan=ent.plan.code, planLabel=ent.plan.label, planState=ent.state,
            stationLimit=ent.station_limit, integrations=ent.integrations,
        ))

    # Platform staff: active impersonation grants appear as extra super_admin
    # "memberships" (flagged) so the switcher/WS/API headers all just work.
    if platform_role_of(user) is not None:
        member_ids = {str(c.id) for (_, c) in rows}
        grant_rows = (await session.execute(
            select(SupportGrant, Company)
            .join(Company, SupportGrant.companyId == Company.id)
            .where(SupportGrant.userId == user.id,
                   SupportGrant.endedAt.is_(None),
                   SupportGrant.expiresAt > utcnow())
            .order_by(Company.name)
        )).all()
        for (g, c) in grant_rows:
            if str(c.id) not in member_ids:
                member_ids.add(str(c.id))
                ent = await entitlements.resolve(session, c.id, user=user)
                companies.append(CompanyMembership(
                    id=str(c.id), name=c.name, slug=c.slug, role="super_admin",
                    timezone=c.timezone, impersonated=True,
                    impersonationExpiresAt=g.expiresAt,
                    plan=ent.plan.code, planLabel=ent.plan.label,
                    planState=ent.state, stationLimit=ent.station_limit,
                    integrations=ent.integrations,
                ))
    return MeResponse(user=_to_user_public(user), companies=companies)


async def _new_token(session: AsyncSession, user_id, purpose: str, ttl: int) -> str:
    raw = generate_token()
    session.add(AuthToken(
        userId=user_id, purpose=purpose, tokenHash=hash_token(raw),
        expiresAt=utcnow() + timedelta(seconds=ttl),
    ))
    return raw


async def _consume_token(session: AsyncSession, raw: str, purpose: str) -> Optional[AuthToken]:
    row = (await session.execute(
        select(AuthToken).where(AuthToken.tokenHash == hash_token(raw), AuthToken.purpose == purpose)
    )).scalars().first()
    if row is None or row.usedAt is not None or row.expiresAt <= utcnow():
        return None
    row.usedAt = utcnow()
    return row


def _dev(link: Optional[str]) -> Optional[str]:
    return link if settings.dev else None


# ── Signup / verification ──────────────────────────────────────────────────────
async def _adopt_sandbox(session: AsyncSession, request: Request, new_user: User,
                         company_name: Optional[str]) -> bool:
    """Hand the sandbox line this browser built to a freshly created account.

    The sandbox session cookie is the authorisation — it proves the caller owns
    that throwaway account, so nothing has to be typed in. Only a company whose
    members are *all* sandbox users can move, which keeps this from ever being
    a way to reach a real tenant. The sandbox user is then deleted; the company
    survives because a real member now holds it, and every sandbox restriction
    lifts with the flag it was attached to.
    """
    sandbox = await _current_sandbox(request, session)
    if sandbox is None:
        return False

    memberships = (await session.execute(
        select(Membership).where(Membership.userId == sandbox.id)
    )).scalars().all()
    adopted = False
    for m in memberships:
        others = (await session.execute(
            select(User.isSandbox).join(Membership, Membership.userId == User.id)
            .where(Membership.companyId == m.companyId, Membership.userId != sandbox.id)
        )).scalars().all()
        if any(flag is False for flag in others):
            continue                       # a real member is present — never touch it
        session.add(Membership(companyId=m.companyId, userId=new_user.id, role="super_admin"))
        # It stops being a sandbox the moment a real person owns it, so it
        # stops being on the sandbox plan too. It becomes a free account —
        # there is no clock to start, because the free tier has none.
        sub = await entitlements.ensure_subscription(session, m.companyId)
        sub.planCode = plans.FREE
        if company_name and company_name.strip():
            company = await session.get(Company, m.companyId)
            if company is not None:
                company.name = company_name.strip()[:120]
                company.updatedAt = utcnow()
        adopted = True

    if adopted:
        # Cascades the sandbox membership and its sessions; the line stays.
        await session.delete(sandbox)
        await session.flush()
    return adopted


@router.post("/signup", response_model=MessageResponse, status_code=202)
@limiter.limit("10/hour")
async def signup(request: Request, body: SignupBody, session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    email = body.email.lower()
    existing = (await session.execute(select(User).where(User.email == email))).scalars().first()
    link = None
    adopted = False
    if body.language is not None and not languages.valid(body.language):
        raise HTTPException(422, f"Unknown language '{body.language}'")
    if existing is None:
        user = User(email=email, passwordHash=hash_password(body.password),
                    emailVerified=False, name=body.name,
                    preferences={"language": body.language} if body.language else {},
                    termsVersion=body.acceptedTermsVersion,
                    termsAcceptedAt=utcnow() if body.acceptedTermsVersion else None)
        session.add(user)
        await session.flush()
        if body.adoptSandbox:
            adopted = await _adopt_sandbox(session, request, user, body.companyName)
            if adopted:
                # The other door a company comes through. Attributing only at
                # POST /companies/ would miss every supplier who tried the
                # sandbox first — which is the path the invitation email
                # actually recommends.
                membership = (await session.execute(
                    select(Membership).where(Membership.userId == user.id)
                )).scalars().first()
                if membership is not None:
                    await attribute_signup(session, membership.companyId,
                                           body.supplierInvite)
        token = await _new_token(session, user.id, "email_verify", settings.email_verify_ttl)
        link = await send_verification_email(email, token)
    elif not existing.emailVerified:
        # Account exists but unverified — resend, without confirming existence.
        token = await _new_token(session, existing.id, "email_verify", settings.email_verify_ttl)
        link = await send_verification_email(email, token)
    # else: verified account already exists — say nothing different.
    return MessageResponse(
        message=("Your line is saved — verify your email to sign in and pick it up."
                 if adopted else
                 "If that email is available, a verification link has been sent."),
        devLink=_dev(link),
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(body: VerifyEmailBody, session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _consume_token(session, body.token, "email_verify")
    if row is None:
        raise HTTPException(400, "Invalid or expired verification link")
    user = await session.get(User, row.userId)
    if user is not None:
        user.emailVerified = True
    return MessageResponse(message="Email verified. You can now sign in.")


@router.post("/resend-verification", response_model=MessageResponse)
@limiter.limit("5/hour")
async def resend_verification(request: Request, body: ResendVerificationBody,
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    email = body.email.lower()
    user = (await session.execute(select(User).where(User.email == email))).scalars().first()
    link = None
    if user is not None and not user.emailVerified:
        token = await _new_token(session, user.id, "email_verify", settings.email_verify_ttl)
        link = await send_verification_email(email, token)
    return MessageResponse(
        message="If that account needs verification, a link has been sent.",
        devLink=_dev(link),
    )


# ── Login / logout / me ────────────────────────────────────────────────────────
@router.post("/login", response_model=MeResponse)
@limiter.limit("10/minute")
async def login(request: Request, response: Response, body: LoginBody,
                session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    email = body.email.lower()
    user = (await session.execute(select(User).where(User.email == email))).scalars().first()
    if user is None:
        dummy_verify()  # equalize timing so unknown emails aren't detectable
        raise HTTPException(401, "Invalid email or password")
    if not verify_password(user.passwordHash, body.password):
        raise HTTPException(401, "Invalid email or password")
    # Only reachable with a correct password, so this does not aid enumeration.
    if not user.emailVerified:
        raise HTTPException(403, "Please verify your email before signing in")
    # A successful login is the one moment the plaintext password is in hand, so
    # it is the only chance to migrate this hash onto the current argon2 cost.
    # Without it, changed parameters would apply to new accounts only and every
    # existing user would keep paying the old price forever.
    if needs_rehash(user.passwordHash):
        user.passwordHash = hash_password(body.password)
    raw, csrf = await create_auth_session(session, user, request)
    set_auth_cookies(response, raw, csrf)
    return await _me_response(session, user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response,
                 user: User = Depends(get_current_user),
                 session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    raw = request.cookies.get(settings.session_cookie_name)
    if raw:
        row = (await session.execute(
            select(AuthSession).where(AuthSession.tokenHash == hash_token(raw))
        )).scalars().first()
        if row is not None:
            await session.delete(row)
    clear_auth_cookies(response)


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    return await _me_response(session, user)


@router.patch("/me/preferences", response_model=UserPublic)
async def update_preferences(body: PreferencesPatch,
                             user: User = Depends(get_current_user),
                             session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Merge the provided keys into the user's cross-device preferences
    (currently just the day/night theme)."""
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    # Reassign (not mutate) so SQLAlchemy sees the JSONB change.
    user.preferences = {**(user.preferences or {}), **patch}
    user.updatedAt = utcnow()
    session.add(user)
    await session.flush()
    return _to_user_public(user)


# ── Password reset ─────────────────────────────────────────────────────────────
@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("5/hour")
async def forgot_password(request: Request, body: ForgotPasswordBody,
                          session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    email = body.email.lower()
    user = (await session.execute(select(User).where(User.email == email))).scalars().first()
    link = None
    if user is not None:
        token = await _new_token(session, user.id, "password_reset", settings.password_reset_ttl)
        link = await send_password_reset_email(email, token)
    return MessageResponse(
        message="If that account exists, a password reset link has been sent.",
        devLink=_dev(link),
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(body: ResetPasswordBody, session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _consume_token(session, body.token, "password_reset")
    if row is None:
        raise HTTPException(400, "Invalid or expired reset link")
    user = await session.get(User, row.userId)
    if user is None:
        raise HTTPException(400, "Invalid or expired reset link")
    user.passwordHash = hash_password(body.newPassword)
    user.emailVerified = True  # completing a reset proves control of the inbox
    # Revoke all existing sessions on password change.
    await session.execute(delete(AuthSession).where(AuthSession.userId == user.id))
    return MessageResponse(message="Password updated. Please sign in.")


# ── Public sandbox (landing-page "five-minute tutorial") ──────────────────────
async def _current_sandbox(request: Request, session: AsyncSession) -> Optional[User]:
    """The sandbox user this browser is already signed in as, if any."""
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        return None
    row = (await session.execute(
        select(AuthSession).where(AuthSession.tokenHash == hash_token(raw))
    )).scalars().first()
    if row is None or row.expiresAt <= utcnow():
        return None
    user = await session.get(User, row.userId)
    return user if user is not None and user.isSandbox else None



@router.post("/sandbox")
@limiter.limit("10/hour")
async def create_sandbox(request: Request, response: Response,
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """One-click throwaway account + company for trying Taktline without
    signing up. The account is permanently marked isSandbox, which blocks
    floor-plan uploads, invitations, API keys, orders, and creating further
    companies (enforced server-side via ensure_full_account)."""
    # Idempotent: someone already inside a sandbox gets their own line back
    # rather than a fresh empty one (clicking "try it" again, or arriving from
    # the marketing site in the same browser).
    existing = await _current_sandbox(request, session)
    if existing is not None:
        membership = (await session.execute(
            select(Membership).where(Membership.userId == existing.id)
        )).scalars().first()
        if membership is not None:
            return {"companyId": str(membership.companyId), "csrfToken": None,
                    "userId": str(existing.id), "resumed": True}

    tag = uuid.uuid4().hex[:10]
    user = User(email=f"sandbox-{tag}@taktline.sandbox",
                passwordHash=hash_password(generate_token()),   # never known → never signable-in again
                emailVerified=True, name="Sandbox visitor", isSandbox=True)
    session.add(user)
    await session.flush()
    company = Company(name="Sandbox factory", timezone="UTC")
    session.add(company)
    await session.flush()
    session.add(Membership(companyId=company.id, userId=user.id, role="super_admin"))
    # Sandbox plan: quota'd, never billed, never locked, swept after 7 days.
    await entitlements.ensure_subscription(session, company.id, plan_code=plans.SANDBOX)
    raw, csrf = await create_auth_session(session, user, request)
    set_auth_cookies(response, raw, csrf)
    return {"companyId": str(company.id), "csrfToken": csrf, "userId": str(user.id)}


# ── Dev-only bootstrap (seed / tests) ──────────────────────────────────────────
class DevBootstrapBody(BaseModel):
    email: EmailStr = "demo-admin@taktline.dev"
    password: str = "demo-password-123"
    companyName: str = "Demo Company"


@router.post("/dev/bootstrap")
async def dev_bootstrap(request: Request, response: Response, body: DevBootstrapBody,
                        session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Create a verified admin + company and return a logged-in session in one
    call. Disabled unless TAKTLINE_DEV=1."""
    if not settings.dev:
        raise HTTPException(404, "Not found")
    email = body.email.lower()
    user = (await session.execute(select(User).where(User.email == email))).scalars().first()
    if user is None:
        user = User(email=email, passwordHash=hash_password(body.password),
                    emailVerified=True, name="Demo Admin")
        session.add(user)
        await session.flush()
    else:
        user.emailVerified = True
    company = Company(name=body.companyName, timezone="UTC")
    session.add(company)
    await session.flush()
    session.add(Membership(companyId=company.id, userId=user.id, role="super_admin"))
    await entitlements.ensure_subscription(session, company.id)
    raw, csrf = await create_auth_session(session, user, request)
    set_auth_cookies(response, raw, csrf)
    return {"companyId": str(company.id), "csrfToken": csrf, "userId": str(user.id), "email": email}
