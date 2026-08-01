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


async def _snapshot(session: AsyncSession, company_id) -> engine.Snapshot:
    async def rows(model):
        return (await session.execute(
            select(model).where(model.companyId == company_id))).scalars().all()

    stations = await rows(StationRow)
    routes = await rows(RouteRow)
    processes = await rows(ProcessRow)
    templates = await rows(LotTemplateRow)
    cards = await rows(CardRow)

    wip: dict = {}
    for c in cards:
        for sid, b in (c.bins or {}).items():
            wip[sid] = wip.get(sid, 0) + int(b.get("count", 0) or 0)

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=LOOKBACK_DAYS)
    schedule, tzname = await _work_schedule(session, company_id)
    measured = await _station_metrics(session, company_id, schedule, tzname, since, now)

    # Per-session seconds per piece, and per-operator means. The aggregate
    # cannot answer "is this repeatable" or "do two people do it differently" —
    # both need the individual sessions, and both are findings worth having.
    work = (await session.execute(
        select(SessionRow).where(
            SessionRow.companyId == company_id,
            SessionRow.endedAt.isnot(None),
            SessionRow.startedAt >= since))).scalars().all()
    samples: dict = {}
    per_operator: dict = {}
    for w in work:
        if not w.durationSec or not w.quantity or w.quantity < 1:
            continue
        sid = str(w.stationId)
        each = w.durationSec / w.quantity
        samples.setdefault(sid, []).append(each)
        per_operator.setdefault(sid, {}).setdefault(w.operatorId or "—", []).append(each)

    metrics = {}
    for sid, m in measured.items():
        ops = {op: sum(v) / len(v) for op, v in per_operator.get(sid, {}).items() if v}
        metrics[sid] = engine.StationMetrics(
            sessions=m.get("sessionCount", 0) or 0,
            units=m.get("totalUnits", 0) or 0,
            working_sec=m.get("totalWorkingSec", 0.0) or 0.0,
            cycle_sec=m.get("cycleTimeSec"),
            line_cycle_sec=m.get("lineCycleTimeSec"),
            oee=m.get("oee"),
            samples=samples.get(sid, []),
            operators=ops,
        )

    map_row = (await session.execute(
        select(MapSettingsRow).where(MapSettingsRow.companyId == company_id))).scalars().first()

    return engine.Snapshot(
        stations=[engine.StationIn(
            id=str(s.id), name=s.name, is_storage=bool(s.isStorage),
            provider=s.integrationProvider, branch_mode=s.branchMode,
            x=float((s.position or {}).get("x", 0) or 0),
            y=float((s.position or {}).get("y", 0) or 0),
        ) for s in stations],
        routes=[engine.RouteIn(load=str(r.load), unload=str(r.unload),
                               quantity=int(r.quantity or 1), process=str(r.processId))
                for r in routes],
        processes=[engine.ProcessIn(id=str(p.id), name=p.name,
                                    desired_takt_sec=getattr(p, "desiredTaktSec", None))
                   for p in processes],
        templates=[engine.TemplateIn(
            id=str(t.id), name=t.name,
            process=str(t.processId) if t.processId else None,
            start_station=str(t.startStationId) if t.startStationId else None)
            for t in templates],
        wip=wip,
        metrics=metrics,
        pixels_per_unit=float(map_row.pixelsPerUnit) if map_row else 0.0,
        unit=(map_row.unit if map_row else "m"),
    )


@router.get("/", response_model=ReportOut)
async def line_report(ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """What is wrong with this line, and what to do about it.

    Readable by any member: an operator being able to see that their bench is
    the constraint is the point of the thing, not a risk.
    """
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
