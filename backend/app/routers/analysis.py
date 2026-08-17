"""`GET /analysis/` — the line doctor's report.

Assembles a snapshot of the line from the database and hands it to
`core.analysis`, which is where all the judgement lives. Nothing here decides
anything; the split exists so the rules can be tested against hand-built lines
with planted faults, without a database anywhere near them.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import analysis as engine
from ..core import entitlements, line_snapshot, runout as runout_engine
from ..db.connection import SESSION_SCOPE, get_session
from ..db.tables import (
    Card as CardRow, LotTemplate as LotTemplateRow, MapSettings as MapSettingsRow,
    Process as ProcessRow, Route as RouteRow, Station as StationRow,
    WorkSession as SessionRow,
)
from ..deps.auth import CompanyContext, get_active_company
from .sessions import _station_metrics, _work_schedule

router = APIRouter(prefix="/analysis", tags=["analysis"])

# The report describes how the line is running now, not how it ran last spring.
LOOKBACK_DAYS = 30


class FindingOut(BaseModel):
    rule: str
    severity: str
    basis: str
    title: str
    detail: str
    stations: list = []
    process: Optional[str] = None
    waste: Optional[str] = None
    manual: Optional[str] = None
    metrics: dict = {}


class ReportOut(BaseModel):
    readiness: str
    headline: str
    narrative: list
    findings: list
    coverage: dict
    counts: dict


class LineRunoutOut(BaseModel):
    processId: str
    processName: str
    nextStationId: str
    nextStationName: str
    bufferUnits: int
    lineCycleSec: Optional[float] = None
    #: Seconds until the fed line starves. 0 = starving now. None = no
    #: measured rate downstream, so there is no clock — sort those FIFO.
    runoutSec: Optional[float] = None


class RunoutOut(BaseModel):
    stationId: str
    lines: dict[str, LineRunoutOut]


async def _snapshot(session: AsyncSession, company_id) -> engine.Snapshot:
    """Kept as a thin alias: `core.line_snapshot.build` is the one builder,
    shared with the trial drip's day-3 report."""
    return await line_snapshot.build(session, company_id)


@router.get("/", response_model=ReportOut)
async def line_report(ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """What is wrong with this line, and what to do about it.

    Readable by any member of an entitled company: an operator being able to see
    that their bench is the constraint is the point of the thing, not a risk.
    The gate is per *plan*, never per role.
    """
    ent = ctx.entitlement or await entitlements.resolve(session, ctx.company_id)
    entitlements.ensure_line_doctor(ent)
    snap = await _snapshot(session, ctx.company_id)
    report = engine.analyse(snap)
    return ReportOut(
        readiness=report.readiness,
        headline=report.headline,
        narrative=report.narrative,
        findings=[FindingOut(**vars(f)) for f in report.findings],
        coverage=report.coverage,
        counts={
            "critical": sum(1 for f in report.findings if f.severity == engine.CRITICAL),
            "warning": sum(1 for f in report.findings if f.severity == engine.WARNING),
            "insight": sum(1 for f in report.findings if f.severity == engine.INSIGHT),
        },
    )

@router.get("/runout/{station_id}", response_model=RunoutOut)
async def station_runout(station_id: str,
                         ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """The runout rule, for the operator's lot picker at a shared station:
    per line flowing through here, how long until the station it feeds
    starves. Readable by any member — the operator holding the tablet is the
    person the answer is for."""
    from fastapi import HTTPException

    snap = await _snapshot(session, ctx.company_id)
    if not any(st.id == station_id for st in snap.stations):
        raise HTTPException(404, "Station not found")
    lines = runout_engine.station_runout(snap, station_id)
    return RunoutOut(stationId=station_id, lines={
        pid: LineRunoutOut(
            processId=r.process_id, processName=r.process_name,
            nextStationId=r.next_station_id, nextStationName=r.next_station_name,
            bufferUnits=r.buffer_units, lineCycleSec=r.line_cycle_sec,
            runoutSec=r.runout_sec,
        ) for pid, r in lines.items()})
