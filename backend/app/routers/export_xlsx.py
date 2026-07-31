"""The statistics and the history behind them, as a spreadsheet.

**Why xlsx and not CSV.** A CSV is one flat table of strings: it cannot carry
the five tables this export needs, and every value arrives as text that Excel
then guesses at — famously turning lot codes into dates and dropping leading
zeros, and disagreeing about the decimal separator between locales. An xlsx
carries real typed cells (a timestamp is a timestamp, a duration is a number),
one sheet per table, frozen headers and sane column widths, and opens natively
in Excel, LibreOffice, OpenOffice, Numbers and Google Sheets with no import
dialog at all.

The workbook is built in memory and streamed; openpyxl's write-only mode keeps
a long history from being held as cell objects.
"""

from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session
from ..db.tables import (
    Card as CardRow, CardEvent as CardEventRow, LotTemplate as LotTemplateRow,
    Process as ProcessRow, ProductionOrder as OrderRow, Station as StationRow,
    WorkSession as SessionRow,
)
from ..deps.auth import CompanyContext, require_scope
from .sessions import _station_metrics, _work_schedule, _TREND_WINDOWS

router = APIRouter(prefix="/reports", tags=["reports"])

_export_access = require_scope("reports", session_role="user")

# Enough for a year of a busy line; past this the answer is a BI connector
# (/reports/*) rather than a spreadsheet nobody can open.
_MAX_ROWS = 100_000


def _naive(dt):
    """Excel has no concept of an offset — it stores wall-clock. Everything in
    Taktline is UTC, so strip the tzinfo and say UTC in the header rather than
    let each reader guess."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _append(ws, row):
    """Append a row, pinning every string cell to TEXT.

    openpyxl types a string beginning with `=` as a **formula**, and most of
    what lands in these cells is written by someone else: lot codes come from
    the ERP's reference, station and product names from whoever set the line
    up, and order attributes straight off a connector or a CSV. A lot code of
    `=HYPERLINK("http://…","Invoice")` — or the DDE form, `=cmd|' /C …'!A0` —
    would be exported as live content that evaluates when the customer opens
    the file on their own machine. That is spreadsheet formula injection, and
    the export is the perfect carrier: it is *meant* to be opened.

    Pinning the cell type keeps the text exactly as typed (the reader still
    sees `=1+1`) while making it inert. Numbers, dates and percentages keep
    their own types, so the workbook stays pivotable — the whole reason it is
    xlsx and not CSV.
    """
    ws.append(row)
    for c in ws[ws.max_row]:
        if c.data_type == "f":
            c.data_type = "s"


def _sheet(wb, title: str, headers: list, widths: list):
    ws = wb.create_sheet(title)
    _append(ws, headers)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i) if i <= 26 else "A"].width = w
    return ws


@router.get("/export.xlsx")
async def export_workbook(window: Optional[str] = None,
                          ctx: CompanyContext = Depends(_export_access),
                          session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Every number on the Statistics page, plus the history it was computed
    from, as one workbook.

    `window` (1h/1d/1w/1m) narrows the Stations sheet exactly as the picker on
    the page does, so an export matches what the person exporting is looking at.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    now = datetime.now(timezone.utc)
    schedule, tzname = await _work_schedule(session, ctx.company_id)

    async def named(model):
        rows = (await session.execute(
            select(model).where(model.companyId == ctx.company_id))).scalars().all()
        return {str(r.id): r for r in rows}

    stations = await named(StationRow)
    processes = await named(ProcessRow)
    templates = await named(LotTemplateRow)

    span = _TREND_WINDOWS.get(window) if window else None
    since = now - span if span else now.replace(year=now.year - 5)
    metrics = await _station_metrics(session, ctx.company_id, schedule, tzname, since, now)

    wb = Workbook()
    wb.remove(wb.active)
    head = Font(bold=True)

    def finish(ws, widths):
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for c in ws[1]:
            c.font = head
            c.alignment = Alignment(vertical="center")
        ws.freeze_panes = "A2"          # headers stay put while scrolling
        ws.auto_filter.ref = ws.dimensions

    # ── 1. About ────────────────────────────────────────────────────────────
    ws = wb.create_sheet("About")
    for row in [
        ["Taktline export"],
        [],
        ["Generated (UTC)", _naive(now)],
        ["Statistics window", _TREND_WINDOWS and (window or "all time")],
        ["Timezone of the line", tzname],
        [],
        ["All timestamps in this workbook are UTC."],
        ["Durations are in seconds. Cycle time and line cycle time are per piece."],
        ["OEE is a fraction of open work time, formatted as a percentage."],
    ]:
        _append(ws, row)
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 26

    # ── 2. Stations — the timing table as shown ─────────────────────────────
    ws = wb.create_sheet("Stations")
    _append(ws, ["Station", "Process(es)", "Storage", "Sessions", "Units",
               "Working time (s)", "Cycle time (s/piece)",
               "Line cycle time (s/piece)", "OEE"])
    proc_of_station: dict = {}
    for t in templates.values():
        if t.startStationId and t.processId:
            proc_of_station.setdefault(str(t.startStationId), set()).add(
                processes[str(t.processId)].name if str(t.processId) in processes else "")
    for sid, st in sorted(stations.items(), key=lambda kv: kv[1].name):
        m = metrics.get(sid, {})
        _append(ws, [
            st.name,
            ", ".join(sorted(p for p in proc_of_station.get(sid, set()) if p)),
            "yes" if st.isStorage else "",
            m.get("sessionCount", 0),
            m.get("totalUnits", 0),
            round(m.get("totalWorkingSec") or 0, 1),
            round(m["cycleTimeSec"], 2) if m.get("cycleTimeSec") else None,
            round(m["lineCycleTimeSec"], 1) if m.get("lineCycleTimeSec") else None,
            m.get("oee"),
        ])
    for row in ws.iter_rows(min_row=2, min_col=9, max_col=9):
        for c in row:
            c.number_format = "0.0%"
    finish(ws, [24, 18, 9, 10, 9, 17, 20, 24, 9])

    # ── 3. Work sessions — what the timers recorded ─────────────────────────
    ws = wb.create_sheet("Work sessions")
    _append(ws, ["Started (UTC)", "Ended (UTC)", "Station", "Operator", "Units",
               "Duration (s)", "Seconds per piece", "Lot code", "Product"])
    rows = (await session.execute(
        select(SessionRow).where(SessionRow.companyId == ctx.company_id)
        .order_by(SessionRow.startedAt.asc()).limit(_MAX_ROWS))).scalars().all()
    cards = await named(CardRow)
    for r in rows:
        card = cards.get(str(r.cardId)) if r.cardId else None
        tmpl = templates.get(str(card.lotTemplateId)) if card else None
        st = stations.get(str(r.stationId))
        _append(ws, [
            _naive(r.startedAt), _naive(r.endedAt), st.name if st else "",
            r.operatorId, r.quantity, round(r.durationSec, 1) if r.durationSec else None,
            round(r.durationSec / r.quantity, 2) if r.durationSec and r.quantity else None,
            card.lotNum if card else "", tmpl.name if tmpl else "",
        ])
    finish(ws, [21, 21, 22, 14, 8, 13, 18, 14, 22])

    # ── 4. Lot history — every movement, the audit trail ────────────────────
    ws = wb.create_sheet("Lot history")
    _append(ws, ["When (UTC)", "Event", "Lot code", "Product", "From", "To",
               "Units", "Note", "Lot id"])
    events = (await session.execute(
        select(CardEventRow).where(CardEventRow.companyId == ctx.company_id)
        .order_by(CardEventRow.timestamp.asc()).limit(_MAX_ROWS))).scalars().all()
    for e in events:
        card = cards.get(e.cardId)
        tmpl = templates.get(str(card.lotTemplateId)) if card else None
        frm = stations.get(e.fromStation) if e.fromStation else None
        to = stations.get(e.toStation) if e.toStation else None
        _append(ws, [
            _naive(e.timestamp), e.type, card.lotNum if card else "",
            tmpl.name if tmpl else "", frm.name if frm else "", to.name if to else "",
            e.quantity, e.note, e.cardId,
        ])
    finish(ws, [21, 11, 14, 22, 20, 20, 8, 26, 38])

    # ── 5. Lots on the floor now ────────────────────────────────────────────
    ws = wb.create_sheet("Lots now")
    _append(ws, ["Lot code", "Product", "Process", "Station", "Units",
               "Status", "Flagged", "Created (UTC)", "Order"])
    orders = await named(OrderRow)
    for c in sorted(cards.values(), key=lambda c: c.createdAt or now):
        tmpl = templates.get(str(c.lotTemplateId))
        proc = processes.get(str(c.processId)) if c.processId else None
        order = orders.get(str(c.orderId)) if c.orderId else None
        for station_id, bin_ in (c.bins or {}).items():
            st = stations.get(station_id)
            _append(ws, [
                c.lotNum, tmpl.name if tmpl else "", proc.name if proc else "",
                st.name if st else station_id, bin_.get("count"), c.status,
                "yes" if c.flagged else "", _naive(c.createdAt),
                order.externalRef if order else "",
            ])
    finish(ws, [14, 22, 14, 22, 8, 10, 9, 21, 18])

    # ── 6. Production orders ────────────────────────────────────────────────
    ws = wb.create_sheet("Orders")
    _append(ws, ["Reference", "Source", "Product", "Ordered", "Done", "Status",
               "Released (UTC)", "Completed (UTC)"])
    for o in sorted(orders.values(), key=lambda o: o.createdAt or now):
        tmpl = templates.get(str(o.productTemplateId)) if o.productTemplateId else None
        _append(ws, [o.externalRef, o.source, tmpl.name if tmpl else "",
                   o.quantity, o.quantityDone, o.status,
                   _naive(o.createdAt), _naive(getattr(o, "completedAt", None))])
    finish(ws, [18, 14, 22, 10, 8, 12, 21, 21])

    buf = BytesIO()
    wb.save(buf)
    stamp = now.strftime("%Y-%m-%d")
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="taktline-statistics-{stamp}.xlsx"'},
    )
