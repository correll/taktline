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


async def _normalize_single_feed(session, company_id, unload_uuid) -> None:
    """Weights only mean something on merge feeds. When a station drops back to
    a single incoming route (after a delete or a re-target), that survivor's
    weight is reset to 1."""
    rows = (await session.execute(
        select(RouteRow).where(RouteRow.companyId == company_id, RouteRow.unload == unload_uuid)
    )).scalars().all()
    if len(rows) == 1 and rows[0].quantity != 1:
        rows[0].quantity = 1
        rows[0].updatedAt = utcnow()


_WEIGHT_ERROR = ("Only a route that is one of multiple feeds into a merge station "
                 "can carry a weight — add the other incoming route first")


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

    if body.quantity != 1 and await _other_incoming_count(session, ctx.company_id, unload_uuid) < 1:
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

    if body.load is not None:
        row.load = _req_fk(body.load)
    if body.unload is not None:
        row.unload = _req_fk(body.unload)
    if body.quantity is not None:
        # Weights are only meaningful on one of multiple feeds into a merge station.
        if body.quantity != 1 and await _other_incoming_count(
                session, ctx.company_id, row.unload, exclude_id=row.id) < 1:
            raise HTTPException(400, _WEIGHT_ERROR)
        row.quantity = body.quantity
    elif row.quantity != 1 and await _other_incoming_count(
            session, ctx.company_id, row.unload, exclude_id=row.id) < 1:
        row.quantity = 1   # a re-target that leaves this as the only feed drops its weight
    row.updatedAt = utcnow()
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(400, "Route references a non-existent process or station")
    if row.unload != old_unload:
        await _normalize_single_feed(session, ctx.company_id, old_unload)
    return _to_route(row)


@router.delete("/{route_id}", status_code=204)
async def delete_route(route_id: str, ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, route_id, ctx)
    unload = row.unload
    await session.delete(row)
    await session.flush()
    # If the target station just dropped to a single feed, its weight is moot.
    await _normalize_single_feed(session, ctx.company_id, unload)
