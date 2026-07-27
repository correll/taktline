from fastapi import APIRouter, HTTPException, Depends
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import get_session, require_uuid, optional_uuid
from ..db.tables import LotTemplate as LotTemplateRow
from ..deps.auth import CompanyContext, ensure_sandbox_quota, get_active_company, require_super_admin
from ..models.lot_template import LotTemplate, LotTemplateCreate, LotTemplateUpdate
from ..models.common import utcnow

router = APIRouter(prefix="/lot-templates", tags=["lot-templates"])

_FK_FIELDS = ("processId", "startStationId")


def _to_template(r: LotTemplateRow) -> LotTemplate:
    return LotTemplate(
        _id=str(r.id),
        name=r.name,
        processId=str(r.processId) if r.processId else None,
        startStationId=str(r.startStationId) if r.startStationId else None,
        fields=r.fields or [],
        color=r.color,
        description=r.description,
        createdAt=r.createdAt,
        updatedAt=r.updatedAt,
    )


async def _get_owned(session: AsyncSession, template_id: str, ctx: CompanyContext) -> LotTemplateRow:
    row = await session.get(LotTemplateRow, require_uuid(template_id, "Template not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Template not found")
    return row


@router.get("/", response_model=List[LotTemplate])
async def list_templates(ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(LotTemplateRow).where(LotTemplateRow.companyId == ctx.company_id)
    )).scalars().all()
    return [_to_template(r) for r in rows]


@router.post("/", response_model=LotTemplate, status_code=201)
async def create_template(body: LotTemplateCreate, ctx: CompanyContext = Depends(require_super_admin),
                          session: AsyncSession = Depends(get_session)):
    await ensure_sandbox_quota(session, ctx, LotTemplateRow)
    data = body.model_dump()
    for f in _FK_FIELDS:
        data[f] = optional_uuid(data.get(f))
    row = LotTemplateRow(**data, companyId=ctx.company_id)
    session.add(row)
    await session.flush()
    return _to_template(row)


@router.get("/{template_id}", response_model=LotTemplate)
async def get_template(template_id: str, ctx: CompanyContext = Depends(get_active_company),
                       session: AsyncSession = Depends(get_session)):
    return _to_template(await _get_owned(session, template_id, ctx))


@router.put("/{template_id}", response_model=LotTemplate)
async def update_template(template_id: str, body: LotTemplateUpdate,
                          ctx: CompanyContext = Depends(require_super_admin),
                          session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, template_id, ctx)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    for f in _FK_FIELDS:
        if f in patch:
            patch[f] = optional_uuid(patch[f])
    for k, v in patch.items():
        setattr(row, k, v)
    row.updatedAt = utcnow()
    await session.flush()
    return _to_template(row)


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: str, ctx: CompanyContext = Depends(require_super_admin),
                          session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, template_id, ctx)
    await session.delete(row)
    await session.flush()
