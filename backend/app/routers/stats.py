from fastapi import APIRouter, Depends
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import get_session
from ..db.tables import Card as CardRow, CardEvent as CardEventRow
from ..deps.auth import CompanyContext, get_active_company

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview")
async def get_overview(ctx: CompanyContext = Depends(get_active_company),
                       session: AsyncSession = Depends(get_session)):
    """Aggregate stats for the dashboard: lots per station, recent moves, process throughput."""
    cards = (await session.execute(
        select(CardRow).where(CardRow.companyId == ctx.company_id)
    )).scalars().all()

    total_lots  = len(cards)
    total_units = sum(
        sum(b.get("count", 0) for b in (c.bins or {}).values())
        for c in cards
    )
    flagged_count = sum(1 for c in cards if c.flagged)

    units_per_station: dict[str, int] = {}
    lots_per_station:  dict[str, int] = {}
    for c in cards:
        for sid, b in (c.bins or {}).items():
            cnt = b.get("count", 0)
            if cnt > 0:
                units_per_station[sid] = units_per_station.get(sid, 0) + cnt
                lots_per_station[sid]  = lots_per_station.get(sid, 0) + 1

    lots_per_process: dict[str, int] = {}
    for c in cards:
        pid = str(c.processId) if c.processId else ""
        if pid:
            lots_per_process[pid] = lots_per_process.get(pid, 0) + 1

    recent_events = (await session.execute(
        select(CardEventRow)
        .where(CardEventRow.companyId == ctx.company_id, CardEventRow.type == "moved")
        .order_by(CardEventRow.timestamp.desc())
        .limit(50)
    )).scalars().all()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    hourly: dict[int, int] = {h: 0 for h in range(24)}
    for evt in recent_events:
        ts = evt.timestamp
        if ts and ts >= cutoff:
            hour_ago = int((now - ts).total_seconds() // 3600)
            if 0 <= hour_ago < 24:
                hourly[hour_ago] = hourly.get(hour_ago, 0) + 1

    return {
        "totalLots":        total_lots,
        "totalUnits":       total_units,
        "flaggedLots":      flagged_count,
        "lotsPerStation":   lots_per_station,
        "unitsPerStation":  units_per_station,
        "lotsPerProcess":   lots_per_process,
        "movesPerHour":     [{"hoursAgo": h, "moves": hourly[h]} for h in range(23, -1, -1)],
    }
