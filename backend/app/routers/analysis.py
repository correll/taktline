"""`GET /analysis/` — the line doctor's report.

Assembles a snapshot of the line from the database and hands it to
`core.analysis`, which is where all the judgement lives. Nothing here decides
anything; the split exists so the rules can be tested against hand-built lines
with planted faults, without a database anywhere near them.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
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
from ..models.common import utcnow

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


# ─── What if? ────────────────────────────────────────────────────────────────

class ChangeIn(BaseModel):
    stationId: str
    #: Multiplies the work time: 0.75 is a process 25% faster.
    speedFactor: float = Field(1.0, gt=0.05, le=10)
    #: Piece-time variability of the new process; omit to keep the measured one.
    cv: Optional[float] = Field(None, ge=0, le=3)
    #: False: the new process does not break down.
    breakdowns: bool = True
    #: False: changeovers eliminated (SMED).
    changeovers: bool = True
    servers: Optional[int] = Field(None, ge=1, le=20)


class ScenarioIn(BaseModel):
    name: str = Field(..., max_length=80)
    changes: list[ChangeIn] = Field(default_factory=list, max_length=20)
    #: 1.1 = the same work arriving 10% faster.
    demandFactor: float = Field(1.0, gt=0.1, le=5)


class SharedCrewIn(BaseModel):
    stations: list[str] = Field(..., min_length=2, max_length=12)
    operators: int = Field(1, ge=1, le=50)


class AssumptionsIn(BaseModel):
    """Idealisations of the model to replace with what the record shows.
    Empty: the model as it is (core/whatif.py)."""
    # station -> most lots it holds at once; 0 = the most it held in the record
    buffers: dict[str, int] = Field(default_factory=dict)
    sharedCrews: list[SharedCrewIn] = Field(default_factory=list, max_length=12)
    # stations whose breakdowns accrue on open hours, at the recorded rate per open hour
    openHourBreakdowns: list[str] = Field(default_factory=list, max_length=200)
    # stations whose crew is replayed as recorded (operators present over the day)
    recordedStaffing: list[str] = Field(default_factory=list, max_length=200)


class WhatIfIn(BaseModel):
    scenarios: list[ScenarioIn] = Field(..., min_length=1, max_length=12)
    assumptions: Optional[AssumptionsIn] = None
    replications: int = Field(20, ge=2, le=50)
    days: int = Field(LOOKBACK_DAYS, ge=1, le=LOOKBACK_DAYS)


class AutomationIn(BaseModel):
    assumptions: Optional[AssumptionsIn] = None
    speedFactor: float = Field(0.75, gt=0.05, le=10)
    cv: Optional[float] = Field(0.05, ge=0, le=3)
    breakdowns: bool = True
    replications: int = Field(20, ge=2, le=50)
    days: int = Field(LOOKBACK_DAYS, ge=1, le=LOOKBACK_DAYS)


async def _model(session, company_id, days):
    from ..core import whatif_data
    schedule, tzname = await _work_schedule(session, company_id)
    until = utcnow()
    return await whatif_data.build_model(session, company_id, until - timedelta(days=days),
                                         until, schedule, tzname)


def _present(res: dict, names: dict) -> dict:
    hours = lambda s: None if s is None else round(s / 3600, 5)
    def stations(d):
        return {names.get(k, k): {"busy": round(v["busy"], 3), "down": round(v["down"], 3)}
                for k, v in d.items()}
    rnd = lambda x, n=2: None if x is None else round(x, n)
    out = {"unit": "open hours",
           "baseline": {"leadTimeHours": hours(res["baseline"]["leadTimeSec"]),
                        "leadSpreadHours": hours(res["baseline"].get("leadSpreadSec")),
                        "leadP90Hours": hours(res["baseline"].get("leadP90Sec")),
                        "wipUnits": rnd(res["baseline"].get("wip")),
                        "stations": stations(res["baseline"]["stations"])},
           "calibration": {"observedLeadTimeHours": hours(res["calibration"]["observedLeadTimeSec"]),
                           "modelLeadTimeHours": hours(res["calibration"]["modelLeadTimeSec"]),
                           "observedUnits": res["calibration"]["observedUnits"]},
           "scenarios": []}
    for r in res["scenarios"]:
        out["scenarios"].append({
            "name": names.get(r["name"], r["name"]),
            "stationId": r["name"] if r["name"] in names else None,
            "leadTimeHours": hours(r["leadTimeSec"]),
            "gainHours": hours(r.get("gainSec")),
            "gainCi95Hours": [hours(x) for x in r.get("gainCi95", [])] or None,
            "gainShare": None if r.get("gainShare") is None else round(r["gainShare"], 4),
            "leadSpreadHours": hours(r.get("leadSpreadSec")),
            "leadP90Hours": hours(r.get("leadP90Sec")),
            "wipUnits": rnd(r.get("wip")),
            "wipReductionUnits": rnd(r.get("wipReduction")),
            "wipReductionCi95Units": [rnd(x) for x in r.get("wipReductionCi95", [])] or None,
            "spreadReductionHours": hours(r.get("spreadReductionSec")),
            "spreadReductionCi95Hours": [hours(x) for x in r.get("spreadReductionSec" + "Ci95", [])] or None,
            "p90ReductionHours": hours(r.get("p90ReductionSec")),
            "stations": stations(r["stations"])})
    return out


def _apply_assumptions(model, a: Optional["AssumptionsIn"]):
    """Replace the idealisations the request names, from the record."""
    from fastapi import HTTPException
    from ..core import whatif
    if a is None:
        return
    rec = model.record or {}
    known = set(model.stations)
    named = (set(a.buffers) | {x for g in a.sharedCrews for x in g.stations}
             | set(a.openHourBreakdowns) | set(a.recordedStaffing))
    if named - known:
        raise HTTPException(404, "Station not found")
    buffers = {}
    for sid, n in a.buffers.items():
        n = n or (rec.get("buffers", {}).get(sid, {}).get("maxLots") or 0)
        if n < 1:
            raise HTTPException(422, "No lots were recorded at that station to size its buffer")
        buffers[sid] = int(n)
    model.assumptions = whatif.Assumptions(
        buffers=buffers,
        shared=[(list(g.stations), g.operators) for g in a.sharedCrews],
        open_failures={sid: rec.get("breakdownClock", {}).get(sid, {}).get("perOpenSec", 0.0)
                       for sid in a.openHourBreakdowns},
        staffing={sid: [tuple(x) for x in rec.get("staffing", {}).get(sid, {}).get("schedule", [])]
                  for sid in a.recordedStaffing
                  if rec.get("staffing", {}).get(sid, {}).get("schedule")})


def _assert_answerable(model):
    from fastapi import HTTPException
    if not any(st.worked for st in model.stations.values()):
        raise HTTPException(409, "Nothing to simulate yet: no station has timed work in this window")
    if not model.arrivals:
        raise HTTPException(409, "Nothing to simulate yet: no lot has left an entry station in this window")


@router.post("/what-if")
async def what_if(body: WhatIfIn, ctx: CompanyContext = Depends(get_active_company),
                  session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Replay the recorded period with something changed, and say how much the
    lead time moves. See `core/whatif.py` for what the model is and is not."""
    from ..core import whatif
    from fastapi import HTTPException
    ent = ctx.entitlement or await entitlements.resolve(session, ctx.company_id)
    entitlements.ensure_line_doctor(ent)
    model, names = await _model(session, ctx.company_id, body.days)
    _assert_answerable(model)
    _apply_assumptions(model, body.assumptions)
    scen = []
    for sc in body.scenarios:
        for c in sc.changes:
            if c.stationId not in model.stations:
                raise HTTPException(404, "Station not found")
        scen.append(whatif.Scenario(name=sc.name, demand=sc.demandFactor, changes=[
            whatif.Change(station=c.stationId, speed=c.speedFactor, cv=c.cv,
                          breakdowns=c.breakdowns, changeovers=c.changeovers,
                          servers=c.servers) for c in sc.changes]))
    return _present(whatif.run(model, scen, body.replications), names)


@router.get("/assumptions")
async def assumptions(days: int = LOOKBACK_DAYS, ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """What the record says about each of the what-if model's idealisations:
    the evidence on which to replace one (core/whatif_record.py). Reading
    only; the request to /what-if names what to replace."""
    ent = ctx.entitlement or await entitlements.resolve(session, ctx.company_id)
    entitlements.ensure_line_doctor(ent)
    model, names = await _model(session, ctx.company_id, max(1, min(days, LOOKBACK_DAYS)))
    rec = model.record or {}
    nm = lambda sid: names.get(sid, sid)
    return {
        "unit": "open seconds",
        "busyShare": {nm(k): v for k, v in rec.get("busyShare", {}).items()},
        "sharedCrew": [{**p, "stationIds": p["stations"], "stations": [nm(x) for x in p["stations"]]}
                       for p in rec.get("sharedCrew", [])],
        "breakdownClock": {nm(k): {**v, "stationId": k} for k, v in rec.get("breakdownClock", {}).items()},
        "buffers": {nm(k): {**v, "stationId": k} for k, v in rec.get("buffers", {}).items()},
        "staffing": {nm(k): {"stationId": k, "min": v["min"], "max": v["max"]}
                     for k, v in rec.get("staffing", {}).items()},
    }


@router.post("/automation")
async def automation(body: AutomationIn, ctx: CompanyContext = Depends(get_active_company),
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """The same machine tried at every station worked by hand, ranked by how
    much it would shorten the lead time."""
    from ..core import whatif
    ent = ctx.entitlement or await entitlements.resolve(session, ctx.company_id)
    entitlements.ensure_line_doctor(ent)
    model, names = await _model(session, ctx.company_id, body.days)
    _assert_answerable(model)
    _apply_assumptions(model, body.assumptions)
    return _present(whatif.automation_candidates(model, body.speedFactor, body.cv,
                                                 body.breakdowns, body.replications), names)
