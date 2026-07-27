from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import get_session, require_uuid, parse_uuid
from ..db.tables import (
    WorkSession as SessionRow, Station as StationRow, Card as CardRow,
    GlobalSettings as GlobalSettingsRow,
)
from ..deps.auth import CompanyContext, get_active_company
from ..models.session import WorkSession, SessionCreate, SessionEnd
from ..models.common import utcnow
from ..core.schedule import default_work_hours, open_seconds


async def _work_schedule(session, company_id):
    """(schedule, timezone) for the company — for OEE's open-time denominator."""
    gs = (await session.execute(
        select(GlobalSettingsRow).where(GlobalSettingsRow.companyId == company_id)
    )).scalars().first()
    schedule = gs.workHours if (gs and gs.workHours) else default_work_hours()
    return schedule, (gs.timezone if gs else "UTC")


def _oee(total_working: float, start, end, schedule, tzname) -> Optional[float]:
    """Working time ÷ open work time in [start, end]; falls back to raw elapsed
    time when the schedule leaves no open hours in the window."""
    if not start or not end:
        return None
    denom = open_seconds(start, end, schedule, tzname)
    if denom <= 0:
        denom = (end - start).total_seconds()
    return min(1.0, total_working / denom) if denom > 0 else None

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _to_session(r: SessionRow) -> WorkSession:
    return WorkSession(
        _id=str(r.id),
        stationId=str(r.stationId),
        cardId=str(r.cardId) if r.cardId else None,
        operatorId=r.operatorId,
        quantity=r.quantity,
        startedAt=r.startedAt,
        endedAt=r.endedAt,
        durationSec=r.durationSec,
    )


async def _get_owned(session: AsyncSession, session_id: str, ctx: CompanyContext) -> SessionRow:
    row = await session.get(SessionRow, require_uuid(session_id, "Session not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Session not found")
    return row


@router.get("/", response_model=List[WorkSession])
async def list_sessions(stationId: Optional[str] = None, open_only: bool = False,
                        ctx: CompanyContext = Depends(get_active_company),
                        session: AsyncSession = Depends(get_session)):
    stmt = select(SessionRow).where(SessionRow.companyId == ctx.company_id)
    if stationId:
        sid = parse_uuid(stationId)
        if sid is None:
            return []
        stmt = stmt.where(SessionRow.stationId == sid)
    if open_only:
        stmt = stmt.where(SessionRow.endedAt.is_(None))
    stmt = stmt.order_by(SessionRow.startedAt.desc()).limit(200)
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_session(r) for r in rows]


@router.post("/", response_model=WorkSession, status_code=201)
async def start_session(body: SessionCreate, ctx: CompanyContext = Depends(get_active_company),
                        session: AsyncSession = Depends(get_session)):
    station_uuid = require_uuid(body.stationId, "Station not found")
    station = await session.get(StationRow, station_uuid)
    if station is None or station.companyId != ctx.company_id:
        raise HTTPException(404, "Station not found")

    card_uuid = parse_uuid(body.cardId) if body.cardId else None
    if card_uuid is not None:
        card = await session.get(CardRow, card_uuid)
        if card is None or card.companyId != ctx.company_id:
            raise HTTPException(404, "Card not found")

    # Allow at most one open session per station+operator: auto-close a dangling one.
    existing = (await session.execute(
        select(SessionRow).where(
            SessionRow.companyId == ctx.company_id,
            SessionRow.stationId == station_uuid,
            SessionRow.operatorId == body.operatorId,
            SessionRow.endedAt.is_(None),
        )
    )).scalars().first()
    if existing:
        now = utcnow()
        existing.endedAt = now
        existing.durationSec = (now - existing.startedAt).total_seconds() if existing.startedAt else None

    row = SessionRow(
        companyId=ctx.company_id,
        stationId=station_uuid,
        cardId=card_uuid,
        operatorId=body.operatorId,
        quantity=body.quantity,
        startedAt=utcnow(),
        endedAt=None,
        durationSec=None,
    )
    session.add(row)
    await session.flush()
    return _to_session(row)


@router.get("/open", response_model=List[WorkSession])
async def get_open_sessions(ctx: CompanyContext = Depends(get_active_company),
                            session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(SessionRow).where(
            SessionRow.companyId == ctx.company_id, SessionRow.endedAt.is_(None)
        )
    )).scalars().all()
    return [_to_session(r) for r in rows]


@router.post("/{session_id}/end", response_model=WorkSession)
async def end_session(session_id: str, body: SessionEnd,
                      ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, session_id, ctx)
    if row.endedAt is not None:
        raise HTTPException(400, "Session already closed")
    ended_at = utcnow()
    row.endedAt = ended_at
    row.durationSec = (ended_at - row.startedAt).total_seconds()
    if body.quantity is not None:
        row.quantity = body.quantity
    await session.flush()
    return _to_session(row)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, session_id, ctx)
    await session.delete(row)
    await session.flush()


# ─── All-stations OEE / takt-time summary ────────────────────────────────────

@router.get("/stats")
async def all_station_stats(ctx: CompanyContext = Depends(get_active_company),
                            session: AsyncSession = Depends(get_session)):
    stmt = (
        select(
            SessionRow.stationId,
            func.count().label("sessionCount"),
            func.coalesce(func.sum(SessionRow.quantity), 0).label("totalUnits"),
            func.coalesce(func.sum(SessionRow.durationSec), 0.0).label("totalWorking"),
            func.min(SessionRow.startedAt).label("firstStart"),
            func.max(SessionRow.endedAt).label("lastEnd"),
        )
        .where(SessionRow.companyId == ctx.company_id, SessionRow.endedAt.isnot(None))
        .group_by(SessionRow.stationId)
    )
    rows = (await session.execute(stmt)).all()
    schedule, tzname = await _work_schedule(session, ctx.company_id)
    results = []
    for d in rows:
        total_units = d.totalUnits or 0
        total_working = d.totalWorking or 0.0
        takt = total_working / total_units if total_units > 0 else None
        oee = _oee(total_working, d.firstStart, d.lastEnd, schedule, tzname)
        results.append({
            "stationId": str(d.stationId),
            "sessionCount": d.sessionCount,
            "totalUnits": total_units,
            "totalWorkingSec": total_working,
            "taktTimeSec": takt,
            "oee": oee,
        })
    return results


# ─── Per-station OEE and takt-time ───────────────────────────────────────────

@router.get("/stats/{station_id}")
async def station_session_stats(station_id: str, ctx: CompanyContext = Depends(get_active_company),
                                session: AsyncSession = Depends(get_session)):
    empty = {
        "stationId": station_id, "sessionCount": 0, "totalUnits": 0,
        "totalWorkingSec": 0.0, "taktTimeSec": None, "oee": None,
    }
    sid = parse_uuid(station_id)
    if sid is None:
        return empty
    rows = (await session.execute(
        select(SessionRow).where(
            SessionRow.companyId == ctx.company_id,
            SessionRow.stationId == sid,
            SessionRow.endedAt.isnot(None),
        )
    )).scalars().all()
    if not rows:
        return empty

    total_units = sum(r.quantity for r in rows)
    total_working = sum((r.durationSec or 0) for r in rows)
    takt_time = total_working / total_units if total_units > 0 else None
    starts = [r.startedAt for r in rows if r.startedAt]
    ends = [r.endedAt for r in rows if r.endedAt]
    if starts and ends:
        schedule, tzname = await _work_schedule(session, ctx.company_id)
        oee = _oee(total_working, min(starts), max(ends), schedule, tzname)
    else:
        oee = None

    return {
        "stationId": station_id, "sessionCount": len(rows), "totalUnits": total_units,
        "totalWorkingSec": total_working, "taktTimeSec": takt_time, "oee": oee,
    }
