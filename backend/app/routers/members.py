from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import Membership, User
from ..deps.auth import get_current_user, load_membership
from ..models.company import MemberPublic, RoleUpdate

router = APIRouter(prefix="/companies", tags=["members"])


async def _super_admin_count(session: AsyncSession, company_id) -> int:
    """A company must always keep at least one super-admin (its owner)."""
    return (await session.execute(
        select(func.count()).select_from(Membership).where(
            Membership.companyId == company_id, Membership.role == "super_admin"
        )
    )).scalar_one()


def _to_member(m: Membership, u: User) -> MemberPublic:
    return MemberPublic(userId=str(u.id), email=u.email, name=u.name, role=m.role, joinedAt=m.createdAt)


@router.get("/{company_id}/members", response_model=List[MemberPublic])
async def list_members(company_id: str, user: User = Depends(get_current_user),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    cid = require_uuid(company_id, "Company not found")
    await load_membership(session, user, cid)  # any member may view the roster
    rows = (await session.execute(
        select(Membership, User)
        .join(User, Membership.userId == User.id)
        .where(Membership.companyId == cid)
        .order_by(Membership.role, User.email)
    )).all()
    return [_to_member(m, u) for (m, u) in rows]


@router.delete("/{company_id}/members/{user_id}", status_code=204)
async def remove_member(company_id: str, user_id: str, user: User = Depends(get_current_user),
                        session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    cid = require_uuid(company_id, "Company not found")
    target_uid = require_uuid(user_id, "Member not found")
    await load_membership(session, user, cid, min_role="super_admin")

    target = (await session.execute(
        select(Membership).where(Membership.companyId == cid, Membership.userId == target_uid)
    )).scalars().first()
    if target is None:
        raise HTTPException(404, "Member not found")
    if target.role == "super_admin" and await _super_admin_count(session, cid) <= 1:
        raise HTTPException(400, "Cannot remove the last super-admin of a company")
    await session.delete(target)


@router.patch("/{company_id}/members/{user_id}", response_model=MemberPublic)
async def change_role(company_id: str, user_id: str, body: RoleUpdate,
                      user: User = Depends(get_current_user),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    cid = require_uuid(company_id, "Company not found")
    target_uid = require_uuid(user_id, "Member not found")
    await load_membership(session, user, cid, min_role="super_admin")

    target = (await session.execute(
        select(Membership).where(Membership.companyId == cid, Membership.userId == target_uid)
    )).scalars().first()
    if target is None:
        raise HTTPException(404, "Member not found")
    if target.role == "super_admin" and body.role != "super_admin" and await _super_admin_count(session, cid) <= 1:
        raise HTTPException(400, "Cannot demote the last super-admin of a company")
    target.role = body.role
    await session.flush()
    target_user = await session.get(User, target_uid)
    return _to_member(target, target_user)
