from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, get_or_create_singleton
from ..db.tables import GlobalSettings as GlobalSettingsRow
from ..deps.auth import CompanyContext, get_active_company, require_super_admin
from ..models.global_settings import GlobalSettings, GlobalSettingsUpdate

router = APIRouter(prefix="/global-settings", tags=["global-settings"])


def _to_model(r: GlobalSettingsRow) -> GlobalSettings:
    return GlobalSettings(_id=str(r.id), timezone=r.timezone, workHours=r.workHours or [],
                          showCycleArc=bool(r.showCycleArc))


async def _get_or_create(session: AsyncSession, company_id) -> GlobalSettingsRow:
    return await get_or_create_singleton(
        session, GlobalSettingsRow, company_id, timezone="UTC",
    )


@router.get("/", response_model=GlobalSettings)
async def get_global_settings(ctx: CompanyContext = Depends(get_active_company),
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    return _to_model(await _get_or_create(session, ctx.company_id))


@router.put("/", response_model=GlobalSettings)
async def update_global_settings(body: GlobalSettingsUpdate,
                                 ctx: CompanyContext = Depends(require_super_admin),
                                 session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_or_create(session, ctx.company_id)
    for k, v in body.model_dump().items():
        if v is not None:
            setattr(row, k, v)
    await session.flush()
    return _to_model(row)
