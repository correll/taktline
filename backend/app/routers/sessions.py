from fastapi import APIRouter, HTTPException, Depends
import bisect
from datetime import timedelta, timezone
from typing import List, Optional
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, require_uuid, parse_uuid
from ..db.tables import (
    WorkSession as SessionRow, Station as StationRow, Card as CardRow,
    CardEvent as CardEventRow, GlobalSettings as GlobalSettingsRow, Route as RouteRow,
)
from ..deps.auth import CompanyContext, get_active_company
from ..models.session import (WorkSession, SessionCreate, SessionEnd, SessionPause,
                              Stoppage, StoppageCreate)
from ..db.tables import Stoppage as StoppageRow
from ..core import work
from ..core.flow import average_wip
from ..models.common import utcnow
from ..core.schedule import Schedule, default_work_hours, open_intervals, open_seconds, shift_starts
from ..core.entitlements import works_read_only


async def _work_schedule(session, company_id):
    """(schedule, timezone) for the company — for utilisation's open-time denominator."""
    gs = (await session.execute(
        select(GlobalSettingsRow).where(GlobalSettingsRow.companyId == company_id)
    )).scalars().first()
    grid = gs.workHours if (gs and gs.workHours) else default_work_hours()
    return Schedule(grid, (gs.breaks if gs else None) or []), (gs.timezone if gs else "UTC")


def crew_open_seconds(sessions, start, end, schedule, tzname) -> float:
    """Open seconds in [start, end] weighted by how many operators were at the
    station at once, and at least one.

    `sessions`: (startedAt, endedAt, operatorId) at one station. Working time
    adds up across operators — two people at one bench for an hour worked two
    hours — so the time it is measured against must count them too, or a
    station worked by a crew reads 100% busy all day and cannot be told from
    its neighbours. The crew is read from the record, since each operator
    signs in on their own device: within each stretch between the plant's
    openings, an operator counts as present from their first Start to their
    last Stop there, idle gaps included. Shifts handed over at one bench
    (Ann until two, Bob after) count one operator, not two, and a station
    worked by one person at a time is measured exactly as before.
    """
    if not start or not end or end <= start:
        return 0.0
    opens = open_intervals(start, end, schedule, tzname)
    if not opens:
        return 0.0
    cum = [0.0]
    for x, y in opens:
        cum.append(cum[-1] + (y - x).total_seconds())
    froms = [x for x, _ in opens]

    def open_upto(t):                       # open seconds in [start, t]
        k = bisect.bisect_right(froms, t) - 1
        if k < 0:
            return 0.0
        x, y = opens[k]
        return cum[k] + (min(t, y) - x).total_seconds()

    bounds = [start] + [o for o in shift_starts(start, end, schedule, tzname) if start < o < end] + [end]
    spans: list = [{} for _ in bounds[1:]]   # per stretch: operator -> (first Start, last Stop)
    for s0, s1, op in sessions:
        if s0 is None or s1 is None or s1 <= start or s0 >= end:
            continue
        i0 = max(0, bisect.bisect_right(bounds, s0) - 1)
        i1 = min(len(spans) - 1, bisect.bisect_left(bounds, s1) - 1)
        for k in range(i0, i1 + 1):
            lo, hi = max(s0, bounds[k]), min(s1, bounds[k + 1])
            cur = spans[k].get(op)
            spans[k][op] = (min(cur[0], lo), max(cur[1], hi)) if cur else (lo, hi)
    total = 0.0
    for (a, b), span in zip(zip(bounds, bounds[1:]), spans):
        steps = sorted([(lo, 1) for lo, _ in span.values()] + [(hi, -1) for _, hi in span.values()])
        t, n = a, 0
        for at, d in steps + [(b, 0)]:
            total += (open_upto(at) - open_upto(t)) * max(1, n)
            t, n = at, n + d
    return total


def _oee(total_working: float, start, end, schedule, tzname, crew_seconds: float = 0.0) -> Optional[float]:
    """Working time ÷ the crew's open work time in [start, end]
    (`crew_open_seconds`); falls back to open time, then to raw elapsed time,
    when the record or the schedule leaves nothing to divide by."""
    if not start or not end:
        return None
    denom = crew_seconds or open_seconds(start, end, schedule, tzname)
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
        pausedSec=r.pausedSec or 0.0,
        pausedAt=r.pausedAt,
        pauseReason=r.pauseReason,
        closedBy=r.closedBy,
    )


def _to_stoppage(r: StoppageRow) -> Stoppage:
    return Stoppage(_id=str(r.id), stationId=str(r.stationId),
                    sessionId=str(r.sessionId) if r.sessionId else None,
                    operatorId=r.operatorId, reason=r.reason, startedAt=r.startedAt,
                    endedAt=r.endedAt, durationSec=r.durationSec)


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
        await work.close(session, existing, utcnow(), "next_start")

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
@works_read_only   # An operator must be able to close a session they already
                   # opened. Refusing leaves `endedAt IS NULL` rows that corrupt
                   # the cycle-time and utilisation numbers we are still showing them.
async def end_session(session_id: str, body: SessionEnd,
                      ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, session_id, ctx)
    if row.endedAt is not None:
        raise HTTPException(400, "Session already closed")
    await work.close(session, row, utcnow(), "operator", quantity=body.quantity)
    return _to_session(row)


@router.post("/{session_id}/pause", response_model=WorkSession)
@works_read_only
async def pause_session(session_id: str, body: SessionPause,
                        ctx: CompanyContext = Depends(get_active_company),
                        session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Stop the clock without ending the work: the station broke down, is being
    changed over, or is waiting for material. The pause becomes a stoppage, and
    the session's work time excludes it."""
    row = await _get_owned(session, session_id, ctx)
    if row.endedAt is not None:
        raise HTTPException(400, "Session already closed")
    await work.pause(session, row, body.reason, utcnow())
    return _to_session(row)


@router.post("/{session_id}/resume", response_model=WorkSession)
@works_read_only
async def resume_session(session_id: str, ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, session_id, ctx)
    if row.endedAt is not None:
        raise HTTPException(400, "Session already closed")
    await work.resume(session, row, utcnow())
    return _to_session(row)


# ─── Stoppages without a session ─────────────────────────────────────────────

stoppages_router = APIRouter(prefix="/stoppages", tags=["sessions"])


@stoppages_router.get("/", response_model=List[Stoppage])
async def list_stoppages(stationId: Optional[str] = None, open_only: bool = False,
                         ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    stmt = select(StoppageRow).where(StoppageRow.companyId == ctx.company_id)
    if stationId:
        sid = parse_uuid(stationId)
        if sid is None:
            return []
        stmt = stmt.where(StoppageRow.stationId == sid)
    if open_only:
        stmt = stmt.where(StoppageRow.endedAt.is_(None))
    rows = (await session.execute(stmt.order_by(StoppageRow.startedAt.desc()).limit(200))).scalars().all()
    return [_to_stoppage(r) for r in rows]


@stoppages_router.post("/", response_model=Stoppage, status_code=201)
async def start_stoppage(body: StoppageCreate, ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """A station stopped while nobody was working a lot on it."""
    station_uuid = require_uuid(body.stationId, "Station not found")
    station = await session.get(StationRow, station_uuid)
    if station is None or station.companyId != ctx.company_id:
        raise HTTPException(404, "Station not found")
    row = StoppageRow(companyId=ctx.company_id, stationId=station_uuid,
                      operatorId=body.operatorId, reason=body.reason, startedAt=utcnow())
    session.add(row)
    await session.flush()
    return _to_stoppage(row)


@stoppages_router.post("/{stoppage_id}/end", response_model=Stoppage)
@works_read_only
async def end_stoppage(stoppage_id: str, ctx: CompanyContext = Depends(get_active_company),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await session.get(StoppageRow, require_uuid(stoppage_id, "Stoppage not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Stoppage not found")
    if row.sessionId is not None:
        raise HTTPException(400, "This stop belongs to a paused session: resume the session")
    if row.endedAt is None:
        now = utcnow()
        row.endedAt = now
        row.durationSec = max(0.0, (now - row.startedAt).total_seconds())
        await session.flush()
    return _to_stoppage(row)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, session_id, ctx)
    await session.delete(row)
    await session.flush()


async def _warehouse_ids(session, company_id) -> set:
    """Locations where nothing is *worked on*, so utilisation and cycle time
    would be meaningless: storage (finished goods rest there by design, and
    its utilisation would measure shelf time) and any location bound to an
    integration partner, which is the boundary of the business rather than a
    place someone stands.

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


async def _line_cycle_times(session, company_id, schedule, tzname,
                            since=None, until=None) -> dict:
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
    if until is None:
        until = utcnow()
    if since is None:
        since = until - timedelta(days=_LINE_CYCLE_LOOKBACK_DAYS)
    now = until
    # A departure is any event that carries a fromStation: a plain move, the
    # 'created' events a split or an un-split records per branch — pieces
    # leaving a teardown ARE departures, and in a remanufacturing shop they are
    # the ones that matter most — and a **handoff**, which is how finished
    # goods leave a make-to-order line. Without that last one the shipping
    # station reported no exit rate at all, which is the one station you most
    # want it for. (Events without a fromStation are excluded by the filter
    # below: a release and a merge are births, and a plain deletion is scrap,
    # not a departure — only the handoff records a station to leave from.)
    rows = (await session.execute(
        select(CardEventRow.fromStation, CardEventRow.timestamp, CardEventRow.quantity)
        .where(CardEventRow.companyId == company_id,
               CardEventRow.type.in_(("moved", "created", "deleted")),
               CardEventRow.fromStation.isnot(None),
               CardEventRow.timestamp >= since,
               CardEventRow.timestamp <= until)
        .order_by(CardEventRow.timestamp.asc())
    )).all()
    if not rows:
        return {}

    opens = shift_starts(since, now, schedule, tzname)

    # When each station first had anything to do with a lot — arrivals as well
    # as departures. A shift opening earlier than that cannot be delay this
    # station is answerable for: on a line's first day it is time before the
    # line existed, and charging it reported thousands of seconds per piece
    # while pieces were visibly leaving every minute. Stations with older
    # history are unaffected, so a real shift's idle morning is still counted.
    first_activity: dict[str, object] = {}
    for col in (CardEventRow.fromStation, CardEventRow.toStation):
        for station, first_ts in (await session.execute(
            select(col, func.min(CardEventRow.timestamp))
            .where(CardEventRow.companyId == company_id, col.isnot(None),
                   CardEventRow.timestamp >= since, CardEventRow.timestamp <= until)
            .group_by(col)
        )).all():
            key = str(station)
            if key not in first_activity or first_ts < first_activity[key]:
                first_activity[key] = first_ts

    per_station: dict[str, list] = {}
    for from_station, ts, qty in rows:
        if ts is None:
            continue
        per_station.setdefault(str(from_station), []).append((ts, max(1, qty or 1)))

    out: dict[str, float] = {}
    for station_id, departures in per_station.items():
        floor = first_activity.get(station_id, departures[0][0])
        lct = line_cycle_from_departures(departures, opens, floor)
        if lct is not None:
            out[station_id] = lct
    return out


async def _line_cycle_times_by_process(session, company_id, schedule, tzname,
                                       since=None, until=None) -> dict:
    """Line cycle time per (station, process).

    A station shared by two value streams leaves twice as often as either
    stream sees: its per-piece interval over all departures is not the pace of
    either line. Compared with a station only one stream uses, it made the
    single-stream station look like the constraint of a line where it was not.
    Each departure is attributed to the process whose route it took.
    """
    if until is None:
        until = utcnow()
    if since is None:
        since = until - timedelta(days=_LINE_CYCLE_LOOKBACK_DAYS)
    routes = (await session.execute(
        select(RouteRow.load, RouteRow.unload, RouteRow.processId)
        .where(RouteRow.companyId == company_id))).all()
    by_pair: dict = {}
    by_from: dict = {}
    for a, b, pid in routes:
        by_pair.setdefault((str(a), str(b)), set()).add(str(pid))
        by_from.setdefault(str(a), set()).add(str(pid))
    rows = (await session.execute(
        select(CardEventRow.fromStation, CardEventRow.toStation, CardEventRow.timestamp,
               CardEventRow.quantity)
        .where(CardEventRow.companyId == company_id,
               CardEventRow.type.in_(("moved", "created", "deleted")),
               CardEventRow.fromStation.isnot(None),
               CardEventRow.timestamp >= since, CardEventRow.timestamp <= until)
        .order_by(CardEventRow.timestamp.asc()))).all()
    if not rows:
        return {}
    opens = shift_starts(since, until, schedule, tzname)
    first: dict = {}
    per: dict = {}
    for frm, to, ts, qty in rows:
        frm = str(frm)
        first.setdefault(frm, ts)
        pids = by_pair.get((frm, str(to))) if to else None
        if not pids:
            pids = by_from.get(frm, set())
        if len(pids) != 1:
            continue
        per.setdefault((frm, next(iter(pids))), []).append((ts, max(1, qty or 1)))
    out = {}
    for key, deps in per.items():
        lct = line_cycle_from_departures(deps, opens, first.get(key[0], deps[0][0]))
        if lct is not None:
            out[key] = lct
    return out


def line_cycle_from_departures(departures, opens, floor) -> Optional[float]:
    """Seconds per piece between one station's departures (the pure core of
    `_line_cycle_times`, kept separate so it can be tested without a database).

    `departures`: (timestamp, pieces), ascending. `opens`: shift openings,
    ascending. `floor`: the station's first activity; no opening before it is
    used as an anchor.
    """
    # Lots that leave at the same instant are ONE departure of all their
    # pieces. Kept apart, the second lot's interval was zero, was skipped, and
    # its pieces vanished from the rate: a truck taking two lots read as half
    # the throughput it carried.
    merged: list = []
    for ts, qty in departures:
        if merged and merged[-1][0] == ts:
            merged[-1] = (ts, merged[-1][1] + qty)
        else:
            merged.append((ts, qty))
    station_opens = [o for o in opens if o >= floor]
    intervals: list[float] = []
    anchor = None
    oi = 0
    for ts, qty in merged:
        # Re-anchor to the most recent shift opening at or before this
        # departure: work that could not have been done is not delay.
        while oi < len(station_opens) and station_opens[oi] <= ts:
            if anchor is None or station_opens[oi] > anchor:
                anchor = station_opens[oi]
            oi += 1
        if anchor is not None and ts > anchor:
            intervals.append((ts - anchor).total_seconds() / qty)
        # The departure starts the clock for whatever leaves next.
        anchor = ts
    return sum(intervals) / len(intervals) if intervals else None


# ─── All-stations utilisation / cycle-time summary ───────────────────────────

# Trend windows the Statistics view offers. A trend is this window against the
# one immediately before it, which is the only comparison that answers "is it
# getting better or worse" without pretending to know a target.
_TREND_WINDOWS = {"1h": timedelta(hours=1), "1d": timedelta(days=1),
                  "1w": timedelta(weeks=1), "1m": timedelta(days=30)}


async def _station_metrics(session, company_id, schedule, tzname, since, until) -> dict:
    """cycle time, line cycle time, utilisation (`oee`), stoppages and average WIP per station
    over one window.

    Windowed on the *session* rather than pre-aggregated, so the same code
    answers both halves of a trend and the two halves cannot drift apart.
    """
    rows = (await session.execute(
        select(
            SessionRow.stationId,
            SessionRow.closedBy,
            func.count().label("sessionCount"),
            func.coalesce(func.sum(SessionRow.quantity), 0).label("totalUnits"),
            func.coalesce(func.sum(SessionRow.durationSec), 0.0).label("totalWorking"),
            func.min(SessionRow.startedAt).label("firstStart"),
            func.max(SessionRow.endedAt).label("lastEnd"),
        )
        .where(SessionRow.companyId == company_id, SessionRow.endedAt.isnot(None),
               SessionRow.endedAt >= since, SessionRow.endedAt <= until)
        .group_by(SessionRow.stationId, SessionRow.closedBy)
    )).all()
    crew_rows: dict = {}
    for sid_, a_, b_, op_ in (await session.execute(
        select(SessionRow.stationId, SessionRow.startedAt, SessionRow.endedAt, SessionRow.operatorId)
        .where(SessionRow.companyId == company_id, SessionRow.endedAt.isnot(None),
               SessionRow.endedAt >= since, SessionRow.endedAt <= until)
    )).all():
        crew_rows.setdefault(str(sid_), []).append((a_, b_, op_))
    # Stoppages count in OPEN time: a changeover begun just before the shift
    # ends and closed the next morning took minutes of the plant's time, not
    # the night it spans on the wall clock.
    stop_rows = (await session.execute(
        select(StoppageRow.stationId, StoppageRow.reason, StoppageRow.startedAt,
               StoppageRow.endedAt)
        .where(StoppageRow.companyId == company_id, StoppageRow.endedAt.isnot(None),
               StoppageRow.endedAt >= since, StoppageRow.endedAt <= until)
    )).all()
    agg: dict = {}
    for sid_, reason_, a_, b_ in stop_rows:
        secs = open_seconds(a_, b_, schedule, tzname)
        cur = agg.get((sid_, reason_), (0.0, 0))
        agg[(sid_, reason_)] = (cur[0] + secs, cur[1] + 1)
    stops = [(k[0], k[1], v[0], v[1]) for k, v in agg.items()]
    line_cycles = await _line_cycle_times(session, company_id, schedule, tzname,
                                          since=since, until=until)
    warehouses = await _warehouse_ids(session, company_id)
    # Averaged over at most the departure look-back: long enough to cover a
    # line's weekly rhythm, short enough that the statistics view (refreshed
    # every few seconds) never walks a year of history.
    wip_avg = await average_wip(session, company_id,
                                max(since, until - timedelta(days=_LINE_CYCLE_LOOKBACK_DAYS)),
                                until, schedule, tzname)

    per: dict = {}
    for d in rows:
        a = per.setdefault(str(d.stationId), {"id": d.stationId, "all": [0, 0, 0.0],
                                              "measured": [0, 0, 0.0], "stopped": [0, 0, 0.0],
                                              "first": d.firstStart, "last": d.lastEnd})
        a["first"] = min(a["first"], d.firstStart) if a["first"] else d.firstStart
        a["last"] = max(a["last"], d.lastEnd) if a["last"] else d.lastEnd
        keys = ("all",)
        if d.closedBy != "next_start":
            keys += ("measured",)
        if d.closedBy in (None, "operator"):
            keys += ("stopped",)
        for key in keys:
            a[key][0] += d.sessionCount
            a[key][1] += d.totalUnits or 0
            a[key][2] += d.totalWorking or 0.0
    stop_by: dict = {}
    for sid, reason, secs, n in stops:
        b = stop_by.setdefault(str(sid), {})
        b[reason] = (b.get(reason, (0.0, 0))[0] + (secs or 0.0), b.get(reason, (0.0, 0))[1] + n)

    out: dict = {}
    for sid, a in per.items():
        n_all, units_all, working_all = a["all"]
        n_m, units_m, working_m = a["measured"]
        # A session closed by the operator's *next* Start was never stopped:
        # its end is when they came back, not when the work ended. Cycle time
        # is read from the sessions that were actually stopped (by the
        # operator, or by the lot leaving), as long as there are enough of
        # them to read; a station where nobody ever presses Stop falls back to
        # everything rather than to nothing.
        # A timer the lot's departure closed is better than one left running
        # until the next Start, but it still ran on while the lot waited to be
        # moved: an upper bound, not a reading. Timers the operator stopped
        # come first; the others fill in only where there are too few.
        n_s, units_s, working_s = a["stopped"]
        if n_s >= 3:
            n_m, units_m, working_m = n_s, units_s, working_s
        units, working = (units_m, working_m) if n_m >= 3 else (units_all, working_all)
        # The same holds for how long the station worked, which load and
        # uptime divide by: a timer that ran on until the next Start would
        # count a night as work. The units it carried are charged at the pace
        # of the stopped timers instead.
        busy = (working_m + (units_all - units_m) * working_m / units_m
                if n_m >= 3 and units_m > 0 else working_all)
        st = stop_by.get(sid, {})
        down = st.get("breakdown", (0.0, 0))
        co = st.get("changeover", (0.0, 0))
        other = (st.get("material", (0.0, 0))[0] + st.get("other", (0.0, 0))[0])
        out[sid] = {
            "stationId": sid,
            "sessionCount": n_all,
            "totalUnits": units_all,
            "totalWorkingSec": busy,
            "timerSec": working_all,
            "cycleTimeSec": (working / units) if units > 0 else None,
            "lineCycleTimeSec": line_cycles.get(sid),
            "oee": None if a["id"] in warehouses
                   else _oee(busy, a["first"], a["last"], schedule, tzname,
                             crew_open_seconds(crew_rows.get(sid, []), a["first"], a["last"],
                                               schedule, tzname)),
            "isWarehouse": a["id"] in warehouses,
            "unstoppedSessions": n_all - a["stopped"][0],
            "downtimeSec": down[0], "breakdowns": down[1],
            "changeoverSec": co[0], "changeovers": co[1],
            "otherStopSec": other,
            # Uptime as the data box means it: of the time the station was
            # meant to be working, the share it was not broken down.
            "uptime": (busy / (busy + down[0])) if (busy + down[0]) > 0 else None,
            "wipAvg": wip_avg.get(sid),
        }
    # A station can have a measurable exit rate and no work sessions at all —
    # nobody runs a timer at a shipping bench, and an automated cell may never
    # have one. Listing only stations with sessions dropped them from the
    # statistics table entirely, which reads as "nothing happens here" for a
    # station that is in fact shipping every order. Line cycle time is built
    # from departures, not sessions, so it stands on its own.
    for sid, line_cycle in line_cycles.items():
        if sid in out:
            continue
        out[sid] = {
            "stationId": sid, "sessionCount": 0, "totalUnits": 0, "totalWorkingSec": 0.0,
            "cycleTimeSec": None, "lineCycleTimeSec": line_cycle, "oee": None,
            "isWarehouse": parse_uuid(sid) in warehouses,
            "unstoppedSessions": 0, "downtimeSec": 0.0, "breakdowns": 0,
            "changeoverSec": 0.0, "changeovers": 0, "otherStopSec": 0.0, "uptime": None,
            "wipAvg": wip_avg.get(sid),
        }
    # And a station where work only waits: no sessions, no departures in the
    # window, but units standing there. On a slow line that is the queue that
    # matters most, and leaving it out of the table hid it from the people and
    # the agents reading it.
    for sid, avg in wip_avg.items():
        if sid in out or not avg:
            continue
        out[sid] = {
            "stationId": sid, "sessionCount": 0, "totalUnits": 0, "totalWorkingSec": 0.0,
            "cycleTimeSec": None, "lineCycleTimeSec": None, "oee": None,
            "isWarehouse": parse_uuid(sid) in warehouses,
            "unstoppedSessions": 0, "downtimeSec": 0.0, "breakdowns": 0,
            "changeoverSec": 0.0, "changeovers": 0, "otherStopSec": 0.0, "uptime": None,
            "wipAvg": avg,
        }
    return out


@router.get("/stats")
async def all_station_stats(window: Optional[str] = None,
                            ctx: CompanyContext = Depends(get_active_company),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Per-station timing, optionally with a trend.

    Without `window` this is the all-time-ish view it always was (a 30-day
    departure lookback, every session). With one — 1h / 1d / 1w / 1m — each
    station also carries `previous`: the same metrics over the window
    immediately before, so a client can show which way the number is moving
    without inventing a target to compare against.
    """
    schedule, tzname = await _work_schedule(session, ctx.company_id)
    now = utcnow()

    if window is None:
        current = await _station_metrics(
            session, ctx.company_id, schedule, tzname,
            now - timedelta(days=_LINE_CYCLE_LOOKBACK_DAYS * 12), now)
        return list(current.values())

    span = _TREND_WINDOWS.get(window)
    if span is None:
        raise HTTPException(400, f"window must be one of {sorted(_TREND_WINDOWS)}")

    current = await _station_metrics(session, ctx.company_id, schedule, tzname,
                                     now - span, now)
    prior = await _station_metrics(session, ctx.company_id, schedule, tzname,
                                   now - span * 2, now - span)
    results = []
    for sid, row in current.items():
        before = prior.get(sid)
        results.append({**row, "window": window, "previous": None if before is None else {
            "cycleTimeSec": before["cycleTimeSec"],
            "lineCycleTimeSec": before["lineCycleTimeSec"],
            "oee": before["oee"],
            "totalUnits": before["totalUnits"],
        }})
    return results


# ─── Per-station utilisation and cycle time ──────────────────────────────────

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

    # The same rule as the statistics table: timers closed by the next Start
    # are not readings of the work, and their units are charged at the pace
    # of the others.
    total_units = sum(r.quantity for r in rows)
    timer_sec = sum((r.durationSec or 0) for r in rows)
    measured = [r for r in rows if r.closedBy in (None, "operator")]
    if len(measured) < 3:
        measured = [r for r in rows if r.closedBy != "next_start"]
    units_m = sum(r.quantity for r in measured)
    working_m = sum((r.durationSec or 0) for r in measured)
    if len(measured) >= 3 and units_m > 0:
        cycle_time = working_m / units_m
        total_working = working_m + (total_units - units_m) * cycle_time
    else:
        cycle_time = timer_sec / total_units if total_units > 0 else None
        total_working = timer_sec
    starts = [r.startedAt for r in rows if r.startedAt]
    ends = [r.endedAt for r in rows if r.endedAt]
    is_warehouse = sid in await _warehouse_ids(session, ctx.company_id)
    schedule, tzname = await _work_schedule(session, ctx.company_id)
    line_cycle = (await _line_cycle_times(session, ctx.company_id, schedule, tzname)).get(station_id)
    if starts and ends and not is_warehouse:
        crew = crew_open_seconds([(r.startedAt, r.endedAt, r.operatorId) for r in rows],
                                 min(starts), max(ends), schedule, tzname)
        oee = _oee(total_working, min(starts), max(ends), schedule, tzname, crew)
    else:
        oee = None   # a warehouse stores rather than runs

    return {
        "stationId": station_id, "sessionCount": len(rows), "totalUnits": total_units,
        "totalWorkingSec": total_working, "timerSec": timer_sec, "cycleTimeSec": cycle_time,
        "lineCycleTimeSec": line_cycle,
        "oee": oee,
        "isWarehouse": is_warehouse,
    }


# ─── Detail behind one number ────────────────────────────────────────────────

_MAX_SAMPLES = 3000


@router.get("/stats/{station_id}/detail")
async def station_detail(station_id: str, window: Optional[str] = None,
                         ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """The samples behind a station's numbers, for charting.

    An average hides the thing you most need to see. On a line watched today,
    a bench averaged 30 s per piece — sixteen sessions near 4 s and one 80 s
    stall. "Slow station" and "usually quick but occasionally jams" are
    different problems with different fixes, and only the distribution tells
    them apart. So this returns SAMPLES, not more aggregates, and lets the
    client draw the shape.

    * ``cycleSamples``     one point per work session: when, and seconds per piece.
                           Serves both the histogram and the run chart.
    * ``departureSamples`` one point per departure: the per-piece interval that
                           line cycle time averages.
    * ``byHour``           sessions and units by hour of the day, with the hours
                           the company says it is open — which is how work
                           happening outside the schedule becomes visible.
    """
    sid = parse_uuid(station_id)
    if sid is None:
        raise HTTPException(404, "Station not found")
    station = await session.get(StationRow, sid)
    if station is None or station.companyId != ctx.company_id:
        raise HTTPException(404, "Station not found")

    now = utcnow()
    span = _TREND_WINDOWS.get(window) if window else None
    since = now - (span or timedelta(days=_LINE_CYCLE_LOOKBACK_DAYS))
    schedule, tzname = await _work_schedule(session, ctx.company_id)

    rows = (await session.execute(
        select(SessionRow.startedAt, SessionRow.durationSec, SessionRow.quantity)
        .where(SessionRow.companyId == ctx.company_id, SessionRow.stationId == sid,
               SessionRow.endedAt.isnot(None),
               SessionRow.endedAt >= since, SessionRow.endedAt <= now)
        .order_by(SessionRow.startedAt.asc()).limit(_MAX_SAMPLES)
    )).all()

    cycle_samples = [
        {"t": started.isoformat(), "secPerPiece": dur / qty, "units": qty}
        for started, dur, qty in rows if dur and qty and qty > 0
    ]

    # Departures, as the line-cycle walk sees them, but kept as individual
    # intervals rather than averaged — the spread is the point.
    departures = await _line_cycle_samples(session, ctx.company_id, sid, schedule,
                                           tzname, since, now)

    # Activity by hour of the day, in the company's own timezone, against the
    # hours it says it is open. Work outside those hours is the signal.
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(tzname)
    except Exception:
        tz = timezone.utc
    by_hour = [{"hour": h, "sessions": 0, "units": 0} for h in range(24)]
    for started, _dur, qty in rows:
        h = started.astimezone(tz).hour
        by_hour[h]["sessions"] += 1
        by_hour[h]["units"] += qty or 0
    # An hour counts as open if any scheduled day opens in it — the histogram
    # aggregates across days, so a per-weekday mask cannot be drawn on it.
    open_hours = sorted({h for day in schedule for h, mask in enumerate(day) if mask})

    return {
        "stationId": station_id,
        "stationName": station.name,
        "window": window,
        "cycleSamples": cycle_samples,
        "departureSamples": departures,
        "byHour": by_hour,
        "openHours": open_hours,
        "timezone": tzname,
    }


async def _line_cycle_samples(session, company_id, station_uuid, schedule, tzname,
                              since, until) -> list:
    """The individual per-piece departure intervals — the same walk
    _line_cycle_times averages, stopping one step earlier."""
    rows = (await session.execute(
        select(CardEventRow.timestamp, CardEventRow.quantity)
        .where(CardEventRow.companyId == company_id,
               CardEventRow.type.in_(("moved", "created", "deleted")),
               CardEventRow.fromStation == str(station_uuid),
               CardEventRow.timestamp >= since, CardEventRow.timestamp <= until)
        .order_by(CardEventRow.timestamp.asc()).limit(_MAX_SAMPLES)
    )).all()
    if not rows:
        return []
    opens = [o for o in shift_starts(since, until, schedule, tzname) if o >= rows[0][0]]
    out, anchor, oi = [], None, 0
    for ts, qty in rows:
        qty = max(1, qty or 1)
        while oi < len(opens) and opens[oi] <= ts:
            if anchor is None or opens[oi] > anchor:
                anchor = opens[oi]
            oi += 1
        if anchor is not None and ts > anchor:
            out.append({"t": ts.isoformat(),
                        "secPerPiece": (ts - anchor).total_seconds() / qty})
        anchor = ts
    return out
