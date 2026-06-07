from fastapi import APIRouter, Depends
from ..db.connection import get_db

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview")
async def get_overview(db=Depends(get_db)):
    """Aggregate stats for the dashboard: lots per station, recent moves, process throughput."""
    cards = await db.cards.find().to_list(None)

    total_lots     = len(cards)
    total_units    = sum(
        sum(b.get("count", 0) for b in c.get("bins", {}).values())
        for c in cards
    )
    flagged_count  = sum(1 for c in cards if c.get("flagged"))

    # Units per station
    units_per_station: dict[str, int] = {}
    lots_per_station:  dict[str, int] = {}
    for c in cards:
        for sid, b in c.get("bins", {}).items():
            cnt = b.get("count", 0)
            if cnt > 0:
                units_per_station[sid] = units_per_station.get(sid, 0) + cnt
                lots_per_station[sid]  = lots_per_station.get(sid, 0) + 1

    # Lots per process
    lots_per_process: dict[str, int] = {}
    for c in cards:
        pid = c.get("processId", "")
        if pid:
            lots_per_process[pid] = lots_per_process.get(pid, 0) + 1

    # Recent move events (last 50)
    recent_events = await db.card_events.find(
        {"type": "moved"}
    ).sort("timestamp", -1).limit(50).to_list(None)

    # Moves per hour over last 24 hours
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    hourly: dict[int, int] = {h: 0 for h in range(24)}
    for evt in recent_events:
        ts = evt.get("timestamp")
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
