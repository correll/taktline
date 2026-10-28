"""Build the line doctor's input from the database.

Lifted out of `routers/analysis.py` so a **background job** can produce a report
without importing the router graph — the trial drip's day-3 email is a real
line-doctor reading of the customer's own line, not a form letter, and a
background task that imports routers risks a circular import with `main`.

`core/analysis.py` still owns every judgement. This only gathers.
"""

import bisect
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import analysis as engine
from ..models.common import utcnow
from ..db.tables import (
    Card as CardRow, CardEvent, LotTemplate as LotTemplateRow, MapSettings as MapSettingsRow,
    Process as ProcessRow, Route as RouteRow, Station as StationRow,
    WorkSession as SessionRow,
)

# The report describes how the line is running now, not how it ran last spring.
LOOKBACK_DAYS = 30


async def build(session: AsyncSession, company_id) -> engine.Snapshot:
    async def rows(model):
        return (await session.execute(
            select(model).where(model.companyId == company_id))).scalars().all()

    stations = await rows(StationRow)
    routes = await rows(RouteRow)
    processes = await rows(ProcessRow)
    templates = await rows(LotTemplateRow)
    cards = await rows(CardRow)

    # Finished goods resting on a shelf are not work in process. Counted, they
    # inflated Little's-law lead time with the warehouse: a lot card's whole
    # quantity read as "on the floor", including the units already delivered
    # to the customer shelf.
    off_floor = {str(st.id) for st in stations if st.isStorage or st.integrationProvider}
    wip: dict = {}
    wip_process: dict = {}
    wip_station_process: dict = {}
    for c in cards:
        for sid, b in (c.bins or {}).items():
            n = int(b.get("count", 0) or 0)
            wip[sid] = wip.get(sid, 0) + n
            if c.processId:
                pid = str(c.processId)
                if str(sid) not in off_floor:
                    wip_process[pid] = wip_process.get(pid, 0) + n
                per = wip_station_process.setdefault(sid, {})
                per[pid] = per.get(pid, 0) + n

    now = utcnow()
    since = now - timedelta(days=LOOKBACK_DAYS)
    # Imported here rather than at module scope: `routers.sessions` pulls in
    # the router graph, and this module is imported by a background task.
    from ..routers.sessions import (_line_cycle_times_by_process, _station_metrics,
                                    _work_schedule)

    schedule, tzname = await _work_schedule(session, company_id)
    measured = await _station_metrics(session, company_id, schedule, tzname, since, now)
    lct_by_process = await _line_cycle_times_by_process(session, company_id, schedule, tzname,
                                                        since, now)
    from .flow import by_process as _flow_by_process
    wip_by_p, exit_by_p = await _flow_by_process(session, company_id, since, now, schedule, tzname)
    from . import whatif_data as _wd
    try:
        _model, _ = await _wd.build_model(session, company_id, since, now, schedule, tzname)
        observed_by_p = _model.observed_by_process
    except Exception:                       # the report must not fail over a measurement
        observed_by_p = {}

    # Seconds per piece per LOT, and per-operator means. The aggregate cannot
    # answer "is this repeatable" or "do two people do it differently" -- both
    # need the individual lots, and both are findings worth having. A sample
    # is a lot's VISIT to a station: its sessions there until those units are
    # moved on, pooled (work time over pieces). An operator who presses Stop
    # at a break books the partly finished piece's time against the pieces
    # completed, so one session reads long and the one after the break short,
    # and charted per session every line with breaks would show an
    # "assignable cause" that is only the clock. A visit, not the whole card:
    # a card that carries a stock through a station tray by tray (partial
    # moves) passes it many times, and pooled whole it would be one sample.
    work = (await session.execute(
        select(SessionRow).where(
            SessionRow.companyId == company_id,
            SessionRow.endedAt.isnot(None),
            SessionRow.startedAt >= since)
        # Recorded order: the individuals chart reads successive lots, and a
        # moving range over rows in whatever order Postgres returns them
        # measures nothing. A lot takes the place of its first session.
        .order_by(SessionRow.startedAt, SessionRow.id))).scalars().all()
    tmpl_of = {str(c.id): str(c.lotTemplateId) for c in (await session.execute(
        select(CardRow).where(CardRow.companyId == company_id))).scalars().all() if c.lotTemplateId}
    # Moves out of each station, per card, in time order: the visit a session
    # belongs to is the number of moves of its card out of its station before
    # the session started.
    outs: dict = {}
    for cid, frm, ts in (await session.execute(
            select(CardEvent.cardId, CardEvent.fromStation, CardEvent.timestamp).where(
                CardEvent.companyId == company_id, CardEvent.type == "moved",
                CardEvent.timestamp >= since, CardEvent.fromStation.isnot(None))
            .order_by(CardEvent.timestamp))).all():
        outs.setdefault((str(cid), str(frm)), []).append(ts)
    lots: dict = {}            # (station, visit) -> [work sec, pieces]
    lots_op: dict = {}         # (station, visit, operator) -> [work sec, pieces]
    for w in work:
        if not w.durationSec or not w.quantity or w.quantity < 1:
            continue
        if w.closedBy == "next_start":   # never stopped: not a reading of the work
            continue
        sid = str(w.stationId)
        if w.cardId:
            cid = str(w.cardId)
            lot = (cid, bisect.bisect_right(outs.get((cid, sid), []), w.startedAt))
        else:
            lot = (f"session:{w.id}", 0)      # no lot: the session is its own
        acc = lots.setdefault((sid, lot), [0.0, 0])
        acc[0] += w.durationSec
        acc[1] += w.quantity
        # A session with no operator on record is nobody's sample: pooled
        # under one key it would be charted as a person.
        if w.operatorId:
            acc = lots_op.setdefault((sid, lot, w.operatorId), [0.0, 0])
            acc[0] += w.durationSec
            acc[1] += w.quantity
    samples: dict = {}
    samples_by: dict = {}
    per_operator: dict = {}
    operator_samples: dict = {}
    for (sid, lot), (sec, n) in lots.items():          # dicts keep first-session order
        each = sec / n
        samples.setdefault(sid, []).append(each)
        # by product too: a station that makes two products with different
        # work contents is not uneven, and pooled its times look as if it were
        samples_by.setdefault(sid, {}).setdefault(tmpl_of.get(lot[0], "?"), []).append(each)
    for (sid, lot, op), (sec, n) in lots_op.items():
        per_operator.setdefault(sid, {}).setdefault(op, []).append(sec / n)
        operator_samples.setdefault(sid, {}).setdefault(op, []).append(sec / n)

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
            samples_by=samples_by.get(sid, {}),
            operators=ops,
            operator_samples=operator_samples.get(sid, {}),
            downtime_sec=m.get("downtimeSec", 0.0) or 0.0,
            changeover_sec=m.get("changeoverSec", 0.0) or 0.0,
            wip_avg=m.get("wipAvg"),
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
        wip_process=wip_process,
        line_cycle_by_process={(k[0], k[1]): v for k, v in lct_by_process.items()},
        wip_avg_by_process=wip_by_p,
        exit_rate_by_process=exit_by_p,
        observed_lead_by_process=observed_by_p,
        wip_station_process=wip_station_process,
        metrics=metrics,
        pixels_per_unit=float(map_row.pixelsPerUnit) if map_row else 0.0,
        unit=(map_row.unit if map_row else "m"),
    )
