"""The life of a work session: pause, resume, close — and the rule that a lot
cannot still be worked at a station it has left.

Shared by the sessions router (operator actions) and the cards router (a move
is the strongest evidence there is that work on a lot has ended), so the two
cannot disagree about what a session's work time is.

Work time is elapsed time minus stoppages. A timer that runs through a
breakdown charges the repair to cycle time and records nowhere that the
station was down; a Pause keeps the two apart, and the stoppage it opens is
what uptime and changeover time are computed from.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from ..db.tables import Stoppage as StoppageRow, WorkSession as SessionRow

REASONS = ("breakdown", "changeover", "material", "other")


async def _open_stoppage(session, row: SessionRow):
    return (await session.execute(
        select(StoppageRow).where(StoppageRow.sessionId == row.id,
                                  StoppageRow.endedAt.is_(None))
    )).scalars().first()


async def pause(session, row: SessionRow, reason: str, now: datetime) -> None:
    """Stop the clock on a running session and open a stoppage. Idempotent:
    pausing a paused session changes nothing (a double tap is not two
    breakdowns)."""
    if row.endedAt is not None or row.pausedAt is not None:
        return
    row.pausedAt = now
    row.pauseReason = reason
    session.add(StoppageRow(companyId=row.companyId, stationId=row.stationId,
                            sessionId=row.id, operatorId=row.operatorId,
                            reason=reason, startedAt=now))
    await session.flush()


async def resume(session, row: SessionRow, now: datetime) -> None:
    """Restart the clock and close the stoppage the pause opened."""
    if row.pausedAt is None:
        return
    gap = max(0.0, (now - row.pausedAt).total_seconds())
    row.pausedSec = (row.pausedSec or 0.0) + gap
    row.pausedAt = None
    row.pauseReason = None
    st = await _open_stoppage(session, row)
    if st is not None:
        st.endedAt = now
        st.durationSec = max(0.0, (now - st.startedAt).total_seconds())
    await session.flush()


async def close(session, row: SessionRow, now: datetime, closed_by: str,
                quantity: int | None = None) -> None:
    """End a session: a pause still running ends with it, and the recorded
    duration is work only."""
    if row.endedAt is not None:
        return
    await resume(session, row, now)
    row.endedAt = now
    elapsed = (now - row.startedAt).total_seconds() if row.startedAt else 0.0
    row.durationSec = max(0.0, elapsed - (row.pausedSec or 0.0))
    row.closedBy = closed_by
    if quantity is not None:
        row.quantity = quantity
    await session.flush()


async def close_sessions_left_behind(session, company_id, card_uuid, station_uuid,
                                     units_left: int, now: datetime) -> int:
    """A lot that has left a station cannot still be worked there.

    An operator who forgets to press Stop leaves the timer running until their
    next Start, which may be after the next lot, a shift change or the night;
    the whole gap is charged to cycle time. Moving the lot is something the
    work cannot proceed without, so when the last of a lot's units leave a
    station, any session still open on that lot there ends at the move. The
    move is the latest moment the work can have ended, which makes it a far
    better reading than the next Start, and it is marked as not the
    operator's, so a reader of the data can tell. Called before the lot is
    deleted, while its sessions still point at it.
    """
    if card_uuid is None or station_uuid is None or units_left > 0:
        return 0
    rows = (await session.execute(
        select(SessionRow).where(SessionRow.companyId == company_id,
                                 SessionRow.cardId == card_uuid,
                                 SessionRow.stationId == station_uuid,
                                 SessionRow.endedAt.is_(None))
    )).scalars().all()
    for r in rows:
        await close(session, r, now, "move")
    return len(rows)
