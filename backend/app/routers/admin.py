from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import get_session
from ..db.tables import (
    WorkSession as SessionRow,
    Card as CardRow,
    LotTemplate as LotTemplateRow,
    Route as RouteRow,
    Process as ProcessRow,
    Station as StationRow,
)
from ..deps.auth import CompanyContext, require_super_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset", status_code=204)
async def reset_all(ctx: CompanyContext = Depends(require_super_admin),
                    session: AsyncSession = Depends(get_session)):
    """Delete all process/lot data for THIS company only (admins). Child-before-
    parent order; map/global settings, users, and the card_events audit log are
    left intact."""
    for table in (SessionRow, CardRow, LotTemplateRow, RouteRow, ProcessRow, StationRow):
        await session.execute(delete(table).where(table.companyId == ctx.company_id))
