"""Scoped API keys for integrations (managed from the Integrations UI, admin only)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import generate_api_key, hash_token
from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import ApiKey as ApiKeyRow
from ..deps.auth import CompanyContext, ensure_full_account, require_super_admin
from ..models.apikey import AVAILABLE_SCOPES, ApiKeyCreate, ApiKeyCreated, ApiKeyPublic
from ..models.common import utcnow

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("/scopes")
async def list_scopes(_: CompanyContext = Depends(require_super_admin)):
    """The catalog the UI renders as the scope picker."""
    return [{"scope": s, "description": d} for s, d in AVAILABLE_SCOPES.items()]


def _to_public(k: ApiKeyRow) -> ApiKeyPublic:
    return ApiKeyPublic(
        id=str(k.id), name=k.name, prefix=k.prefix, scopes=k.scopes or [],
        createdAt=k.createdAt, lastUsedAt=k.lastUsedAt, revoked=k.revokedAt is not None,
    )


@router.post("/", response_model=ApiKeyCreated, status_code=201)
async def create_key(body: ApiKeyCreate, ctx: CompanyContext = Depends(require_super_admin),
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    ensure_full_account(ctx)   # sandbox: no integrations
    full, prefix = generate_api_key()
    row = ApiKeyRow(
        companyId=ctx.company_id, name=body.name, prefix=prefix,
        keyHash=hash_token(full), scopes=(body.scopes or ["orders"]),
    )
    session.add(row)
    await session.flush()
    return ApiKeyCreated(**_to_public(row).model_dump(), key=full)


@router.get("/", response_model=List[ApiKeyPublic])
async def list_keys(ctx: CompanyContext = Depends(require_super_admin),
                    session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(ApiKeyRow).where(ApiKeyRow.companyId == ctx.company_id).order_by(ApiKeyRow.createdAt.desc())
    )).scalars().all()
    return [_to_public(k) for k in rows]


@router.delete("/{key_id}", status_code=204)
async def revoke_key(key_id: str, ctx: CompanyContext = Depends(require_super_admin),
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await session.get(ApiKeyRow, require_uuid(key_id, "API key not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "API key not found")
    if row.revokedAt is None:
        row.revokedAt = utcnow()
