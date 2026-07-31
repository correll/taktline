"""Production orders — release runs onto the floor (wrapping the pull), and
report completion via the integration outbox. This is the Taktline side of an
ERP integration; a connector service maps Odoo/NetSuite orders to these."""

import csv
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, require_uuid, parse_uuid
from ..db.tables import (
    Card as CardRow, IntegrationOutbox as OutboxRow, LotTemplate as LotTemplateRow,
    ProductionOrder as OrderRow, Route as RouteRow, Station as StationRow,
)
from ..deps.auth import CompanyContext, ensure_full_account, get_active_company, require_orders_access
from ..models.common import utcnow
from ..models.order import CancelByRef, OrderCreate, OrderPublic, OutboxEvent
from .cards import _record_event
from .merge import _incoming_routes, _leaf_sources, _gen_lot_code

router = APIRouter(prefix="/orders", tags=["orders"])


def _to_order(o: OrderRow) -> OrderPublic:
    return OrderPublic(
        id=str(o.id), source=o.source, externalRef=o.externalRef,
        productTemplateId=str(o.productTemplateId) if o.productTemplateId else None,
        mergeStationId=str(o.mergeStationId) if o.mergeStationId else None,
        quantity=o.quantity, quantityDone=o.quantityDone, status=o.status, note=o.note,
        attributes=o.attributes or {}, createdAt=o.createdAt, updatedAt=o.updatedAt,
    )


def _to_outbox(o: OutboxRow) -> OutboxEvent:
    return OutboxEvent(
        id=str(o.id), orderId=str(o.orderId) if o.orderId else None, eventType=o.eventType,
        payload=o.payload or {}, status=o.status, attempts=o.attempts, createdAt=o.createdAt,
    )


async def _resolve_process(session, company_id, station_uuid, tmpl) -> Optional[object]:
    if tmpl.processId:
        return tmpl.processId
    r = (await session.execute(
        select(RouteRow).where(
            RouteRow.companyId == company_id,
            or_(RouteRow.load == station_uuid, RouteRow.unload == station_uuid),
        ).limit(1)
    )).scalars().first()
    return r.processId if r else None


# ─── Orders ─────────────────────────────────────────────────────────────────────

async def _release_order(session, company_id, body: OrderCreate) -> tuple[OrderRow, bool]:
    """Create + release a pull order. Idempotent on (source, externalRef).
    Returns (order, created) — created is False when an existing order was reused."""
    if body.externalRef:
        existing = (await session.execute(
            select(OrderRow).where(
                OrderRow.companyId == company_id,
                OrderRow.source == body.source,
                OrderRow.externalRef == body.externalRef,
            )
        )).scalars().first()
        if existing:
            return existing, False   # already released — idempotent

    if body.quantity < 1:
        raise HTTPException(400, "quantity must be ≥ 1")

    tmpl = await session.get(LotTemplateRow, require_uuid(body.productTemplateId, "Product template not found"))
    if tmpl is None or tmpl.companyId != company_id:
        raise HTTPException(404, "Product template not found")

    target = parse_uuid(body.mergeStationId) if body.mergeStationId else tmpl.startStationId
    if target is None:
        raise HTTPException(400, "This product has no origination station; set mergeStationId")
    station = await session.get(StationRow, target)
    if station is None or station.companyId != company_id:
        raise HTTPException(404, "Origination station not found")

    order = OrderRow(
        companyId=company_id, source=body.source, externalRef=body.externalRef,
        productTemplateId=tmpl.id, mergeStationId=target, quantity=body.quantity,
        quantityDone=0, status="pending", note=body.note,
        attributes=body.attributes or {},
    )
    # The look-up above is not the guarantee — it is the fast path. Two
    # deliveries of the same webhook arriving together both find nothing, both
    # insert, and the unique index rejects one of them. That is the index doing
    # its job, but it surfaced as a 500 out of an endpoint whose contract is
    # "idempotent on (source, externalRef)", and a connector reading a 500 has
    # every reason to believe the release failed. A savepoint turns the loser
    # of that race into what it actually is: a re-post of an order that exists.
    try:
        async with session.begin_nested():
            session.add(order)
            await session.flush()
    except IntegrityError:
        if not body.externalRef:
            raise
        existing = (await session.execute(
            select(OrderRow).where(
                OrderRow.companyId == company_id,
                OrderRow.source == body.source,
                OrderRow.externalRef == body.externalRef,
            )
        )).scalars().first()
        if existing is None:
            raise
        return existing, False

    # The lot code comes from the ERP order: an explicit lotCode if the connector
    # sent one, else the externalRef, so every released Kanban card traces back to
    # its Odoo/Shopify/… order. Falls back to a generated code for bare manual
    # releases with neither. Capped for label printing.
    lot_code = ((body.lotCode or body.externalRef or "").strip() or None)
    if lot_code and len(lot_code) > 24:
        lot_code = lot_code[:24]

    # Scoped to the product's own process: a sibling process sharing the origin
    # station must neither trigger a pull nor have its queues seeded.
    process_id = await _resolve_process(session, company_id, target, tmpl)
    incoming = await _incoming_routes(session, company_id, target, process_id)
    if len(incoming) >= 1:
        # The product is made here — assembled at a merge, or yielded by an
        # upstream disassembly. Either way it cannot be conjured into existence
        # at its origin: the pull walks the graph back and seeds the leaf source
        # queues (ordering 8 modules orders the one pack they are torn from).
        sources = await _leaf_sources(session, company_id, target, body.quantity, process_id)
        if not sources:
            raise HTTPException(422, "No source queues feed this product")
        for src in sources:
            units = src["quantity"]
            await _spawn_lot(session, company_id, src["template"].id, process_id,
                             src["station_id"], units, order.id, lot_code,
                             fields=order.attributes)
    else:
        # True source product (its origin is a leaf queue) → mint it there.
        if process_id is None:
            raise HTTPException(422, "Cannot determine the process for this product")
        await _spawn_lot(session, company_id, tmpl.id, process_id, str(target),
                         body.quantity, order.id, lot_code, fields=order.attributes)

    order.status = "released"
    await session.flush()
    return order, True


@router.post("/", response_model=OrderPublic, status_code=201)
async def create_order(body: OrderCreate, response: Response,
                       ctx: CompanyContext = Depends(require_orders_access),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Create + release a production order. Idempotent on (source, externalRef).

    **201** when this call released the order, **200** when it returned one that
    already existed. A polling connector re-posts its whole open backlog every
    cycle, so without that distinction it cannot tell a real release from a
    redelivery and logs every order as new, forever.
    """
    ensure_full_account(ctx)   # sandbox: no order integrations
    order, created = await _release_order(session, ctx.company_id, body)
    if not created:
        response.status_code = 200
    return _to_order(order)


def _cell(row: dict, *names: str) -> str:
    """Case-insensitive column read across accepted header aliases."""
    lut = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
    for n in names:
        if lut.get(n):
            return lut[n]
    return ""


@router.post("/import")
async def import_orders(file: UploadFile = File(...),
                        ctx: CompanyContext = Depends(require_orders_access),
                        session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Bulk-release orders from a CSV — the no-API on-ramp for tools that can only
    export a spreadsheet. Header row required; columns (case-insensitive):

        product      template name OR id   (aliases: sku, template, productTemplateId)
        quantity     integer               (alias: qty)
        source       optional, default 'csv'
        externalRef  optional idempotency key (aliases: ref, reference)
        note         optional

    Each row releases in its own SAVEPOINT, so one bad row is reported and skipped
    without aborting the batch. Idempotent per (source, externalRef)."""
    ensure_full_account(ctx)   # sandbox: no order integrations
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")          # tolerate a UTF-8 BOM from Excel
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 encoded CSV")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV has no header row")

    templates = (await session.execute(
        select(LotTemplateRow).where(LotTemplateRow.companyId == ctx.company_id)
    )).scalars().all()
    by_id = {str(t.id): t for t in templates}
    by_name = {t.name.strip().lower(): t for t in templates}

    rows_out, released, duplicate, errors = [], 0, 0, 0
    for i, row in enumerate(reader, start=1):
        product = _cell(row, "product", "sku", "template", "producttemplateid")
        ref = _cell(row, "externalref", "ref", "reference") or None
        try:
            if not product:
                raise ValueError("missing product")
            tmpl = by_id.get(product) or by_name.get(product.lower())
            if tmpl is None:
                raise ValueError(f"unknown product {product!r}")
            qty_s = _cell(row, "quantity", "qty")
            try:
                qty = int(float(qty_s))
            except (ValueError, TypeError):
                raise ValueError(f"invalid quantity {qty_s!r}")
            known = {"product", "sku", "template", "producttemplateid", "quantity", "qty",
                     "source", "externalref", "ref", "reference", "note", "notes",
                     "lotcode", "lot", "lotnum"}
            extra = {k.strip(): v.strip() for k, v in row.items()
                     if k and k.strip().lower() not in known and v and v.strip()}
            body = OrderCreate(productTemplateId=str(tmpl.id), quantity=qty,
                               source=_cell(row, "source") or "csv",
                               externalRef=ref, note=_cell(row, "note", "notes"),
                               lotCode=_cell(row, "lotcode", "lot", "lotnum") or None,
                               attributes=extra)
            async with session.begin_nested():
                order, created = await _release_order(session, ctx.company_id, body)
            if created:
                released += 1
                rows_out.append({"row": i, "status": "released", "externalRef": ref, "orderId": str(order.id)})
            else:
                duplicate += 1
                rows_out.append({"row": i, "status": "duplicate", "externalRef": ref, "orderId": str(order.id)})
        except Exception as e:                   # noqa: BLE001 — per-row failure, batch continues
            errors += 1
            rows_out.append({"row": i, "status": "error", "externalRef": ref,
                             "error": str(getattr(e, "detail", e))})
    return {
        "summary": {"total": released + duplicate + errors, "released": released,
                    "duplicate": duplicate, "errors": errors},
        "rows": rows_out,
    }


async def _spawn_lot(session, company_id, template_id, process_id, station_id: str, count: int,
                     order_id, lot_code: str | None = None,
                     fields: dict | None = None) -> None:
    from .cards import _emit_card_update   # lazy: avoids an import cycle via merge

    card = CardRow(
        companyId=company_id, lotTemplateId=template_id, processId=process_id,
        lotNum=lot_code or _gen_lot_code(),
        totalQuantity=count, bins={station_id: {"count": count}},
        # The ERP's context travels ON the card — the physical Kanban card is
        # the one artefact guaranteed to be standing next to the material.
        fields=dict(fields or {}),
        orderId=order_id, status="idle",
    )
    session.add(card)
    await session.flush()
    _record_event(session, company_id, str(card.id), "created", note="order release")
    _emit_card_update(session, company_id, card)


@router.get("/", response_model=List[OrderPublic])
async def list_orders(ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(OrderRow).where(OrderRow.companyId == ctx.company_id).order_by(OrderRow.createdAt.desc())
    )).scalars().all()
    return [_to_order(o) for o in rows]


# ── Outbox (declared before /{order_id} so the literal path wins) ───────────────

MAX_DELIVERY_ATTEMPTS = 10


@router.get("/outbox", response_model=List[OutboxEvent])
async def list_outbox(status: Optional[str] = "pending", source: Optional[str] = None,
                      ctx: CompanyContext = Depends(require_orders_access),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Poll pending ERP-delivery events. A connector delivers, then acks.

    ``source`` restricts the page to events a given connector owns. Without it
    the oldest 500 pending rows are returned — and events no connector can ack
    (a manual UI release, a CSV import) stay pending forever, so once 500 of
    those accumulate they fill the window and a connector never sees its own
    completions again. Each connector passes its own source to stay clear of
    everyone else's backlog.
    """
    stmt = select(OutboxRow).where(OutboxRow.companyId == ctx.company_id)
    if status:
        stmt = stmt.where(OutboxRow.status == status)
    if source:
        stmt = stmt.where(OutboxRow.payload["source"].astext == source)
    rows = (await session.execute(stmt.order_by(OutboxRow.createdAt.asc()).limit(500))).scalars().all()
    return [_to_outbox(o) for o in rows]


@router.post("/outbox/{event_id}/ack", status_code=204)
async def ack_outbox(event_id: str, ctx: CompanyContext = Depends(require_orders_access),
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await session.get(OutboxRow, require_uuid(event_id, "Event not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Event not found")
    row.status = "delivered"
    row.attempts += 1
    row.deliveredAt = utcnow()


@router.post("/outbox/{event_id}/fail", status_code=200)
async def fail_outbox(event_id: str, ctx: CompanyContext = Depends(require_orders_access),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Record a failed delivery attempt. The event stays ``pending`` (and is
    retried) until :data:`MAX_DELIVERY_ATTEMPTS`, then parks as ``failed`` so a
    permanently undeliverable event — an ERP order deleted on their side — stops
    consuming a slot in every poll forever. Returns the row so a connector can
    log the give-up."""
    row = await session.get(OutboxRow, require_uuid(event_id, "Event not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Event not found")
    if row.status == "pending":
        row.attempts += 1
        if row.attempts >= MAX_DELIVERY_ATTEMPTS:
            row.status = "failed"
    await session.flush()
    return _to_outbox(row)


@router.get("/{order_id}", response_model=OrderPublic)
async def get_order(order_id: str, ctx: CompanyContext = Depends(get_active_company),
                    session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    o = await session.get(OrderRow, require_uuid(order_id, "Order not found"))
    if o is None or o.companyId != ctx.company_id:
        raise HTTPException(404, "Order not found")
    return _to_order(o)


async def _cancel_order(session, company_id, o: OrderRow) -> None:
    """Cancel + scrap in-flight lots + emit order.cancelled. No-op if already
    completed/cancelled (so redelivered ERP cancel/refund webhooks are safe)."""
    if o.status in ("completed", "cancelled"):
        return
    o.status = "cancelled"
    o.updatedAt = utcnow()
    from .cards import _emit_card_delete   # lazy: avoids an import cycle via merge

    scrap = (await session.execute(
        select(CardRow).where(CardRow.companyId == company_id, CardRow.orderId == o.id)
    )).scalars().all()
    for c in scrap:
        await session.delete(c)
        _emit_card_delete(session, company_id, str(c.id))
    session.add(OutboxRow(
        companyId=company_id, orderId=o.id, eventType="order.cancelled",
        payload={"orderId": str(o.id), "source": o.source, "externalRef": o.externalRef},
    ))


@router.post("/cancel", response_model=OrderPublic)
async def cancel_order_by_ref(body: CancelByRef, ctx: CompanyContext = Depends(require_orders_access),
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Cancel by (source, externalRef) — the Shopify/WooCommerce cancel & refund
    path, where the connector knows the shop's order id but not Taktline's."""
    o = (await session.execute(
        select(OrderRow).where(
            OrderRow.companyId == ctx.company_id,
            OrderRow.source == body.source,
            OrderRow.externalRef == body.externalRef,
        )
    )).scalars().first()
    if o is None:
        raise HTTPException(404, "Order not found")
    await _cancel_order(session, ctx.company_id, o)
    return _to_order(o)


@router.post("/{order_id}/cancel", response_model=OrderPublic)
async def cancel_order(order_id: str, ctx: CompanyContext = Depends(require_orders_access),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    o = await session.get(OrderRow, require_uuid(order_id, "Order not found"))
    if o is None or o.companyId != ctx.company_id:
        raise HTTPException(404, "Order not found")
    await _cancel_order(session, ctx.company_id, o)
    return _to_order(o)
