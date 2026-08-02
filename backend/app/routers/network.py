"""Supplier invitations — `/network/suppliers`.

See `core/network.py` for what an invitation is and, more importantly, what it
is not: attribution, never access.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import network
from ..core.config import settings
from ..core.email import mailer
from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import Company, SupplierInvite, User
from ..deps.auth import CompanyContext, ensure_full_account, require_admin
from ..models.common import utcnow

router = APIRouter(prefix="/network", tags=["network"])


class InviteIn(BaseModel):
    email: EmailStr
    #: "castings", "powder coating" — the inviter's words, used in the email.
    supplies: str = Field("", max_length=120)


class InviteOut(BaseModel):
    id: str
    email: str
    supplies: str
    accepted: bool
    acceptedAt: Optional[str] = None
    createdAt: str


def _token(invite_id) -> str:
    """Proves an invitation is real without letting anyone enumerate them.

    Derived rather than stored, like every other token here — and it is only
    ever used to attribute a signup, so the worst a forged one could do is
    credit the wrong company.
    """
    secret = (settings.stripe_webhook_secret or settings.database_url).encode()
    return hmac.new(secret, f"supplier-invite:{invite_id}".encode(),
                    hashlib.sha256).hexdigest()[:20]


def _to_invite(row: SupplierInvite) -> InviteOut:
    return InviteOut(
        id=str(row.id), email=row.email, supplies=row.supplies,
        accepted=row.acceptedCompanyId is not None,
        acceptedAt=row.acceptedAt.isoformat() if row.acceptedAt else None,
        createdAt=row.createdAt.isoformat(),
    )


@router.get("/suppliers", response_model=List[InviteOut])
async def list_suppliers(ctx: CompanyContext = Depends(require_admin),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(SupplierInvite).where(SupplierInvite.companyId == ctx.company_id)
        .order_by(SupplierInvite.createdAt.desc())
    )).scalars().all()
    return [_to_invite(r) for r in rows]


@router.post("/suppliers", response_model=InviteOut, status_code=201)
async def invite_supplier(body: InviteIn,
                          ctx: CompanyContext = Depends(require_admin),
                          session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Ask a supplier to publish status.

    Idempotent per (company, email): re-inviting the same supplier updates what
    they supply and sends again, rather than filling the list with duplicates —
    a chased supplier is the normal case, not an error.
    """
    ensure_full_account(ctx)      # a throwaway sandbox may not email strangers

    email = str(body.email).lower()
    row = (await session.execute(
        select(SupplierInvite).where(SupplierInvite.companyId == ctx.company_id,
                                     SupplierInvite.email == email)
    )).scalars().first()
    if row is None:
        row = SupplierInvite(companyId=ctx.company_id, email=email,
                             supplies=body.supplies.strip(),
                             invitedByUserId=ctx.user.id if ctx.user else None)
        session.add(row)
        await session.flush()
    else:
        if row.acceptedCompanyId is not None:
            raise HTTPException(409, "They are already on Taktline")
        row.supplies = body.supplies.strip() or row.supplies

    company = await session.get(Company, ctx.company_id)
    base = settings.frontend_base_url.rstrip("/")
    link = f"{base}/signup?supplier={row.id}.{_token(row.id)}"
    try:
        await mailer.send(
            email,
            f"{company.name if company else 'A customer'} would like to see "
            f"where their order is",
            network.invite_body(customer=company.name if company else "A customer",
                                supplies=row.supplies, link=link),
        )
    except Exception as exc:                    # noqa: BLE001
        raise HTTPException(502, f"Could not send the invitation: {exc}") from None
    return _to_invite(row)


@router.delete("/suppliers/{invite_id}", status_code=204)
async def forget_supplier(invite_id: str,
                          ctx: CompanyContext = Depends(require_admin),
                          session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await session.get(SupplierInvite, require_uuid(invite_id, "Not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Not found")
    await session.delete(row)


# ─── Attribution ─────────────────────────────────────────────────────────────

async def attribute_signup(session: AsyncSession, company_id, marker: Optional[str]) -> None:
    """Record that a new company came from a supplier invitation.

    Called from company creation. Deliberately forgiving — a bad or stale
    marker is ignored rather than refused, because failing somebody's signup
    over a mangled query parameter would be an absurd trade.
    """
    if not marker or "." not in marker:
        return
    raw_id, _, token = marker.partition(".")
    try:
        invite_uuid = require_uuid(raw_id, "bad")
    except Exception:
        return
    if not hmac.compare_digest(_token(invite_uuid), token):
        return
    row = await session.get(SupplierInvite, invite_uuid)
    if row is None or row.acceptedCompanyId is not None:
        return
    row.acceptedCompanyId = company_id
    row.acceptedAt = utcnow()
