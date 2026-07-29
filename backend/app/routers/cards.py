from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import PlainTextResponse
from typing import List
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.ws_events import queue_event
from ..core.integrations import can_sink
from ..db.connection import SESSION_SCOPE, get_session, require_uuid, parse_uuid
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
from .merge import (_assembly_template, _boundary_station_ids, _ensure_origination_template,
                    _gen_lot_code, _incoming_routes, _leaf_sources, _precursor_template_ids)

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
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(CardRow).where(CardRow.companyId == ctx.company_id)
    )).scalars().all()
    return [_to_card(r) for r in rows]


@router.post("/", response_model=Card, status_code=201)
async def create_card(body: CardCreate, ctx: CompanyContext = Depends(require_admin),  # admin+ may create lots
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
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
    await _assert_units_stay_off_partner_nodes(session, ctx.company_id, data.get("bins", {}).keys())
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
                   session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    return _to_card(await _get_owned(session, card_id, ctx))


@router.put("/{card_id}", response_model=Card)
async def update_card(card_id: str, body: CardUpdate, ctx: CompanyContext = Depends(require_super_admin),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, card_id, ctx)
    if body.bins is not None:
        await _assert_units_stay_off_partner_nodes(session, ctx.company_id, body.bins.keys())
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
                             session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
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
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, card_id, ctx)
    await session.delete(row)
    await session.flush()
    _record_event(session, ctx.company_id, card_id, "deleted")
    _emit_card_delete(session, ctx.company_id, card_id)


# ─── Move / advance / unmerge ──────────────────────────────────────────────────

async def _split_branches(session, company_id, row: CardRow, from_id: str, to_id: str):
    """The branches of a split, or None when this is an ordinary 1:1 hop.

    Within one process a station with two or more outgoing routes is a **split**
    — a disassembly. One unit becomes a piece on *every* branch at once (a bar
    cut into four tubes plus an offcut), which is the exact mirror of a merge
    consuming one precursor per incoming branch. Alternative ("either/or")
    routing is modelled as a *separate process*, so branches are only ever
    counted within the card's own process.

    Only **source material** fans out. A card that already wears one of the
    branches' product templates IS a piece of a previous disassembly — you
    cannot take apart a module into modules — so it simply relocates along the
    chosen branch. Without this, setting two surplus modules aside to a spares
    warehouse would re-trigger the split: the two would be relabelled as the
    warehouse's product while two phantom modules were minted toward the merge
    — identity destroyed on one branch, material duplicated on the other.
    """
    from_uuid, to_uuid = parse_uuid(from_id), parse_uuid(to_id)
    if from_uuid is None or to_uuid is None:
        return None
    branches = list((await session.execute(
        select(RouteRow).where(
            RouteRow.companyId == company_id,
            RouteRow.load == from_uuid,
            RouteRow.processId == row.processId,
        )
    )).scalars().all())
    # A handoff link to an integration node is not a production branch. Counting
    # it made one production route + one handoff read as a split, and advancing
    # minted a piece onto the partner's node. The placement rules now refuse
    # that shape within a process in both creation orders, so this filter is
    # defense for data drawn before the rule existed.
    bound = await _boundary_station_ids(session, company_id)
    branches = [b for b in branches if b.unload not in bound]
    if len(branches) < 2 or not any(b.unload == to_uuid for b in branches):
        return None
    # Piece check — resolve each branch's product read-only (never provisioning:
    # a template that does not exist yet cannot be what this card wears).
    for branch in branches:
        if branch.outputTemplateId is not None:
            if branch.outputTemplateId == row.lotTemplateId:
                return None
            continue
        into_merge = await _is_merge_station(session, company_id, branch.unload, row.processId)
        tmpl_station = branch.load if into_merge else branch.unload
        exists = (await session.execute(
            select(LotTemplateRow.id).where(
                LotTemplateRow.companyId == company_id,
                LotTemplateRow.processId == row.processId,
                LotTemplateRow.startStationId == tmpl_station,
                LotTemplateRow.id == row.lotTemplateId,
            ).limit(1)
        )).first()
        if exists:
            return None
    return branches


async def _is_merge_station(session, company_id, station_uuid, process_id) -> bool:
    return (await session.execute(
        select(func.count()).select_from(RouteRow).where(
            RouteRow.companyId == company_id, RouteRow.unload == station_uuid,
            RouteRow.processId == process_id)
    )).scalar_one() >= 2


async def _perform_split(session, company_id, row: CardRow, from_id: str, to_id: str,
                         quantity: int, branches) -> Card:
    """Disassemble `quantity` units into a new lot on every branch.

    Each piece becomes its own card pinned to that branch's originating
    template — the mirror of a merge, where several precursor cards become one
    assembly card. Keeping them as separate cards is what lets a downstream
    merge tell the branches apart. The lot code carries through: the pieces are
    the same physical material."""
    old_bins = dict(row.bins or {})
    from_count = old_bins.get(from_id, {}).get("count", 0)
    if quantity < 1 or quantity > from_count:
        raise HTTPException(400, f"Cannot move {quantity}: only {from_count} available at source")

    source_id = str(row.id)
    inherit_num = row.lotNum or _gen_lot_code()
    order_id = row.orderId
    process_id = row.processId

    # Consume at the source; the card disappears once nothing of it is left.
    new_bins = dict(old_bins)
    remaining = from_count - quantity
    if remaining <= 0:
        new_bins.pop(from_id, None)
    else:
        new_bins[from_id] = {"count": remaining}
    _record_event(session, company_id, source_id, "updated",
                  fromStation=from_id, quantity=quantity, note="split")
    if not new_bins:
        await session.delete(row)
        _emit_card_delete(session, company_id, source_id)
    else:
        row.bins = new_bins
        row.totalQuantity = max(1, sum(b.get("count", 0) for b in new_bins.values()))
        row.updatedAt = utcnow()
        await session.flush()
        _emit_card_update(session, company_id, row)
    if remaining <= 0:
        await plugin_registry.notify_lot_depart(from_id, source_id)

    requested: Card | None = None
    for branch in branches:
        into_merge = await _is_merge_station(session, company_id, branch.unload, process_id)
        # On a merge feed the weight counts units consumed per assembly and is
        # applied at the merge, so the branch itself moves 1:1.
        units = quantity * (1 if into_merge else max(1, branch.quantity))
        # Which product the piece *is*. A disassembly yields different products
        # per branch (a battery → modules, busbars, cables), so the branch may
        # name its own output template. Without one we infer: normally the
        # target station's product, but for a branch landing on a merge station
        # the source's — the merge matches precursors by their template's
        # origin, and the target's own template is what it mints assemblies
        # with, so a piece wearing it would be invisible as a precursor and
        # would masquerade as finished output.
        if branch.outputTemplateId is not None:
            tmpl = await session.get(LotTemplateRow, branch.outputTemplateId)
        else:
            tmpl = None
        if tmpl is None:
            tmpl_station = branch.load if into_merge else branch.unload
            tmpl = await _ensure_origination_template(session, company_id, tmpl_station, process_id)
        piece = CardRow(
            companyId=company_id, lotTemplateId=tmpl.id, processId=process_id,
            lotNum=inherit_num, totalQuantity=units,
            bins={str(branch.unload): {"count": units}},
            # Pieces of a teardown are the same physical material wearing new
            # templates: the lot code, the order AND the ERP context all ride
            # along, or the customer's name falls off the card at the saw.
            fields=dict(row.fields or {}),
            flagged=False, description="", status="idle", orderId=order_id,
        )
        session.add(piece)
        await session.flush()
        piece_card = _to_card(piece)
        _record_event(session, company_id, str(piece.id), "created",
                      fromStation=from_id, toStation=str(branch.unload),
                      quantity=units, note="split")
        _emit_card_update(session, company_id, piece)
        await plugin_registry.notify_lot_arrive(
            str(branch.unload), str(piece.id), piece_card.model_dump(mode="json"))
        await _record_order_progress(session, company_id, piece, str(branch.unload), units)
        if str(branch.unload) == to_id:
            requested = piece_card
    return requested or piece_card


async def _perform_bin_move(session, company_id, row: CardRow, from_id: str, to_id: str,
                            quantity: int) -> Card:
    """Shift `quantity` units of a card between two of its bins, record the
    'moved' event, and fire the arrive/depart plugin notifications."""
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
    new_bins[to_id] = {"count": to_count + quantity}

    row.bins = new_bins
    # `status` is the work state *at the station the lot was worked at*, not a
    # property of the lot. Carrying 'done' along with the units made the next
    # station greet the worker with a finished-work screen for a lot nobody has
    # touched there — at a merge station that reads as "the assembly is ready"
    # when what actually arrived is one unmerged precursor. Timing already lives
    # in the work sessions, so clearing this loses nothing.
    if row.status != "idle":
        row.status = "idle"
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


async def _assert_units_stay_off_partner_nodes(session, company_id, station_ids) -> None:
    """Lots never sit on an integration node — that is the model's one hard rule
    about them, and it held everywhere except the three endpoints that place
    units at an arbitrary station. A handoff link is a real route row, so
    /advance would happily walk finished goods ONTO the ShipStation node —
    where they then credited the order as if arriving at an unbound leaf,
    bypassing the handoff and its sink-addressed event entirely. A scanner at
    the last station (scan-to-advance) would do this on every read.

    Moving OUT of a bound station is deliberately not refused: nothing should
    ever be there, but if something is, the rescue path must stay open.
    """
    ids = {u for u in (parse_uuid(str(sid)) for sid in station_ids) if u is not None}
    if not ids:
        return
    hit = ids & await _boundary_station_ids(session, company_id)
    if hit:
        st = await session.get(StationRow, next(iter(hit)))
        name = st.name if st else "that station"
        raise HTTPException(400,
            f"Lots never sit on {name} — it is the boundary to "
            f"{st.integrationProvider if st else 'a partner'}. Finished goods leave "
            f"through it with a handoff (\u201cSend to {name}\u201d), which consumes the lot.")


async def _assert_not_unmerged_precursor(session, company_id, row: CardRow, from_id: str) -> None:
    """Refuse to advance a precursor out of a station that assembles it.

    At a merge station the thing that leaves for the downstream is the assembly
    the merge minted, not the parts waiting to be consumed. Letting a precursor
    through pushes an unmerged part into finished goods wearing its own product
    identity — a motor booked as a finished e-bike — and quietly destroys the
    units it should have been merged with. The Operator view already hides
    precursors from the lot picker, but that is UX: this endpoint is also the
    public scan-to-advance API, so a scanner pointed at a precursor label would
    otherwise walk straight through the gate.
    """
    from_uuid = parse_uuid(from_id)
    if from_uuid is None:
        return
    # Judged on the topology of the card's OWN process, and nothing else.
    #
    # Within one process, two feeds converging on a station *is* a merge — that
    # is what a merge is. The shared-resource case people reach for (a paint
    # booth two lines send work through) is not a counter-example: that is two
    # *processes* sharing a physical location, and each of them has a single
    # feed into it, so this returns early below. Alternative routing is modelled
    # the same way, as a separate process.
    #
    # This used to also require that a product template already start here,
    # excused as protecting the paint booth. It protected nothing — process
    # scoping already did that — and it left a hole exactly where the product
    # is newest: until someone defines the assembly, every precursor could walk
    # straight out of the station that was supposed to consume it.
    incoming = await _incoming_routes(session, company_id, from_uuid, row.processId)
    if len(incoming) < 2:
        return                      # one feed in this process — ordinary pass-through
    precursor_ids: set = set()
    for route in incoming:
        precursor_ids.update(await _precursor_template_ids(session, company_id, route))
    if row.lotTemplateId in precursor_ids:
        raise HTTPException(
            409, "This lot is a precursor waiting to be merged here — merge it "
                 "into an assembly before moving it on.")


async def _sink_link(session, company_id, station_uuid) -> StationRow | None:
    """The integration location this station hands finished goods to, if any.

    The link is an ordinary route drawn on the map, but it carries no material:
    a lot is *consumed* across it by an explicit handoff ("Send to ShipStation"),
    never walked onto the partner's node.
    """
    rows = (await session.execute(
        select(StationRow).join(RouteRow, RouteRow.unload == StationRow.id)
        .where(RouteRow.companyId == company_id, RouteRow.load == station_uuid,
               StationRow.integrationProvider.isnot(None))
    )).scalars().all()
    for st in rows:
        if can_sink(st.integrationProvider, st.integrationRole):
            return st
    return None


async def _record_order_progress(session, company_id, card_row: CardRow, to_station_id: str, quantity: int) -> None:
    """When order-tagged units arrive at a finished-goods leaf (a station with no
    outgoing routes = warehouse), credit the order and enqueue an outbox event
    in the same transaction.

    A location wired to an integration sink is deliberately *not* credited on
    arrival: there, finishing is an act someone performs ("Send back to Odoo"),
    and crediting here as well would count every unit twice."""
    if card_row.orderId is None:
        return
    to_uuid = parse_uuid(to_station_id)
    if to_uuid is None:
        return
    if await _sink_link(session, company_id, to_uuid) is not None:
        return  # handed over explicitly, not on arrival
    has_outgoing = (await session.execute(
        select(RouteRow.id).where(RouteRow.companyId == company_id,
                                  RouteRow.processId == card_row.processId,
                                  RouteRow.load == to_uuid).limit(1)
    )).first()
    if has_outgoing:
        return  # not a finished-goods location
    order = await session.get(OrderRow, card_row.orderId)
    if order is None or order.companyId != company_id or order.status in ("completed", "cancelled"):
        return
    await _credit_order(session, company_id, order, to_station_id, quantity,
                        sink=None, lot_code=card_row.lotNum)


async def _credit_order(session, company_id, order: OrderRow, at_station_id: str,
                        quantity: int, sink: StationRow | None,
                        lot_code: str | None = None) -> None:
    """Credit progress and enqueue the delivery event(s).

    The payload must let a sink act without a second round-trip: the ERP's ref
    and its own attributes come back out (a shipper needs the ship-to the store
    sent in), the lot code identifies the physical material, and ``units`` says
    how many crossed the boundary in THIS event — quantityDone is cumulative
    and useless for building one shipment."""
    order.quantityDone += quantity
    order.updatedAt = utcnow()
    completed = order.quantityDone >= order.quantity
    order.status = "completed" if completed else "in_progress"
    to_station_id = at_station_id

    # Who needs to hear about this?
    #
    # The connector that released the order always does — that is the existing
    # behaviour and every line built before integration locations keeps working
    # unchanged. But the place the goods actually left through may belong to a
    # *different* partner (released from Shopify, shipped via ShipStation), and
    # that partner needs telling too. So the event fans out to both.
    #
    # This is also what rescues a manual or CSV release that lands on a bound
    # dock: its own event carries source='manual' and no connector can ever ack
    # it, but the dock's copy is addressed to a connector that can.
    sink_provider = sink.integrationProvider if sink is not None else None
    base = {
        "orderId": str(order.id), "externalRef": order.externalRef,
        "productTemplateId": str(order.productTemplateId) if order.productTemplateId else None,
        "quantity": order.quantity, "quantityDone": order.quantityDone,
        "units": quantity,
        "lotCode": lot_code,
        "attributes": dict(order.attributes or {}),
        "completed": completed, "stationId": to_station_id,
    }
    event_type = "order.completed" if completed else "order.progress"
    # dict.fromkeys keeps insertion order and drops the duplicate when the
    # releasing connector *is* the one that owns the dock.
    for audience in dict.fromkeys(a for a in (order.source, sink_provider) if a):
        session.add(OutboxRow(
            companyId=company_id, orderId=order.id, eventType=event_type,
            payload={**base, "source": audience,
                     # Which partner's location it physically left through —
                     # null when it was an ordinary unbound finished-goods leaf.
                     "sinkProvider": sink_provider},
        ))


class MoveBody(BaseModel):
    fromStationId: str
    toStationId:   str
    quantity:      int = 1



async def _is_forward_move(session, company_id, row: CardRow, from_id: str, to_id: str) -> bool:
    """Is there a production route carrying work from here to there?

    Used to tell "pushing this onward" from "putting it back" — the board's
    drag does both, and only the first should be gated at a merge."""
    from_uuid, to_uuid = parse_uuid(from_id), parse_uuid(to_id)
    if from_uuid is None or to_uuid is None:
        return False
    hit = (await session.execute(
        select(RouteRow.id).where(RouteRow.companyId == company_id,
                                  RouteRow.processId == row.processId,
                                  RouteRow.load == from_uuid,
                                  RouteRow.unload == to_uuid).limit(1)
    )).first()
    return hit is not None


async def _unsplit_back(session, company_id, row: CardRow, from_id: str, to_id: str,
                        quantity: int):
    """Moving pieces back onto the location they were cut from re-forms the lot.

    A split is not a move, it is a transformation: one bar becomes four tubes
    *and* an offcut, all at once. Dragging the tubes back therefore cannot be a
    plain move — it has to undo the transformation, which means two things a
    bare move got wrong.

    It divided nothing: four tubes went back as **four bars**, because the
    branch weight was ignored on the way back though it was applied on the way
    out. And it left the offcut standing on its own branch, still wearing the
    lot code of a bar that now exists again. Advance that bar and you get four
    more tubes and a second offcut — every round trip minting material out of
    nothing, which is exactly what a Kanban system exists to make impossible.

    So: the pieces on *every* branch are consumed in the ratio the weights
    describe, and one source lot is re-formed. Returns None when this is not a
    move back into a split, leaving the ordinary path to handle it.
    """
    to_uuid, from_uuid = parse_uuid(to_id), parse_uuid(from_id)
    if to_uuid is None or from_uuid is None:
        return None
    branches = await _outgoing_routes_for_split(session, company_id, to_uuid, row.processId)
    if len(branches) < 2:
        return None
    mine = next((r for r in branches if r.unload == from_uuid), None)
    if mine is None:
        return None                       # not coming back down one of the branches

    weight = max(1, mine.quantity or 1)
    if quantity % weight != 0:
        raise HTTPException(400,
            f"{quantity} does not re-form whole units: this branch yields {weight} per unit, "
            f"so move back a multiple of {weight}.")
    units = quantity // weight

    # Every sibling branch has to give back its share, or the ratio is broken
    # and the leftovers become material that was never made.
    consumed: list[tuple[CardRow, int]] = []
    for branch in branches:
        if branch.unload == from_uuid:
            continue
        need = units * max(1, branch.quantity or 1)
        pool = (await session.execute(
            select(CardRow).where(CardRow.companyId == company_id,
                                  CardRow.processId == row.processId)
            .with_for_update()
        )).scalars().all()
        # Twins first: the pieces carrying this lot's code are the ones that
        # came off the same source unit. Only then anything else on the branch.
        at_branch = [c for c in pool if (c.bins or {}).get(str(branch.unload), {}).get("count", 0) > 0]
        at_branch.sort(key=lambda c: (c.lotNum != row.lotNum, c.createdAt or utcnow()))
        remaining = need
        for cand in at_branch:
            if remaining <= 0:
                break
            have = (cand.bins or {}).get(str(branch.unload), {}).get("count", 0)
            take = min(have, remaining)
            consumed.append((cand, take))
            remaining -= take
        if remaining > 0:
            station = await session.get(StationRow, branch.unload)
            raise HTTPException(400,
                f"Re-forming {units} unit{'s' if units != 1 else ''} needs {need} at "
                f"{station.name if station else 'the other branch'}, and only {need - remaining} "
                f"{'is' if need - remaining == 1 else 'are'} there. The pieces a split produced "
                "have to go back together.")

    # Take this branch's pieces off the card that was dragged.
    _take_units(row, from_id, quantity)
    if not (row.bins or {}):
        await session.delete(row)
        _emit_card_delete(session, company_id, str(row.id))
    else:
        row.updatedAt = utcnow()
        _emit_card_update(session, company_id, row)

    for cand, take in consumed:
        _take_units(cand, str(_branch_station_of(branches, cand)), take)
        if not (cand.bins or {}):
            await session.delete(cand)
            _emit_card_delete(session, company_id, str(cand.id))
        else:
            cand.updatedAt = utcnow()
            _emit_card_update(session, company_id, cand)

    tmpl = await _ensure_origination_template(session, company_id, to_uuid, row.processId)
    reformed = CardRow(
        companyId=company_id, lotTemplateId=tmpl.id, processId=row.processId,
        lotNum=row.lotNum or _gen_lot_code(), totalQuantity=units,
        bins={to_id: {"count": units}},
        fields=dict(row.fields or {}), flagged=False, description="",
        status="idle", orderId=row.orderId,
    )
    session.add(reformed)
    await session.flush()
    _record_event(session, company_id, str(reformed.id), "created",
                  fromStation=from_id, toStation=to_id, quantity=units, note="unsplit")
    _emit_card_update(session, company_id, reformed)
    return _to_card(reformed)


def _take_units(card: CardRow, station_id: str, n: int) -> None:
    bins = dict(card.bins or {})
    left = bins.get(station_id, {}).get("count", 0) - n
    if left <= 0:
        bins.pop(station_id, None)
    else:
        bins[station_id] = {"count": left}
    card.bins = bins
    card.totalQuantity = max(1, card.totalQuantity - n)


def _branch_station_of(branches, card: CardRow):
    """Which branch station this card is standing on."""
    for b in branches:
        if (card.bins or {}).get(str(b.unload), {}).get("count", 0) > 0:
            return b.unload
    return None


async def _outgoing_routes_for_split(session, company_id, station_uuid, process_id):
    """Production routes out of a station, within its process — boundary links
    to an integration are not branches of anything."""
    rows = (await session.execute(
        select(RouteRow).where(RouteRow.companyId == company_id,
                               RouteRow.load == station_uuid,
                               RouteRow.processId == process_id)
    )).scalars().all()
    bound = set((await session.execute(
        select(StationRow.id).where(StationRow.companyId == company_id,
                                    StationRow.integrationProvider.isnot(None))
    )).scalars().all())
    return [r for r in rows if r.unload not in bound]



@router.post("/{card_id}/move", response_model=Card)
async def move_card(card_id: str, body: MoveBody, ctx: CompanyContext = Depends(require_super_admin),
                    session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Super-admin lot-board drag: unconstrained move of units between any two
    bins (forward or backward along the graph — backward can trigger unmerge)."""
    row = await _get_owned(session, card_id, ctx, for_update=True)
    await _assert_units_stay_off_partner_nodes(session, ctx.company_id, [body.toStationId])
    # The board drag is unconstrained on purpose — backwards, sideways, to fix a
    # mistake — but pushing a precursor *onward* out of the station that
    # assembles it is not a correction, it is the same lie /advance already
    # refuses: an unmerged motor booked as a finished e-bike, and the units it
    # should have been merged with quietly stranded. Only forward moves are
    # gated, so dragging back to undo still works.
    if await _is_forward_move(session, ctx.company_id, row, body.fromStationId,
                              body.toStationId):
        await _assert_not_unmerged_precursor(session, ctx.company_id, row, body.fromStationId)
    # Coming back down a split branch undoes the split rather than moving units.
    reformed = await _unsplit_back(session, ctx.company_id, row, body.fromStationId,
                                   body.toStationId, body.quantity)
    if reformed is not None:
        return reformed
    branches = await _split_branches(session, ctx.company_id, row, body.fromStationId,
                                     body.toStationId)
    if branches is not None:
        return await _perform_split(session, ctx.company_id, row, body.fromStationId,
                                    body.toStationId, body.quantity, branches)
    card = await _perform_bin_move(session, ctx.company_id, row, body.fromStationId,
                                   body.toStationId, body.quantity)
    await _record_order_progress(session, ctx.company_id, row, body.toStationId, body.quantity)
    return card


class AdvanceBody(BaseModel):
    fromStationId: str
    toStationId:   str
    quantity:      int = 1


@router.post("/{card_id}/advance", response_model=Card)
async def advance_card(card_id: str, body: AdvanceBody,
                       ctx: CompanyContext = Depends(require_scope("cards:advance", session_role="user")),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
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
    await _assert_units_stay_off_partner_nodes(session, ctx.company_id, [body.toStationId])
    # The route must belong to the card's own process: routes of a sibling
    # process sharing these stations are a different value stream, and riding
    # one would teleport the lot out of its own flow.
    route = (await session.execute(
        select(RouteRow).where(
            RouteRow.companyId == ctx.company_id,
            RouteRow.processId == row.processId,
            RouteRow.load == from_uuid,
            RouteRow.unload == to_uuid,
        )
    )).scalars().first()
    if route is None:
        raise HTTPException(400, "No route from the current station to the target station")
    await _assert_not_unmerged_precursor(session, ctx.company_id, row, body.fromStationId)
    branches = await _split_branches(session, ctx.company_id, row, body.fromStationId,
                                     body.toStationId)
    if branches is not None:
        return await _perform_split(session, ctx.company_id, row, body.fromStationId,
                                    body.toStationId, body.quantity, branches)
    card = await _perform_bin_move(session, ctx.company_id, row, body.fromStationId,
                                   body.toStationId, body.quantity)
    await _record_order_progress(session, ctx.company_id, row, body.toStationId, body.quantity)
    return card


def _zpl_escape(s: str) -> str:
    # ^FD field data ends at ^FS; strip the caret/tilde control chars to be safe.
    return (s or "").replace("^", " ").replace("~", " ")[:40]


@router.get("/{card_id}/label", response_class=PlainTextResponse)
async def card_label(card_id: str,
                     ctx: CompanyContext = Depends(require_scope("cards:advance", session_role="user")),
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
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


class HandoffBody(BaseModel):
    fromStationId:        str
    integrationStationId: str
    quantity:             int = 1


@router.post("/{card_id}/handoff", response_model=dict)
async def handoff_card(card_id: str, body: HandoffBody,
                       ctx: CompanyContext = Depends(require_scope("cards:advance", session_role="user")),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Hand finished goods to an integration partner — "Send back to Odoo",
    "Send to ShipStation".

    This is where a lot **leaves Taktline**, and it is deliberately an act
    someone performs rather than something that happens because a card arrived
    somewhere. Shipping is a decision: the goods are packed, the paperwork is
    right, and only then does the ERP get told. Crediting on arrival instead
    would report work finished while it was still sitting on a bench.

    The units are consumed here — the partner's node never holds cards, it is
    the far side of the boundary — and the order is credited with the delivery
    event addressed to that partner (plus the connector that released the
    order, when it is a different one).
    """
    row = await _get_owned(session, card_id, ctx, for_update=True)
    from_uuid = require_uuid(body.fromStationId, "Station not found")
    dest_uuid = require_uuid(body.integrationStationId, "Station not found")
    if body.quantity < 1:
        raise HTTPException(400, "Quantity must be at least 1")

    dest = await session.get(StationRow, dest_uuid)
    if dest is None or dest.companyId != ctx.company_id:
        raise HTTPException(404, "Station not found")
    if not can_sink(dest.integrationProvider, dest.integrationRole):
        raise HTTPException(400, "That station does not accept finished goods")

    # The link has to be drawn: a lot can only leave through a partner this
    # location actually hands off to.
    link = (await session.execute(
        select(RouteRow.id).where(RouteRow.companyId == ctx.company_id,
                                  RouteRow.load == from_uuid,
                                  RouteRow.unload == dest_uuid).limit(1)
    )).first()
    if link is None:
        raise HTTPException(400, "No handoff link from this station to that integration")

    bins = dict(row.bins or {})
    have = bins.get(body.fromStationId, {}).get("count", 0)
    if body.quantity > have:
        raise HTTPException(400, f"Cannot send {body.quantity}: only {have} here")

    remaining = have - body.quantity
    if remaining <= 0:
        bins.pop(body.fromStationId, None)
    else:
        bins[body.fromStationId] = {"count": remaining}

    order = await session.get(OrderRow, row.orderId) if row.orderId else None
    provider = dest.integrationProvider
    # Captured before the delete below — reading a deleted ORM object's
    # attributes works today but is an implementation detail, not a contract.
    handed = {"lotNum": row.lotNum, "templateId": str(row.lotTemplateId),
              "fields": dict(row.fields or {})}

    if not bins:
        await session.delete(row)
        _emit_card_delete(session, ctx.company_id, card_id)
    else:
        row.bins = bins
        row.totalQuantity = max(1, row.totalQuantity - body.quantity)
        row.updatedAt = utcnow()
        _emit_card_update(session, ctx.company_id, row)
    _record_event(session, ctx.company_id, card_id, "deleted",
                  fromStation=body.fromStationId, quantity=body.quantity,
                  note=f"handed off to {provider}")
    await plugin_registry.notify_lot_depart(body.fromStationId, card_id)

    if order is not None and order.companyId == ctx.company_id \
            and order.status not in ("completed", "cancelled"):
        await _credit_order(session, ctx.company_id, order, body.fromStationId,
                            body.quantity, sink=dest, lot_code=handed["lotNum"])
    else:
        # No order — a lot someone made by hand, or surplus set aside — but the
        # partner still received physical goods and still needs telling. A
        # `lot.handoff` event, addressed to the sink's connector; connectors
        # that only understand order events drain-and-ack it harmlessly (the
        # core skips unknown types), so this is additive on the wire.
        session.add(OutboxRow(
            companyId=ctx.company_id, orderId=None, eventType="lot.handoff",
            payload={
                "source": provider, "sinkProvider": provider,
                "externalRef": None, "stationId": body.fromStationId,
                "units": body.quantity, "lotCode": handed["lotNum"],
                "templateId": handed["templateId"],
                "attributes": handed["fields"],
            },
        ))

    return {"sentTo": provider, "quantity": body.quantity,
            "orderId": str(order.id) if order else None,
            "orderStatus": order.status if order else None}


class UnmergeBody(BaseModel):
    stationId: str
    quantity:  int = 1


@router.post("/{card_id}/unmerge")
async def unmerge_card(card_id: str, body: UnmergeBody, ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Reverse a merge: dissolve `quantity` assembly units of a lot at its merge
    station and recreate the precursor lots at each direct-upstream station
    (using each upstream station's originating template). This is what backward-
    dragging a merged assembly in the lot board triggers.

    The row lock makes a duplicated unmerge wait, re-read the already-dissolved
    card (gone or reduced), and fail cleanly — instead of both requests minting a
    full set of precursors (lot duplication)."""
    row = await _get_owned(session, card_id, ctx, for_update=True)
    station_uuid = require_uuid(body.stationId, "Station not found")

    # The assembly dissolves along its OWN process's feeds — a sibling process
    # sharing this station contributes no branches (and must gain no lots).
    incoming = (await session.execute(
        select(RouteRow).where(RouteRow.companyId == ctx.company_id,
                               RouteRow.processId == row.processId,
                               RouteRow.unload == station_uuid)
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
            # Same material going backwards: order attribution and ERP context
            # survive the dissolve, exactly as they survive the merge. Dropping
            # the orderId here would strand the order at partially-done forever
            # if the assembly is later rebuilt and shipped.
            fields=dict(row.fields or {}), orderId=row.orderId,
            flagged=False, description="", status="idle",
        )
        session.add(pre)
        await session.flush()
        created.append(str(pre.id))
        _record_event(session, ctx.company_id, str(pre.id), "created", note="unmerged")
        _emit_card_update(session, ctx.company_id, pre)

    for route in incoming:
        units = qty * max(1, route.quantity)
        # A disassembly feed names its product (battery → cable): the precursor
        # this branch consumed wore THAT template, so it is what comes back.
        up_tmpl = None
        if route.outputTemplateId is not None:
            up_tmpl = await session.get(LotTemplateRow, route.outputTemplateId)
        if up_tmpl is None:
            up_tmpl = (await session.execute(
                select(LotTemplateRow).where(
                    LotTemplateRow.companyId == ctx.company_id,
                    LotTemplateRow.processId == row.processId,
                    LotTemplateRow.startStationId == route.load,
                ).order_by(LotTemplateRow.createdAt.asc())
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
                          session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(CardEventRow)
        .where(CardEventRow.cardId == card_id, CardEventRow.companyId == ctx.company_id)
        .order_by(CardEventRow.timestamp.asc())
    )).scalars().all()
    return [_to_event(r) for r in rows]
