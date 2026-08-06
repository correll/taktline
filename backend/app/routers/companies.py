from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import entitlements
from .network import attribute_signup
from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import Company, Membership, User
from ..deps.auth import ensure_full_account, get_current_user, load_membership
from ..models.company import CompanyCreate, CompanyPublic

router = APIRouter(prefix="/companies", tags=["companies"])


def _to_company(c: Company, role: Optional[str] = None) -> CompanyPublic:
    return CompanyPublic(id=str(c.id), name=c.name, slug=c.slug, timezone=c.timezone, role=role)


@router.post("/", response_model=CompanyPublic, status_code=201)
async def create_company(body: CompanyCreate, user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    ensure_full_account(user)   # sandbox visitors stay in their sandbox
    if not user.emailVerified:
        raise HTTPException(403, "Verify your email before creating a company")
    company = Company(name=body.name, timezone=body.timezone)
    session.add(company)
    await session.flush()
    # The creator becomes the company's super-admin (its owner).
    session.add(Membership(companyId=company.id, userId=user.id, role="super_admin"))
    # Every company starts on the free tier — no clock, no grant to record.
    await entitlements.ensure_subscription(session, company.id)
    # If they came here because a customer asked them to, record it.
    await attribute_signup(session, company.id, body.supplierInvite)
    return _to_company(company, role="super_admin")


@router.get("/", response_model=List[CompanyPublic])
async def list_my_companies(user: User = Depends(get_current_user),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(Membership, Company)
        .join(Company, Membership.companyId == Company.id)
        .where(Membership.userId == user.id)
        .order_by(Company.name)
    )).all()
    return [_to_company(c, role=m.role) for (m, c) in rows]


@router.get("/{company_id}", response_model=CompanyPublic)
async def get_company(company_id: str, user: User = Depends(get_current_user),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    cid = require_uuid(company_id, "Company not found")
    membership = await load_membership(session, user, cid)
    company = await session.get(Company, cid)
    return _to_company(company, role=membership.role)


class CompanyDelete(BaseModel):
    confirmName: str


@router.delete("/{company_id}", status_code=204)
async def delete_company(company_id: str, body: CompanyDelete,
                         user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """The owner deletes their company — everything in it, permanently.

    Mirrors the staff endpoint (`/platform/companies/{id}`): the exact name
    confirms, and Stripe is released *before* the cascade removes the rows
    that could still find the live subscription — cascade first and the
    customer keeps being billed for an account that no longer exists.

    Membership is checked BEFORE the name is compared, deliberately: comparing
    first would let anyone probe names against foreign company ids and turn
    the confirmation into a cross-tenant name oracle. Deliberately ungated by
    the plan state — deleting the account must work for a paused company,
    or the pause holds the data hostage after all.
    """
    cid = require_uuid(company_id, "Company not found")
    await load_membership(session, user, cid, min_role="super_admin")
    company = await session.get(Company, cid)
    if company is None:
        raise HTTPException(404, "Company not found")
    if body.confirmName.strip() != company.name:
        raise HTTPException(400, "Type the company's exact name to confirm deletion")
    await entitlements.release_company(session, cid)
    await session.delete(company)   # every domain row cascades via companyId FKs
