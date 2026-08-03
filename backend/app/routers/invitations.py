from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import languages
from ..core.config import settings
from ..core.email import send_invitation_email
from ..core.ratelimit import limiter
from ..core.security import generate_token, hash_password, hash_token
from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import (Company, GlobalSettings as GlobalSettingsRow,
                         Invitation, Membership, User)
from ..deps.auth import create_auth_session, ensure_full_account, get_current_user, load_membership, set_auth_cookies
from ..models.auth import MeResponse
from ..models.company import (
    AcceptInviteSignup,
    InviteCreate,
    InvitationPublic,
    InvitePreview,
)
from ..models.common import utcnow
from .auth import _me_response

router = APIRouter(tags=["invitations"])


def _status(inv: Invitation) -> str:
    if inv.acceptedAt is not None:
        return "accepted"
    if inv.revokedAt is not None:
        return "revoked"
    if inv.expiresAt <= utcnow():
        return "expired"
    return "pending"


def _to_public(inv: Invitation, dev_link: str | None = None) -> InvitationPublic:
    return InvitationPublic(
        id=str(inv.id), email=inv.email, role=inv.role, status=_status(inv),
        createdAt=inv.createdAt, expiresAt=inv.expiresAt, devLink=dev_link,
    )


async def _valid_pending_invite(session: AsyncSession, token: str) -> Invitation | None:
    inv = (await session.execute(
        select(Invitation).where(Invitation.tokenHash == hash_token(token))
    )).scalars().first()
    if inv is None or _status(inv) != "pending":
        return None
    return inv


# ── Admin: manage a company's invitations ──────────────────────────────────────
async def _company_languages(session: AsyncSession, company_id) -> list[str]:
    """The languages this company runs in — its global_settings row, or every
    language the product speaks when the row has never been created (a company
    that never opened Settings has not narrowed anything)."""
    row = (await session.execute(
        select(GlobalSettingsRow).where(GlobalSettingsRow.companyId == company_id)
    )).scalars().first()
    if row is None or not row.supportedLanguages:
        return list(languages.LANGUAGES)
    return list(row.supportedLanguages)


@router.post("/companies/{company_id}/invitations", response_model=InvitationPublic, status_code=201)
async def create_invitation(company_id: str, body: InviteCreate,
                            user: User = Depends(get_current_user),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    ensure_full_account(user)   # sandbox: no inviting real users
    cid = require_uuid(company_id, "Company not found")
    await load_membership(session, user, cid, min_role="super_admin")
    email = body.email.lower()

    already = (await session.execute(
        select(Membership).join(User, Membership.userId == User.id)
        .where(Membership.companyId == cid, User.email == email)
    )).first()
    if already is not None:
        raise HTTPException(400, "That user is already a member of this company")

    # Supersede any existing live invite for this email + company.
    await session.execute(
        update(Invitation)
        .where(Invitation.companyId == cid, Invitation.email == email,
               Invitation.acceptedAt.is_(None), Invitation.revokedAt.is_(None))
        .values(revokedAt=utcnow())
    )

    token = generate_token()
    inv = Invitation(
        companyId=cid, email=email, role=body.role, tokenHash=hash_token(token),
        invitedByUserId=user.id, expiresAt=utcnow() + timedelta(seconds=settings.invite_ttl),
    )
    session.add(inv)
    await session.flush()
    company = await session.get(Company, cid)
    link = await send_invitation_email(email, token, company.name)
    return _to_public(inv, dev_link=link if settings.dev else None)


@router.get("/companies/{company_id}/invitations", response_model=List[InvitationPublic])
async def list_invitations(company_id: str, user: User = Depends(get_current_user),
                           session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    cid = require_uuid(company_id, "Company not found")
    await load_membership(session, user, cid, min_role="super_admin")
    rows = (await session.execute(
        select(Invitation).where(
            Invitation.companyId == cid,
            Invitation.acceptedAt.is_(None),
            Invitation.revokedAt.is_(None),
            Invitation.expiresAt > utcnow(),
        ).order_by(Invitation.createdAt.desc())
    )).scalars().all()
    return [_to_public(inv) for inv in rows]


@router.delete("/companies/{company_id}/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(company_id: str, invitation_id: str,
                            user: User = Depends(get_current_user),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    cid = require_uuid(company_id, "Company not found")
    inv_id = require_uuid(invitation_id, "Invitation not found")
    await load_membership(session, user, cid, min_role="super_admin")
    inv = await session.get(Invitation, inv_id)
    if inv is None or inv.companyId != cid:
        raise HTTPException(404, "Invitation not found")
    if inv.acceptedAt is None and inv.revokedAt is None:
        inv.revokedAt = utcnow()


# ── Public / invitee: preview and accept ───────────────────────────────────────
@router.get("/invitations/{token}", response_model=InvitePreview)
async def preview_invitation(token: str, session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    inv = (await session.execute(
        select(Invitation).where(Invitation.tokenHash == hash_token(token))
    )).scalars().first()
    if inv is None:
        return InvitePreview(valid=False, reason="not_found")
    status = _status(inv)
    if status != "pending":
        return InvitePreview(valid=False, reason=status)
    company = await session.get(Company, inv.companyId)
    return InvitePreview(valid=True, companyName=company.name if company else None,
                         email=inv.email, role=inv.role,
                         supportedLanguages=await _company_languages(session, inv.companyId))


@router.post("/invitations/{token}/accept", response_model=MeResponse)
async def accept_invitation(token: str, user: User = Depends(get_current_user),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    inv = await _valid_pending_invite(session, token)
    if inv is None:
        raise HTTPException(400, "This invitation is no longer valid")
    if user.email.lower() != inv.email.lower():
        raise HTTPException(403, "This invitation was sent to a different email address")

    membership = (await session.execute(
        select(Membership).where(Membership.companyId == inv.companyId, Membership.userId == user.id)
    )).scalars().first()
    if membership is None:
        session.add(Membership(companyId=inv.companyId, userId=user.id, role=inv.role))
    else:
        membership.role = inv.role
    inv.acceptedAt = utcnow()
    await session.flush()
    return await _me_response(session, user)


@router.post("/invitations/{token}/accept-signup", response_model=MeResponse)
@limiter.limit("10/hour")
async def accept_invitation_signup(token: str, body: AcceptInviteSignup,
                                   request: Request, response: Response,
                                   session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Create a brand-new (auto-verified) account for the invited email and join
    the company in one step. The invite itself proves control of the inbox."""
    inv = await _valid_pending_invite(session, token)
    if inv is None:
        raise HTTPException(400, "This invitation is no longer valid")
    if len(body.password) < settings.password_min_length:
        raise HTTPException(422, f"password must be at least {settings.password_min_length} characters")

    email = inv.email.lower()
    existing = (await session.execute(select(User).where(User.email == email))).scalars().first()
    if existing is not None:
        raise HTTPException(409, "An account with this email already exists — please sign in and accept.")

    if body.language is not None:
        offered = await _company_languages(session, inv.companyId)
        if body.language not in offered:
            raise HTTPException(422,
                f"This company runs in {', '.join(offered)} — "
                f"'{body.language}' is not one of them")
    user = User(email=email, passwordHash=hash_password(body.password),
                emailVerified=True, name=body.name,
                preferences={"language": body.language} if body.language else {})
    session.add(user)
    await session.flush()
    session.add(Membership(companyId=inv.companyId, userId=user.id, role=inv.role))
    inv.acceptedAt = utcnow()
    raw, csrf = await create_auth_session(session, user, request)
    set_auth_cookies(response, raw, csrf)
    return await _me_response(session, user)
