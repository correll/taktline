from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import entitlements
from ..db.connection import SESSION_SCOPE, get_session
from ..db.tables import (
    WorkSession as SessionRow,
    CardEvent as CardEventRow,
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
                    session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Delete all process/lot data for THIS company only (admins). Child-before-
    parent order; map/global settings, users, and the card_events audit log are
    left intact."""
    for table in (SessionRow, CardRow, LotTemplateRow, RouteRow, ProcessRow, StationRow):
        await session.execute(delete(table).where(table.companyId == ctx.company_id))
    # Zero stations now — tell Stripe (best-effort; the count is the price).
    await entitlements.report_station_count(session, ctx.company_id)


@router.post("/reset-statistics")
async def reset_statistics(ctx: CompanyContext = Depends(require_super_admin),
                           session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Clear the measured history, keeping the line and the lots on it.

    Everything the Statistics view computes comes from two tables: work
    sessions (cycle time, OEE) and card events (line cycle time, the moves
    chart, a lot's own history). This empties both, so a pilot's practice runs
    or a simulation stop distorting the numbers a real week is judged on.

    Deliberately NOT touched: stations, routes, processes, products, the lot
    cards currently on the floor, and production orders. Those are the line and
    the business, not the measurement — `/admin/reset` is the one that clears
    those, and conflating the two would make "clean up my test data" delete a
    customer's factory.
    """
    sessions = await session.execute(
        delete(SessionRow).where(SessionRow.companyId == ctx.company_id))
    events = await session.execute(
        delete(CardEventRow).where(CardEventRow.companyId == ctx.company_id))
    return {"workSessionsDeleted": sessions.rowcount or 0,
            "cardEventsDeleted": events.rowcount or 0}
