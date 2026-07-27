from fastapi import APIRouter, HTTPException, Depends
from typing import List
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import get_session, require_uuid, parse_uuid
from ..db.tables import Route as RouteRow, Process as ProcessRow, Station as StationRow
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
    stmt = select(RouteRow).where(
        RouteRow.companyId == company_id, RouteRow.processId == process_uuid
    )
    if exclude_id is not None:
        stmt = stmt.where(RouteRow.id != exclude_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [(str(r.load), str(r.unload)) for r in rows]


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


@router.get("/", response_model=List[Route])
async def list_routes(ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(RouteRow).where(RouteRow.companyId == ctx.company_id)
    )).scalars().all()
    return [_to_route(r) for r in rows]


async def _other_incoming_count(session, company_id, unload_uuid, exclude_id=None) -> int:
    """How many routes (other than exclude_id) feed this station."""
    stmt = select(func.count()).select_from(RouteRow).where(
        RouteRow.companyId == company_id, RouteRow.unload == unload_uuid)
    if exclude_id is not None:
        stmt = stmt.where(RouteRow.id != exclude_id)
    return (await session.execute(stmt)).scalar_one()


async def _other_outgoing_count(session, company_id, load_uuid, exclude_id=None) -> int:
    """How many routes (other than exclude_id) leave this station."""
    stmt = select(func.count()).select_from(RouteRow).where(
        RouteRow.companyId == company_id, RouteRow.load == load_uuid)
    if exclude_id is not None:
        stmt = stmt.where(RouteRow.id != exclude_id)
    return (await session.execute(stmt)).scalar_one()


async def _weight_allowed(session, company_id, load_uuid, unload_uuid, exclude_id=None) -> bool:
    """A weight is only meaningful where the graph branches:

    - **merge feed** — the target has another incoming route, so the weight is
      how many upstream units are *consumed* per assembly;
    - **split branch** — the source has another outgoing route, so the weight is
      how many downstream units are *produced* per upstream unit (one steel bar
      cut into four tubes).

    Anywhere else a lot simply moves along 1:1.
    """
    return (
        await _other_incoming_count(session, company_id, unload_uuid, exclude_id) >= 1
        or await _other_outgoing_count(session, company_id, load_uuid, exclude_id) >= 1
    )


async def _normalize_weights(session, company_id, *, unload_uuid=None, load_uuid=None) -> None:
    """Weights only mean something where the graph branches. When a station
    drops back to a single incoming route (no longer a merge) or a single
    outgoing route (no longer a split), the survivor's weight resets to 1."""
    if unload_uuid is not None:
        rows = (await session.execute(
            select(RouteRow).where(RouteRow.companyId == company_id, RouteRow.unload == unload_uuid)
        )).scalars().all()
        for r in rows:
            if len(rows) == 1 and r.quantity != 1 and not await _other_outgoing_count(
                    session, company_id, r.load, r.id):
                r.quantity = 1
                r.updatedAt = utcnow()
    if load_uuid is not None:
        rows = (await session.execute(
            select(RouteRow).where(RouteRow.companyId == company_id, RouteRow.load == load_uuid)
        )).scalars().all()
        for r in rows:
            if len(rows) == 1 and r.quantity != 1 and not await _other_incoming_count(
                    session, company_id, r.unload, r.id):
                r.quantity = 1
                r.updatedAt = utcnow()


_WEIGHT_ERROR = ("A weight only applies where the graph branches — a feed into a "
                 "merge station, or one of several routes out of a split station. "
                 "Add the sibling route first")


@router.post("/", response_model=Route, status_code=201)
async def create_route(body: RouteCreate, ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session)):
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
        raise HTTPException(400, "Route already exists between these two locations")

    edges = await _process_edges(session, ctx.company_id, process_uuid)
    if _would_create_cycle(edges, body.load, body.unload):
        raise HTTPException(400, "This route would create a cycle in the process graph")

    if body.quantity != 1 and not await _weight_allowed(session, ctx.company_id, load_uuid, unload_uuid):
        raise HTTPException(400, _WEIGHT_ERROR)

    row = RouteRow(
        companyId=ctx.company_id, processId=process_uuid,
        load=load_uuid, unload=unload_uuid, quantity=body.quantity,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(400, "Route references a non-existent process or station")
    return _to_route(row)


@router.get("/{route_id}", response_model=Route)
async def get_route(route_id: str, ctx: CompanyContext = Depends(get_active_company),
                    session: AsyncSession = Depends(get_session)):
    return _to_route(await _get_owned(session, route_id, ctx))


@router.put("/{route_id}", response_model=Route)
async def update_route(route_id: str, body: RouteUpdate,
                       ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, route_id, ctx)

    new_load = body.load or str(row.load)
    new_unload = body.unload or str(row.unload)
    if new_load == new_unload:
        raise HTTPException(400, "A route cannot connect a location to itself")

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
                session, ctx.company_id, row.load, row.unload, exclude_id=row.id):
            raise HTTPException(400, _WEIGHT_ERROR)
        row.quantity = body.quantity
    elif row.quantity != 1 and not await _weight_allowed(
            session, ctx.company_id, row.load, row.unload, exclude_id=row.id):
        row.quantity = 1   # a re-target that leaves this unbranched drops its weight
    row.updatedAt = utcnow()
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(400, "Route references a non-existent process or station")
    if row.unload != old_unload:
        await _normalize_weights(session, ctx.company_id, unload_uuid=old_unload)
    if row.load != old_load:
        await _normalize_weights(session, ctx.company_id, load_uuid=old_load)
    return _to_route(row)


@router.delete("/{route_id}", status_code=204)
async def delete_route(route_id: str, ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, route_id, ctx)
    unload, load = row.unload, row.load
    await session.delete(row)
    await session.flush()
    # If either end just stopped branching, the surviving weight is moot.
    await _normalize_weights(session, ctx.company_id, unload_uuid=unload)
    await _normalize_weights(session, ctx.company_id, load_uuid=load)
