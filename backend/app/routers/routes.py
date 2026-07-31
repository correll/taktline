from fastapi import APIRouter, HTTPException, Depends
from typing import List
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, require_uuid, parse_uuid, optional_uuid
from ..db.tables import (Route as RouteRow, Process as ProcessRow, Station as StationRow,
                         LotTemplate as LotTemplateRow)
from ..deps.auth import CompanyContext, get_active_company, require_super_admin
from ..models.route import Route, RouteCreate, RouteUpdate
from ..models.common import utcnow

router = APIRouter(prefix="/routes", tags=["routes"])


def _to_route(r: RouteRow) -> Route:
    return Route(
        _id=str(r.id),
        processId=str(r.processId),
        load=str(r.load),
        unload=str(r.unload),
        quantity=r.quantity,
        outputTemplateId=str(r.outputTemplateId) if r.outputTemplateId else None,
        createdAt=r.createdAt,
        updatedAt=r.updatedAt,
    )


def _req_fk(value: str):
    parsed = parse_uuid(value)
    if parsed is None:
        raise HTTPException(400, f"Invalid id: {value!r}")
    return parsed


async def _get_owned(session: AsyncSession, route_id: str, ctx: CompanyContext) -> RouteRow:
    row = await session.get(RouteRow, require_uuid(route_id, "Route not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Route not found")
    return row


async def _assert_in_company(session, model, ids, company_id, what):
    """Every id must reference a row of `model` owned by company_id."""
    for i in ids:
        row = await session.get(model, i)
        if row is None or row.companyId != company_id:
            raise HTTPException(400, f"Referenced {what} does not exist in this company")


async def _process_edges(session, company_id, process_uuid, exclude_id=None) -> list[tuple[str, str]]:
    """Production edges of a process, for the cycle check.

    Boundary links are left out. An ERP that both raises demand against a queue
    and takes the finished goods back is a *loop through the outside world*, not
    a loop in the flow — material goes queue → line → Odoo exactly once and
    never comes round again. Counting those edges made the commonest ERP wiring
    there is (Odoo in, Odoo out) impossible to draw."""
    stmt = select(RouteRow).where(
        RouteRow.companyId == company_id, RouteRow.processId == process_uuid
    )
    if exclude_id is not None:
        stmt = stmt.where(RouteRow.id != exclude_id)
    rows = (await session.execute(stmt)).scalars().all()
    bound = set((await session.execute(
        select(StationRow.id).where(StationRow.companyId == company_id,
                                    StationRow.integrationProvider.isnot(None))
    )).scalars().all())
    return [(str(r.load), str(r.unload)) for r in rows
            if r.load not in bound and r.unload not in bound]


def _would_create_cycle(edges, new_load: str, new_unload: str) -> bool:
    adj: dict[str, list[str]] = {}
    for load, unload in edges:
        adj.setdefault(load, []).append(unload)
    adj.setdefault(new_load, []).append(new_unload)
    visited: set[str] = set()
    stack = [new_unload]
    while stack:
        node = stack.pop()
        if node == new_load:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adj.get(node, []))
    return False


async def _check_boundary_placement(session, company_id, process_uuid,
                                    load_uuid, unload_uuid) -> None:
    """Where an integration may attach to a process's flow.

    Everything here is judged **within the route's own process** — the same
    scoping every other graph judgement obeys. An earlier version read the
    station's routes across all processes, which broke the moment two value
    streams shared a station.

    * A **demand link** (integration → station) lands somewhere the line can
      answer it: either the location where the ordered product is *made in this
      process*, or a station the line already **feeds** — which is what
      ordering into stock means, and is the same test the board's "pull
      precursors" button uses. (Checked only once this process has products, so
      a line can be drawn before its products are named.) The link is
      documentary: a release keys off the order's own product template, never
      off this edge.

    * **Partner → partner** is refused outright. No material crosses an edge
      between two integrations.

    * A **handoff link** (station → integration) may only leave the **end of
      this process's flow** — a station that sends work nowhere else *in this
      process*. Ship-or-stock is not an exception, it is two processes: one
      pulled by the warehouse (make-to-stock, completing on arrival there) and
      one pulled by the shipper (make-to-order, completing at the handoff).
      The same physical QA bench carries both; each process's flow through it
      stays deterministic. An earlier version special-cased onward routes to
      storage instead, which smuggled an either/or into a single process —
      exactly what the separate-process convention exists to prevent.

    * The mirror: once a process hands off at a station, that station is the
      end of that process's flow, so adding an onward production route to it
      *in the same process* is refused with the same advice.
    """
    load = await session.get(StationRow, load_uuid)
    unload = await session.get(StationRow, unload_uuid)
    bound = set((await session.execute(
        select(StationRow.id).where(StationRow.companyId == company_id,
                                    StationRow.integrationProvider.isnot(None))
    )).scalars().all())

    # Two partners with a line between them is not flow of any kind: no material
    # crosses it, and Taktline has nothing to contribute to two external systems talking
    # to each other. Whatever was meant is already expressible as demand into the
    # station that makes the product, plus a handoff out of the last one.
    if (load is not None and load.integrationProvider
            and unload is not None and unload.integrationProvider):
        raise HTTPException(400,
            f"{load.name} and {unload.name} are both integrations, so no material moves "
            f"along this link — it would draw a line on the floor plan that nothing "
            f"travels. Connect {load.name} to the station whose product it orders, and "
            f"connect the station that finishes the work to {unload.name}.")

    if load is not None and load.integrationProvider:      # a link carrying demand
        any_templates = (await session.execute(
            select(LotTemplateRow.id)
            .where(LotTemplateRow.companyId == company_id,
                   LotTemplateRow.processId == process_uuid).limit(1)
        )).first()
        if any_templates is None:
            return                                          # no products in this process yet
        makes_a_product = (await session.execute(
            select(LotTemplateRow.id).where(
                LotTemplateRow.companyId == company_id,
                LotTemplateRow.processId == process_uuid,
                LotTemplateRow.startStationId == unload_uuid).limit(1)
        )).first()
        # …or the station is simply somewhere the line already feeds. Pressing
        # "pull precursors" there walks the graph back and seeds the source
        # queues, so it is a place demand can be raised — which is exactly what
        # ordering **into stock** is: an ERP asking for finished goods to be put
        # on a warehouse shelf. The board offered that button at a warehouse
        # while this check refused the link to the same station, so the app
        # disagreed with itself about one station; the button was right.
        feeds = (await session.execute(
            select(RouteRow.load).where(RouteRow.companyId == company_id,
                                        RouteRow.processId == process_uuid,
                                        RouteRow.unload == unload_uuid)
        )).scalars().all()
        is_pull_point = any(f not in bound for f in feeds)
        if makes_a_product is None and not is_pull_point:
            where = unload.name if unload else "that station"
            raise HTTPException(400,
                f"An order from {load.name} has to land somewhere the line can answer it. "
                f"Connect it either to the station where the ordered product is made, or to "
                f"one the line already feeds — a warehouse, for stock. {where} is neither: "
                f"no product of this process starts there and nothing upstream feeds it.")

    if unload is not None and unload.integrationProvider:   # a link carrying finished goods
        onward = (await session.execute(
            select(RouteRow.unload).where(RouteRow.companyId == company_id,
                                          RouteRow.processId == process_uuid,
                                          RouteRow.load == load_uuid)
        )).scalars().all()
        onward_flow = [d for d in onward if d not in bound]
        if onward_flow:
            nxt = await session.get(StationRow, onward_flow[0])
            raise HTTPException(400,
                f"Finished goods leave through {unload.name}, so connect it to the last "
                f"station of this process — {load.name if load else 'that station'} still "
                f"sends work on to {nxt.name if nxt else 'another station'} here. To both "
                f"ship and stock, model each destination as its own process.")

    if (load is not None and not load.integrationProvider
            and unload is not None and not unload.integrationProvider):
        # ordinary production route: its source must not already be this
        # process's handoff point
        handoff = (await session.execute(
            select(StationRow).join(RouteRow, RouteRow.unload == StationRow.id)
            .where(RouteRow.companyId == company_id,
                   RouteRow.processId == process_uuid,
                   RouteRow.load == load_uuid,
                   StationRow.integrationProvider.isnot(None)).limit(1)
        )).scalars().first()
        if handoff is not None:
            raise HTTPException(400,
                f"{load.name} already hands finished goods to {handoff.name} in this "
                f"process, so it is the end of this flow. To also send work to "
                f"{unload.name}, model that destination as its own process.")


@router.get("/", response_model=List[Route])
async def list_routes(ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(RouteRow).where(RouteRow.companyId == ctx.company_id)
    )).scalars().all()
    return [_to_route(r) for r in rows]


async def _other_incoming_count(session, company_id, unload_uuid, exclude_id=None,
                                process_id=None) -> int:
    """How many routes (other than exclude_id) feed this station within the
    same process — a sibling process's feed into a shared station is a
    different value stream, not a merge partner."""
    stmt = select(func.count()).select_from(RouteRow).where(
        RouteRow.companyId == company_id, RouteRow.unload == unload_uuid)
    if exclude_id is not None:
        stmt = stmt.where(RouteRow.id != exclude_id)
    if process_id is not None:
        stmt = stmt.where(RouteRow.processId == process_id)
    return (await session.execute(stmt)).scalar_one()


async def _other_outgoing_count(session, company_id, load_uuid, exclude_id=None,
                                process_id=None) -> int:
    """How many routes (other than exclude_id) leave this station within the
    same process — alternative routings live in their own process, so they are
    not siblings of a split."""
    stmt = select(func.count()).select_from(RouteRow).where(
        RouteRow.companyId == company_id, RouteRow.load == load_uuid)
    if exclude_id is not None:
        stmt = stmt.where(RouteRow.id != exclude_id)
    if process_id is not None:
        stmt = stmt.where(RouteRow.processId == process_id)
    return (await session.execute(stmt)).scalar_one()


async def _weight_allowed(session, company_id, load_uuid, unload_uuid, exclude_id=None,
                          process_id=None) -> bool:
    """A weight is only meaningful where the graph branches:

    - **merge feed** — the target has another incoming route, so the weight is
      how many upstream units are *consumed* per assembly;
    - **split branch** — the source has another outgoing route, so the weight is
      how many downstream units are *produced* per upstream unit (one steel bar
      cut into four tubes).

    Anywhere else a lot simply moves along 1:1 — including out of a **choice**
    station, whose several routes are either/or destinations, not branches of a
    disassembly. A route out of a choice station may still carry a weight when
    the *target* is a merge: that meaning belongs to the merge.
    """
    if await _other_incoming_count(session, company_id, unload_uuid, exclude_id,
                                   process_id) >= 1:
        return True
    if await _other_outgoing_count(session, company_id, load_uuid, exclude_id,
                                   process_id) < 1:
        return False
    load_station = await session.get(StationRow, load_uuid)
    return load_station is None or load_station.branchMode != "choice"


async def _normalize_weights(session, company_id, *, unload_uuid=None, load_uuid=None,
                             process_id=None) -> None:
    """Weights only mean something where the graph branches. When a station
    drops back to a single incoming route (no longer a merge) or a single
    outgoing route (no longer a split), the survivor's weight resets to 1.
    Branch-hood is judged within one process throughout."""
    if unload_uuid is not None:
        stmt = select(RouteRow).where(RouteRow.companyId == company_id,
                                      RouteRow.unload == unload_uuid)
        if process_id is not None:
            stmt = stmt.where(RouteRow.processId == process_id)
        rows = (await session.execute(stmt)).scalars().all()
        for r in rows:
            if len(rows) == 1 and r.quantity != 1 and not await _other_outgoing_count(
                    session, company_id, r.load, r.id, process_id=r.processId):
                r.quantity = 1
                r.updatedAt = utcnow()
    if load_uuid is not None:
        stmt = select(RouteRow).where(RouteRow.companyId == company_id,
                                      RouteRow.load == load_uuid)
        if process_id is not None:
            stmt = stmt.where(RouteRow.processId == process_id)
        rows = (await session.execute(stmt)).scalars().all()
        for r in rows:
            if len(rows) == 1 and r.quantity != 1 and not await _other_incoming_count(
                    session, company_id, r.unload, r.id, process_id=r.processId):
                r.quantity = 1
                r.updatedAt = utcnow()


_OUTPUT_TEMPLATE_ERROR = (
    "An output product only applies to a branch of a split — disassembly turns "
    "one product into several. Add the sibling route first")


async def _validate_output_template(session, company_id, template_id, load_uuid,
                                    process_id, exclude_id=None, unload_uuid=None):
    """A split branch may declare which product it yields (battery → module /
    busbar / cable). Only splits may: elsewhere a lot keeps its own product."""
    tmpl_uuid = optional_uuid(template_id)
    if tmpl_uuid is None:
        return None
    if await _other_outgoing_count(session, company_id, load_uuid, exclude_id, process_id) < 1:
        raise HTTPException(400, _OUTPUT_TEMPLATE_ERROR)
    load_station = await session.get(StationRow, load_uuid)
    if load_station is not None and load_station.branchMode == "choice":
        raise HTTPException(400, "A choice station routes lots unchanged — only a "
                                 "split station's branches yield a product")
    tmpl = await session.get(LotTemplateRow, tmpl_uuid)
    if tmpl is None or tmpl.companyId != company_id:
        raise HTTPException(404, "Output product not found")
    # When the destination is a MERGE, a piece must never wear the
    # destination's own product: that template is what the merge MINTS, so a
    # piece wearing it is invisible as a precursor and masquerades as finished
    # output — a wash station would count dirty parts as clean and could
    # consume its own work. (On a plain target this is the NORMAL pattern —
    # the branch product starts where the piece lands.)
    if unload_uuid is not None and tmpl.startStationId == unload_uuid:
        from .merge import _incoming_routes
        feeds = await _incoming_routes(session, company_id, unload_uuid, process_id)
        if any(f.id != exclude_id for f in feeds if f.load != load_uuid):
            raise HTTPException(400, "That product is what the destination's merge assembles — "
                                     "a piece wearing it would count as already finished there. "
                                     "Give the branch its own product (for example a 'dirty' variant).")
    return tmpl_uuid


_WEIGHT_ERROR = ("A weight only applies where the graph branches — a feed into a "
                 "merge station, or one of several routes out of a split station. "
                 "Add the sibling route first")


@router.post("/", response_model=Route, status_code=201)
async def create_route(body: RouteCreate, ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    process_uuid = _req_fk(body.processId)
    load_uuid = _req_fk(body.load)
    unload_uuid = _req_fk(body.unload)

    await _assert_in_company(session, ProcessRow, [process_uuid], ctx.company_id, "process")
    await _assert_in_company(session, StationRow, [load_uuid, unload_uuid], ctx.company_id, "station")

    dup = (await session.execute(
        select(RouteRow).where(
            RouteRow.companyId == ctx.company_id,
            RouteRow.processId == process_uuid,
            RouteRow.load == load_uuid,
            RouteRow.unload == unload_uuid,
        )
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(400, "Route already exists between these two stations")

    await _check_boundary_placement(session, ctx.company_id, process_uuid,
                                    load_uuid, unload_uuid)

    edges = await _process_edges(session, ctx.company_id, process_uuid)
    if _would_create_cycle(edges, body.load, body.unload):
        raise HTTPException(400, "This route would create a cycle in the process graph")

    if body.quantity != 1 and not await _weight_allowed(
            session, ctx.company_id, load_uuid, unload_uuid, process_id=process_uuid):
        raise HTTPException(400, _WEIGHT_ERROR)

    row = RouteRow(
        companyId=ctx.company_id, processId=process_uuid,
        load=load_uuid, unload=unload_uuid, quantity=body.quantity,
        outputTemplateId=await _validate_output_template(
            session, ctx.company_id, body.outputTemplateId, load_uuid, process_uuid,
            unload_uuid=unload_uuid),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(400, "Route references a non-existent process or station")
    return _to_route(row)


@router.get("/{route_id}", response_model=Route)
async def get_route(route_id: str, ctx: CompanyContext = Depends(get_active_company),
                    session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    return _to_route(await _get_owned(session, route_id, ctx))


@router.put("/{route_id}", response_model=Route)
async def update_route(route_id: str, body: RouteUpdate,
                       ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, route_id, ctx)

    new_load = body.load or str(row.load)
    new_unload = body.unload or str(row.unload)
    if new_load == new_unload:
        raise HTTPException(400, "A route cannot connect a station to itself")

    if body.load or body.unload:
        ids = [_req_fk(new_load), _req_fk(new_unload)]
        await _assert_in_company(session, StationRow, ids, ctx.company_id, "station")
        edges = await _process_edges(session, ctx.company_id, row.processId, exclude_id=row.id)
        if _would_create_cycle(edges, new_load, new_unload):
            raise HTTPException(400, "This change would create a cycle in the process graph")

    old_unload = row.unload
    old_load = row.load

    if body.load is not None:
        row.load = _req_fk(body.load)
    if body.unload is not None:
        row.unload = _req_fk(body.unload)
    if body.quantity is not None:
        # Weights are only meaningful where the graph branches (merge or split).
        if body.quantity != 1 and not await _weight_allowed(
                session, ctx.company_id, row.load, row.unload, exclude_id=row.id,
                process_id=row.processId):
            raise HTTPException(400, _WEIGHT_ERROR)
        row.quantity = body.quantity
    elif row.quantity != 1 and not await _weight_allowed(
            session, ctx.company_id, row.load, row.unload, exclude_id=row.id,
            process_id=row.processId):
        row.quantity = 1   # a re-target that leaves this unbranched drops its weight
    if body.clearOutputTemplate:
        row.outputTemplateId = None
    elif body.outputTemplateId is not None:
        row.outputTemplateId = await _validate_output_template(
            session, ctx.company_id, body.outputTemplateId, row.load, row.processId,
            exclude_id=row.id, unload_uuid=row.unload)
    row.updatedAt = utcnow()
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(400, "Route references a non-existent process or station")
    if row.unload != old_unload:
        await _normalize_weights(session, ctx.company_id, unload_uuid=old_unload,
                                 process_id=row.processId)
    if row.load != old_load:
        await _normalize_weights(session, ctx.company_id, load_uuid=old_load,
                                 process_id=row.processId)
    return _to_route(row)


@router.delete("/{route_id}", status_code=204)
async def delete_route(route_id: str, ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_owned(session, route_id, ctx)
    unload, load, proc = row.unload, row.load, row.processId
    await session.delete(row)
    await session.flush()
    # If either end just stopped branching, the surviving weight is moot.
    await _normalize_weights(session, ctx.company_id, unload_uuid=unload, process_id=proc)
    await _normalize_weights(session, ctx.company_id, load_uuid=load, process_id=proc)
