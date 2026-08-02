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
from ..core import line_snapshot
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
    """Kept as a thin alias: `core.line_snapshot.build` is the one builder,
    shared with the trial drip's day-3 report."""
    return await line_snapshot.build(session, company_id)


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
