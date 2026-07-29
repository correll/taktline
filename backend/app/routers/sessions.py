from fastapi import APIRouter, HTTPException, Depends
from datetime import timedelta
from typing import List, Optional
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, require_uuid, parse_uuid
from ..db.tables import (
    WorkSession as SessionRow, Station as StationRow, Card as CardRow,
    CardEvent as CardEventRow, GlobalSettings as GlobalSettingsRow, Route as RouteRow,
)
from ..deps.auth import CompanyContext, get_active_company
from ..models.session import WorkSession, SessionCreate, SessionEnd
from ..models.common import utcnow
from ..core.schedule import default_work_hours, open_seconds, shift_starts


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
                        session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
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
                        session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
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
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(SessionRow).where(
            SessionRow.companyId == ctx.company_id, SessionRow.endedAt.is_(None)
        )
    )).scalars().all()
    return [_to_session(r) for r in rows]


@router.post("/{session_id}/end", response_model=WorkSession)
async def end_session(session_id: str, body: SessionEnd,
                      ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
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
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, session_id, ctx)
    await session.delete(row)
    await session.flush()


async def _warehouse_ids(session, company_id) -> set:
    """Locations where nothing is *worked on*, so OEE and cycle time would be
    meaningless: storage (finished goods rest there by design, and its OEE
    would measure shelf time) and any location bound to an integration partner,
    which is the boundary of the business rather than a place someone stands.

    Storage is now a property of the location, not a shape in the graph. It
    used to be inferred as "receives routes but sends none", which quietly
    swallowed every leaf that does real work — a final test bench, a paint
    booth, the last cell on a line — and made them invisible on the heatmap,
    which is exactly where a queue building up matters most.
    """
    rows = (await session.execute(
        select(StationRow.id).where(
            StationRow.companyId == company_id,
            or_(StationRow.isStorage.is_(True),
                StationRow.integrationProvider.isnot(None)))
    )).scalars().all()
    return set(rows)


# ─── Line cycle time ─────────────────────────────────────────────────────────

# How far back to look for departures. Long enough to be stable across a slow
# week, short enough that a year-old pilot run cannot skew today's number.
_LINE_CYCLE_LOOKBACK_DAYS = 30


async def _line_cycle_times(session, company_id, schedule, tzname) -> dict:
    """Seconds per piece between a station's departures — its actual exit rate.

    Cycle time answers "how long does the work take"; this answers "how often
    does a piece actually leave", which is the number that moves when the line
    is starved, blocked or waiting for a forklift. The gap between the two is
    the waste.

    The clock starts when work *could* have left — the start of the shift — and
    is re-anchored to each departure, so what is measured is the interval a lot
    waited before moving, not how long it sat over a weekend. Every shift
    opening resets it, which is what lets a lot finished after hours still be
    counted against the shift that follows rather than against the night.

    Divided by units: moving a lot of ten is ten pieces leaving, not one.
    """
    now = utcnow()
    since = now - timedelta(days=_LINE_CYCLE_LOOKBACK_DAYS)
    # A departure is any event that carries a fromStation: a plain move, and
    # also the 'created' events a split or an un-split records per branch —
    # pieces leaving a teardown ARE departures, and in a remanufacturing shop
    # they are the ones that matter most. (Creation events without a
    # fromStation — a release, a merge — are births, not departures, and stay
    # excluded by the isnot(None) filter.)
    rows = (await session.execute(
        select(CardEventRow.fromStation, CardEventRow.timestamp, CardEventRow.quantity)
        .where(CardEventRow.companyId == company_id,
               CardEventRow.type.in_(("moved", "created")),
               CardEventRow.fromStation.isnot(None),
               CardEventRow.timestamp >= since)
        .order_by(CardEventRow.timestamp.asc())
    )).all()
    if not rows:
        return {}

    opens = shift_starts(since, now, schedule, tzname)

    per_station: dict[str, list] = {}
    for from_station, ts, qty in rows:
        if ts is None:
            continue
        per_station.setdefault(str(from_station), []).append((ts, max(1, qty or 1)))

    out: dict[str, float] = {}
    for station_id, departures in per_station.items():
        intervals: list[float] = []
        anchor = None
        oi = 0
        for ts, qty in departures:
            # Re-anchor to the most recent shift opening at or before this
            # departure: work that could not have been done is not delay.
            while oi < len(opens) and opens[oi] <= ts:
                if anchor is None or opens[oi] > anchor:
                    anchor = opens[oi]
                oi += 1
            if anchor is not None and ts > anchor:
                intervals.append((ts - anchor).total_seconds() / qty)
            # The departure starts the clock for whatever leaves next.
            anchor = ts
        if intervals:
            out[station_id] = sum(intervals) / len(intervals)
    return out


# ─── All-stations OEE / cycle-time summary ───────────────────────────────────

@router.get("/stats")
async def all_station_stats(ctx: CompanyContext = Depends(get_active_company),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
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
    warehouses = await _warehouse_ids(session, ctx.company_id)
    line_cycles = await _line_cycle_times(session, ctx.company_id, schedule, tzname)
    results = []
    for d in rows:
        total_units = d.totalUnits or 0
        total_working = d.totalWorking or 0.0
        cycle = total_working / total_units if total_units > 0 else None
        is_warehouse = d.stationId in warehouses
        results.append({
            "stationId": str(d.stationId),
            "sessionCount": d.sessionCount,
            "totalUnits": total_units,
            "totalWorkingSec": total_working,
            "cycleTimeSec": cycle,
            "lineCycleTimeSec": line_cycles.get(str(d.stationId)),
            # A warehouse stores, it does not run — OEE would be meaningless.
            "oee": None if is_warehouse else _oee(total_working, d.firstStart, d.lastEnd,
                                                  schedule, tzname),
            "isWarehouse": is_warehouse,
        })
    return results


# ─── Per-station OEE and cycle time ──────────────────────────────────────────

@router.get("/stats/{station_id}")
async def station_session_stats(station_id: str, ctx: CompanyContext = Depends(get_active_company),
                                session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    def empty(is_warehouse: bool = False, line_cycle=None):
        return {
            "stationId": station_id, "sessionCount": 0, "totalUnits": 0,
            "totalWorkingSec": 0.0, "cycleTimeSec": None,
            "lineCycleTimeSec": line_cycle, "oee": None,
            "isWarehouse": is_warehouse,
        }
    sid = parse_uuid(station_id)
    if sid is None:
        return empty()
    rows = (await session.execute(
        select(SessionRow).where(
            SessionRow.companyId == ctx.company_id,
            SessionRow.stationId == sid,
            SessionRow.endedAt.isnot(None),
        )
    )).scalars().all()
    if not rows:
        # What a location *is* does not depend on whether anyone has worked at
        # it yet: a warehouse with no sessions is still a warehouse, and an
        # integration dock is never a work station. Reporting False here made
        # both look like ordinary stations until their first session.
        #
        # Line cycle time is measured from departures, not sessions — a
        # teardown station may ship pieces all day without anyone pressing
        # Start there — so it is computed even when no session ever ran. The
        # early return used to skip it, which read as "no exit rate" at
        # exactly the stations whose exit rate is the product.
        schedule0, tz0 = await _work_schedule(session, ctx.company_id)
        lc = (await _line_cycle_times(session, ctx.company_id, schedule0, tz0)).get(station_id)
        return empty(sid in await _warehouse_ids(session, ctx.company_id), line_cycle=lc)

    total_units = sum(r.quantity for r in rows)
    total_working = sum((r.durationSec or 0) for r in rows)
    cycle_time = total_working / total_units if total_units > 0 else None
    starts = [r.startedAt for r in rows if r.startedAt]
    ends = [r.endedAt for r in rows if r.endedAt]
    is_warehouse = sid in await _warehouse_ids(session, ctx.company_id)
    schedule, tzname = await _work_schedule(session, ctx.company_id)
    line_cycle = (await _line_cycle_times(session, ctx.company_id, schedule, tzname)).get(station_id)
    if starts and ends and not is_warehouse:
        oee = _oee(total_working, min(starts), max(ends), schedule, tzname)
    else:
        oee = None   # a warehouse stores rather than runs

    return {
        "stationId": station_id, "sessionCount": len(rows), "totalUnits": total_units,
        "totalWorkingSec": total_working, "cycleTimeSec": cycle_time,
        "lineCycleTimeSec": line_cycle,
        "oee": oee,
        "isWarehouse": is_warehouse,
    }
