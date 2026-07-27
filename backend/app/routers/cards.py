from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import PlainTextResponse
from typing import List
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.ws_events import queue_event
from ..db.connection import get_session, require_uuid, parse_uuid
from ..db.tables import (
    Card as CardRow, CardEvent as CardEventRow,
    LotTemplate as LotTemplateRow, Process as ProcessRow, Route as RouteRow,
    ProductionOrder as OrderRow, IntegrationOutbox as OutboxRow, Station as StationRow,
)
from ..deps.auth import (CompanyContext, ensure_sandbox_quota, get_active_company,
                         require_admin, require_super_admin, require_scope)
from ..models.card import Card, CardCreate, CardUpdate, LotStatus
from ..models.card_event import CardEvent, EventType
from ..models.common import utcnow
from ..plugins.registry import plugin_registry
from .merge import _leaf_sources, _gen_lot_code

router = APIRouter(prefix="/cards", tags=["cards"])


def _to_card(r: CardRow) -> Card:
    return Card(
        _id=str(r.id),
        lotTemplateId=str(r.lotTemplateId),
        processId=str(r.processId),
        lotNum=r.lotNum,
        totalQuantity=r.totalQuantity,
        bins=r.bins or {},
        fields=r.fields or {},
        flagged=r.flagged,
        description=r.description,
        status=r.status,
        orderId=str(r.orderId) if r.orderId else None,
        createdAt=r.createdAt,
        updatedAt=r.updatedAt,
    )


def _emit_card_update(session, company_id, row: CardRow) -> None:
    """Stage a card_update broadcast (delivered after commit) so every other
    client's board tracks this mutation live instead of holding stale bins."""
    queue_event(session, company_id, {
        "type": "card_update",
        "payload": _to_card(row).model_dump(by_alias=True, mode="json"),
    })


def _emit_card_delete(session, company_id, card_id: str) -> None:
    queue_event(session, company_id, {"type": "card_delete", "payload": {"id": card_id}})


def _to_event(r: CardEventRow) -> CardEvent:
    return CardEvent(
        _id=str(r.id), cardId=r.cardId, type=r.type,
        fromStation=r.fromStation, toStation=r.toStation,
        quantity=r.quantity, note=r.note, timestamp=r.timestamp,
    )


def _req_fk(value: str):
    parsed = parse_uuid(value)
    if parsed is None:
        raise HTTPException(400, f"Invalid id: {value!r}")
    return parsed


def _record_event(session, company_id, card_id: str, event_type: EventType, **kwargs) -> None:
    session.add(CardEventRow(
        companyId=company_id,
        cardId=card_id,
        type=event_type,
        fromStation=kwargs.get("fromStation"),
        toStation=kwargs.get("toStation"),
        quantity=kwargs.get("quantity"),
        note=kwargs.get("note", ""),
        timestamp=utcnow(),
    ))


async def _get_owned(session: AsyncSession, card_id: str, ctx: CompanyContext,
                     for_update: bool = False) -> CardRow:
    """Fetch a company-owned card. Mutating endpoints pass ``for_update=True`` to
    row-lock it: a duplicated request (double-fired drag, StrictMode effect,
    scanner re-read) then waits and re-reads the already-mutated state instead of
    applying the same bins math twice — which would double-move or double-unmerge
    units."""
    row = await session.get(
        CardRow, require_uuid(card_id, "Card not found"),
        with_for_update=True if for_update else None,
    )
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Card not found")
    return row


# ─── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[Card])
async def list_cards(ctx: CompanyContext = Depends(get_active_company),
                     session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(CardRow).where(CardRow.companyId == ctx.company_id)
    )).scalars().all()
    return [_to_card(r) for r in rows]


@router.post("/", response_model=Card, status_code=201)
async def create_card(body: CardCreate, ctx: CompanyContext = Depends(require_admin),  # admin+ may create lots
                      session: AsyncSession = Depends(get_session)):
    await ensure_sandbox_quota(session, ctx, CardRow)
    data = body.model_dump()
    if not data.get("lotNum"):
        data["lotNum"] = _gen_lot_code()   # user may define a code; default is generated
    tmpl_id = _req_fk(data["lotTemplateId"])
    proc_id = _req_fk(data["processId"])
    # Both must belong to this company.
    tmpl = await session.get(LotTemplateRow, tmpl_id)
    proc = await session.get(ProcessRow, proc_id)
    if tmpl is None or tmpl.companyId != ctx.company_id or proc is None or proc.companyId != ctx.company_id:
        raise HTTPException(400, "Card references a template or process outside this company")
    data["lotTemplateId"] = tmpl_id
    data["processId"] = proc_id
    row = CardRow(**data, companyId=ctx.company_id)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(400, "Card references a non-existent template or process")

    card = _to_card(row)
    card_id = str(row.id)
    _record_event(session, ctx.company_id, card_id, "created")
    _emit_card_update(session, ctx.company_id, row)
    for station_id, bin_data in card.bins.items():
        if bin_data.count > 0:
            await plugin_registry.notify_lot_arrive(station_id, card_id, card.model_dump(mode="json"))
    return card


@router.get("/{card_id}", response_model=Card)
async def get_card(card_id: str, ctx: CompanyContext = Depends(get_active_company),
                   session: AsyncSession = Depends(get_session)):
    return _to_card(await _get_owned(session, card_id, ctx))


@router.put("/{card_id}", response_model=Card)
async def update_card(card_id: str, body: CardUpdate, ctx: CompanyContext = Depends(require_super_admin),
                      session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, card_id, ctx)
    old_bins = dict(row.bins or {})
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    for k, v in patch.items():
        setattr(row, k, v)
    row.updatedAt = utcnow()
    await session.flush()
    card = _to_card(row)

    if body.flagged is not None:
        _record_event(session, ctx.company_id, card_id, "flagged" if body.flagged else "unflagged")

    if body.bins is not None:
        for station_id, bin_data in card.bins.items():
            old_count = old_bins.get(station_id, {}).get("count", 0)
            if bin_data.count > 0 and old_count == 0:
                await plugin_registry.notify_lot_arrive(station_id, card_id, card.model_dump(mode="json"))
            elif bin_data.count == 0 and old_count > 0:
                await plugin_registry.notify_lot_depart(station_id, card_id)
        _record_event(session, ctx.company_id, card_id, "updated")

    _emit_card_update(session, ctx.company_id, row)
    return card


class CardStatusUpdate(BaseModel):
    status: LotStatus


@router.patch("/{card_id}/status", response_model=Card)
async def update_card_status(card_id: str, body: CardStatusUpdate,
                             ctx: CompanyContext = Depends(get_active_company),
                             session: AsyncSession = Depends(get_session)):
    """Member-allowed: operators may reflect a lot's working/done state without
    otherwise mutating the card (no bin / location changes)."""
    row = await _get_owned(session, card_id, ctx)
    row.status = body.status
    row.updatedAt = utcnow()
    await session.flush()
    _emit_card_update(session, ctx.company_id, row)
    return _to_card(row)


@router.delete("/{card_id}", status_code=204)
async def delete_card(card_id: str, ctx: CompanyContext = Depends(require_super_admin),
                      session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, card_id, ctx)
    await session.delete(row)
    await session.flush()
    _record_event(session, ctx.company_id, card_id, "deleted")
    _emit_card_delete(session, ctx.company_id, card_id)


# ─── Move / advance / unmerge ──────────────────────────────────────────────────

async def _split_factor(session, company_id, from_id: str, to_id: str) -> int:
    """How many downstream units one upstream unit becomes on this route.

    A **split** is a station with two or more outgoing routes: the weight says
    how many pieces each unit becomes (one steel bar cut into four tubes). A
    weight on a *merge feed* means the opposite — units consumed per assembly —
    and is applied when merging, so merge feeds never multiply here.
    """
    from_uuid, to_uuid = parse_uuid(from_id), parse_uuid(to_id)
    if from_uuid is None or to_uuid is None:
        return 1
    route = (await session.execute(
        select(RouteRow).where(
            RouteRow.companyId == company_id,
            RouteRow.load == from_uuid,
            RouteRow.unload == to_uuid,
        )
    )).scalars().first()
    if route is None or route.quantity <= 1:
        return 1
    incoming = (await session.execute(
        select(func.count()).select_from(RouteRow).where(
            RouteRow.companyId == company_id, RouteRow.unload == to_uuid)
    )).scalar_one()
    if incoming >= 2:
        return 1        # merge feed — the weight is consumed at the merge instead
    outgoing = (await session.execute(
        select(func.count()).select_from(RouteRow).where(
            RouteRow.companyId == company_id, RouteRow.load == from_uuid)
    )).scalar_one()
    return route.quantity if outgoing >= 2 else 1


async def _perform_bin_move(session, company_id, row: CardRow, from_id: str, to_id: str,
                            quantity: int, produced: int | None = None) -> Card:
    """Shift `quantity` units of a card between two of its bins, record the
    'moved' event, and fire the arrive/depart plugin notifications.

    `produced` (default: `quantity`) is how many units arrive at the target —
    larger when the route splits one unit into several pieces."""
    produced = quantity if produced is None else produced
    old_bins = dict(row.bins or {})
    from_count = old_bins.get(from_id, {}).get("count", 0)
    if quantity < 1 or quantity > from_count:
        raise HTTPException(400, f"Cannot move {quantity}: only {from_count} available at source")

    new_bins = dict(old_bins)
    new_from = from_count - quantity
    if new_from <= 0:
        new_bins.pop(from_id, None)
    else:
        new_bins[from_id] = {"count": new_from}
    to_count = old_bins.get(to_id, {}).get("count", 0)
    new_bins[to_id] = {"count": to_count + produced}

    row.bins = new_bins
    # Splitting creates pieces, so the lot grows; totalQuantity must keep
    # covering the bins (sum(bins) <= totalQuantity is the card invariant).
    if produced != quantity:
        in_bins = sum(b.get("count", 0) for b in new_bins.values())
        row.totalQuantity = max(row.totalQuantity + (produced - quantity), in_bins)
    row.updatedAt = utcnow()
    await session.flush()
    card = _to_card(row)
    card_id = str(row.id)

    _record_event(session, company_id, card_id, "moved",
                  fromStation=from_id, toStation=to_id, quantity=quantity)
    _emit_card_update(session, company_id, row)
    if from_count > 0 and new_from <= 0:
        await plugin_registry.notify_lot_depart(from_id, card_id)
    if to_count == 0:
        await plugin_registry.notify_lot_arrive(to_id, card_id, card.model_dump(mode="json"))
    return card


async def _record_order_progress(session, company_id, card_row: CardRow, to_station_id: str, quantity: int) -> None:
    """When order-tagged units arrive at a finished-goods leaf (a station with no
    outgoing routes = warehouse), credit the order and enqueue an outbox event
    in the same transaction."""
    if card_row.orderId is None:
        return
    to_uuid = parse_uuid(to_station_id)
    if to_uuid is None:
        return
    has_outgoing = (await session.execute(
        select(RouteRow.id).where(RouteRow.companyId == company_id, RouteRow.load == to_uuid).limit(1)
    )).first()
    if has_outgoing:
        return  # not a finished-goods location
    order = await session.get(OrderRow, card_row.orderId)
    if order is None or order.companyId != company_id or order.status in ("completed", "cancelled"):
        return
    order.quantityDone += quantity
    order.updatedAt = utcnow()
    completed = order.quantityDone >= order.quantity
    order.status = "completed" if completed else "in_progress"
    session.add(OutboxRow(
        companyId=company_id, orderId=order.id,
        eventType="order.completed" if completed else "order.progress",
        payload={
            "orderId": str(order.id), "source": order.source, "externalRef": order.externalRef,
            "productTemplateId": str(order.productTemplateId) if order.productTemplateId else None,
            "quantity": order.quantity, "quantityDone": order.quantityDone,
            "completed": completed, "stationId": to_station_id,
        },
    ))


class MoveBody(BaseModel):
    fromStationId: str
    toStationId:   str
    quantity:      int = 1


@router.post("/{card_id}/move", response_model=Card)
async def move_card(card_id: str, body: MoveBody, ctx: CompanyContext = Depends(require_super_admin),
                    session: AsyncSession = Depends(get_session)):
    """Super-admin lot-board drag: unconstrained move of units between any two
    bins (forward or backward along the graph — backward can trigger unmerge)."""
    row = await _get_owned(session, card_id, ctx, for_update=True)
    produced = body.quantity * await _split_factor(
        session, ctx.company_id, body.fromStationId, body.toStationId)
    card = await _perform_bin_move(session, ctx.company_id, row, body.fromStationId,
                                   body.toStationId, body.quantity, produced)
    await _record_order_progress(session, ctx.company_id, row, body.toStationId, produced)
    return card


class AdvanceBody(BaseModel):
    fromStationId: str
    toStationId:   str
    quantity:      int = 1


@router.post("/{card_id}/advance", response_model=Card)
async def advance_card(card_id: str, body: AdvanceBody,
                       ctx: CompanyContext = Depends(require_scope("cards:advance", session_role="user")),
                       session: AsyncSession = Depends(get_session)):
    """Operator (member-allowed) move: advance a lot to a station that is a valid
    downstream destination along a defined route. Unlike /move it is
    route-constrained, so operators can push work forward without gaining the
    ability to freely relocate lots.

    Also the **scan-to-advance** endpoint: a barcode scanner / print station
    authenticates with a `cards:advance` API key (no session) and hits this after
    reading a lot label, so the shop floor advances work without a logged-in UI."""
    row = await _get_owned(session, card_id, ctx, for_update=True)
    from_uuid = require_uuid(body.fromStationId, "Station not found")
    to_uuid = require_uuid(body.toStationId, "Station not found")
    route = (await session.execute(
        select(RouteRow).where(
            RouteRow.companyId == ctx.company_id,
            RouteRow.load == from_uuid,
            RouteRow.unload == to_uuid,
        )
    )).scalars().first()
    if route is None:
        raise HTTPException(400, "No route from the current station to the target station")
    produced = body.quantity * await _split_factor(
        session, ctx.company_id, body.fromStationId, body.toStationId)
    card = await _perform_bin_move(session, ctx.company_id, row, body.fromStationId,
                                   body.toStationId, body.quantity, produced)
    await _record_order_progress(session, ctx.company_id, row, body.toStationId, produced)
    return card


def _zpl_escape(s: str) -> str:
    # ^FD field data ends at ^FS; strip the caret/tilde control chars to be safe.
    return (s or "").replace("^", " ").replace("~", " ")[:40]


@router.get("/{card_id}/label", response_class=PlainTextResponse)
async def card_label(card_id: str,
                     ctx: CompanyContext = Depends(require_scope("cards:advance", session_role="user")),
                     session: AsyncSession = Depends(get_session)):
    """ZPL for a lot-card label (Zebra/Brother). The Code128 barcode encodes the
    card id, so scanning it and POSTing /cards/{id}/advance closes the
    print → move → scan-to-advance loop. `Accept: application/pdf`? No — this is
    raw ZPL sent straight to a label printer."""
    row = await _get_owned(session, card_id, ctx)
    tmpl = await session.get(LotTemplateRow, row.lotTemplateId)
    name = _zpl_escape(tmpl.name if tmpl else "Lot")
    # Current location = the bin holding the most units (a lot can straddle bins).
    bins = row.bins or {}
    loc = max(bins, key=lambda k: (bins[k] or {}).get("count", 0), default=None)
    loc_name = "—"
    if loc:
        st = await session.get(StationRow, parse_uuid(loc))
        loc_name = _zpl_escape(st.name if st else loc)
    zpl = (
        "^XA"
        "^CF0,40^FO30,30^FDTaktline Lot^FS"
        f"^CF0,32^FO30,90^FD{name}^FS"
        f"^CF0,28^FO30,140^FDQty {row.totalQuantity}   {_zpl_escape(row.status)}^FS"
        f"^CF0,28^FO30,180^FDAt: {loc_name}^FS"
        f"^FO30,230^BY2^BCN,110,Y,N,N^FD{row.id}^FS"
        "^XZ"
    )
    return PlainTextResponse(zpl, media_type="application/zpl")


class UnmergeBody(BaseModel):
    stationId: str
    quantity:  int = 1


@router.post("/{card_id}/unmerge")
async def unmerge_card(card_id: str, body: UnmergeBody, ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session)):
    """Reverse a merge: dissolve `quantity` assembly units of a lot at its merge
    station and recreate the precursor lots at each direct-upstream station
    (using each upstream station's originating template). This is what backward-
    dragging a merged assembly in the lot board triggers.

    The row lock makes a duplicated unmerge wait, re-read the already-dissolved
    card (gone or reduced), and fail cleanly — instead of both requests minting a
    full set of precursors (lot duplication)."""
    row = await _get_owned(session, card_id, ctx, for_update=True)
    station_uuid = require_uuid(body.stationId, "Station not found")

    incoming = (await session.execute(
        select(RouteRow).where(RouteRow.companyId == ctx.company_id, RouteRow.unload == station_uuid)
    )).scalars().all()
    if len(incoming) < 2:
        raise HTTPException(400, "Not a merge station — nothing to unmerge")

    tmpl = await session.get(LotTemplateRow, row.lotTemplateId)
    if tmpl is None or tmpl.startStationId != station_uuid:
        raise HTTPException(400, "This lot was not assembled at this station")

    have = (row.bins or {}).get(body.stationId, {}).get("count", 0)
    qty = body.quantity
    if qty < 1 or qty > have:
        raise HTTPException(400, f"Cannot unmerge {qty}: only {have} assembled units here")

    # Splitting a lot apart keeps its identity: every recreated precursor piece
    # inherits the assembly's lot code (they are the same physical material).
    # Only a legacy un-coded assembly gets a fresh shared code.
    inherit_num = row.lotNum or _gen_lot_code()

    # Remove the dissolved assemblies from this station.
    new_bins = dict(row.bins or {})
    remaining = have - qty
    if remaining <= 0:
        new_bins.pop(body.stationId, None)
    else:
        new_bins[body.stationId] = {"count": remaining}
    if not new_bins:
        await session.delete(row)
        _emit_card_delete(session, ctx.company_id, card_id)
    else:
        row.bins = new_bins
        row.updatedAt = utcnow()
        _emit_card_update(session, ctx.company_id, row)
    _record_event(session, ctx.company_id, card_id, "updated", note="unmerged")

    # Recreate each branch's precursor lot. Prefer the direct-upstream station's
    # originating template; if it has none, fall back to the leaf source queues
    # that feed that branch (the same recursion the merge "pull" uses).
    created: list[str] = []

    async def _spawn(station_id: str, template: LotTemplateRow, count: int) -> None:
        pre = CardRow(
            companyId=ctx.company_id, lotTemplateId=template.id, processId=row.processId,
            lotNum=inherit_num, totalQuantity=count, bins={station_id: {"count": count}},
            fields={}, flagged=False, description="", status="idle",
        )
        session.add(pre)
        await session.flush()
        created.append(str(pre.id))
        _record_event(session, ctx.company_id, str(pre.id), "created", note="unmerged")
        _emit_card_update(session, ctx.company_id, pre)

    for route in incoming:
        units = qty * max(1, route.quantity)
        up_tmpl = (await session.execute(
            select(LotTemplateRow).where(
                LotTemplateRow.companyId == ctx.company_id,
                LotTemplateRow.startStationId == route.load,
            )
        )).scalars().first()
        if up_tmpl is not None:
            await _spawn(str(route.load), up_tmpl, units)
        else:
            # Direct upstream has no template — recurse to its leaf source queues.
            for leaf in await _leaf_sources(session, ctx.company_id, route.load, units, route.processId):
                await _spawn(leaf["station_id"], leaf["template"], leaf["quantity"])

    return {"unmerged": qty, "createdCardIds": created}


# ─── Events / history ─────────────────────────────────────────────────────────

@router.get("/{card_id}/events", response_model=List[CardEvent])
async def get_card_events(card_id: str, ctx: CompanyContext = Depends(get_active_company),
                          session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(CardEventRow)
        .where(CardEventRow.cardId == card_id, CardEventRow.companyId == ctx.company_id)
        .order_by(CardEventRow.timestamp.asc())
    )).scalars().all()
    return [_to_event(r) for r in rows]
