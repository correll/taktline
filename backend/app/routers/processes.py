from fastapi import APIRouter, HTTPException, Depends
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import Process as ProcessRow
from ..deps.auth import CompanyContext, ensure_sandbox_quota, get_active_company, require_super_admin
from ..models.process import Process, ProcessCreate, ProcessUpdate
from ..models.common import utcnow

router = APIRouter(prefix="/processes", tags=["processes"])


def _to_process(r: ProcessRow) -> Process:
    return Process(
        _id=str(r.id),
        name=r.name,
        routes=r.routes or [],
        mapId=r.mapId,
        description=r.description,
        createdAt=r.createdAt,
        updatedAt=r.updatedAt,
    )


async def _get_owned(session: AsyncSession, process_id: str, ctx: CompanyContext) -> ProcessRow:
    row = await session.get(ProcessRow, require_uuid(process_id, "Process not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Process not found")
    return row


@router.get("/", response_model=List[Process])
async def list_processes(ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(ProcessRow).where(ProcessRow.companyId == ctx.company_id)
    )).scalars().all()
    return [_to_process(r) for r in rows]


@router.post("/", response_model=Process, status_code=201)
async def create_process(body: ProcessCreate, ctx: CompanyContext = Depends(require_super_admin),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    await ensure_sandbox_quota(session, ctx, ProcessRow)
    row = ProcessRow(**body.model_dump(), companyId=ctx.company_id)
    session.add(row)
    await session.flush()
    return _to_process(row)


@router.get("/{process_id}", response_model=Process)
async def get_process(process_id: str, ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    return _to_process(await _get_owned(session, process_id, ctx))


@router.put("/{process_id}", response_model=Process)
async def update_process(process_id: str, body: ProcessUpdate,
                         ctx: CompanyContext = Depends(require_super_admin),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, process_id, ctx)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    for k, v in patch.items():
        setattr(row, k, v)
    row.updatedAt = utcnow()
    await session.flush()
    return _to_process(row)


@router.delete("/{process_id}", status_code=204)
async def delete_process(process_id: str, ctx: CompanyContext = Depends(require_super_admin),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, process_id, ctx)
    await session.delete(row)
    await session.flush()
