from fastapi import APIRouter, HTTPException, Depends
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import get_session, require_uuid
from ..db.tables import Station as StationRow, StationFavorite as FavoriteRow
from ..deps.auth import CompanyContext, ensure_sandbox_quota, get_active_company, require_super_admin
from ..models.station import Station, StationCreate, StationUpdate
from ..models.common import utcnow
from ..plugins.registry import plugin_registry

router = APIRouter(prefix="/stations", tags=["stations"])


def _to_station(r: StationRow) -> Station:
    return Station(
        _id=str(r.id),
        name=r.name,
        position=r.position or {},
        adapterType=r.adapterType,
        adapterConfig=r.adapterConfig or {},
        description=r.description,
        color=r.color,
        icon=r.icon,
        createdAt=r.createdAt,
        updatedAt=r.updatedAt,
    )


async def _get_owned(session: AsyncSession, station_id: str, ctx: CompanyContext) -> StationRow:
    row = await session.get(StationRow, require_uuid(station_id, "Station not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Station not found")
    return row


@router.get("/", response_model=List[Station])
async def list_stations(ctx: CompanyContext = Depends(get_active_company),
                        session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(StationRow).where(StationRow.companyId == ctx.company_id)
    )).scalars().all()
    return [_to_station(r) for r in rows]


@router.post("/", response_model=Station, status_code=201)
async def create_station(body: StationCreate, ctx: CompanyContext = Depends(require_super_admin),
                         session: AsyncSession = Depends(get_session)):
    await ensure_sandbox_quota(session, ctx, StationRow)
    row = StationRow(**body.model_dump(), companyId=ctx.company_id)
    session.add(row)
    await session.flush()
    station = _to_station(row)
    if station.adapterType:
        await plugin_registry.register(str(row.id), station.adapterType, station.adapterConfig)
    return station


# ── Favorites (declared before /{station_id} so the literal path wins) ────────

def _require_user(ctx: CompanyContext):
    """Favorites are per-person; an API-key (service) principal has no user."""
    if ctx.user is None:
        raise HTTPException(403, "Favorites require a signed-in user")
    return ctx.user


@router.get("/favorites", response_model=List[str])
async def list_favorites(ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session)):
    """The current user's favorite locations in the active company — surfaced
    first in the operator view's location picker."""
    user = _require_user(ctx)
    rows = (await session.execute(
        select(FavoriteRow.stationId)
        .join(StationRow, StationRow.id == FavoriteRow.stationId)
        .where(FavoriteRow.userId == user.id,
               StationRow.companyId == ctx.company_id)
    )).scalars().all()
    return [str(sid) for sid in rows]


@router.put("/{station_id}/favorite", status_code=204)
async def add_favorite(station_id: str, ctx: CompanyContext = Depends(get_active_company),
                       session: AsyncSession = Depends(get_session)):
    user = _require_user(ctx)
    row = await _get_owned(session, station_id, ctx)
    if await session.get(FavoriteRow, (user.id, row.id)) is None:   # idempotent
        session.add(FavoriteRow(userId=user.id, stationId=row.id))
        await session.flush()


@router.delete("/{station_id}/favorite", status_code=204)
async def remove_favorite(station_id: str, ctx: CompanyContext = Depends(get_active_company),
                          session: AsyncSession = Depends(get_session)):
    user = _require_user(ctx)
    fav = await session.get(
        FavoriteRow, (user.id, require_uuid(station_id, "Station not found")))
    if fav is not None:                                                  # idempotent
        await session.delete(fav)


@router.get("/{station_id}", response_model=Station)
async def get_station(station_id: str, ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session)):
    return _to_station(await _get_owned(session, station_id, ctx))


@router.put("/{station_id}", response_model=Station)
async def update_station(station_id: str, body: StationUpdate,
                         ctx: CompanyContext = Depends(require_super_admin),
                         session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, station_id, ctx)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    for k, v in patch.items():
        setattr(row, k, v)
    row.updatedAt = utcnow()
    await session.flush()
    station = _to_station(row)
    if "adapterType" in patch or "adapterConfig" in patch:
        await plugin_registry.unregister(station_id)
        if station.adapterType:
            await plugin_registry.register(station_id, station.adapterType, station.adapterConfig)
    return station


@router.delete("/{station_id}", status_code=204)
async def delete_station(station_id: str, ctx: CompanyContext = Depends(require_super_admin),
                         session: AsyncSession = Depends(get_session)):
    row = await _get_owned(session, station_id, ctx)
    await session.delete(row)
    await session.flush()
    await plugin_registry.unregister(station_id)


@router.post("/{station_id}/command")
async def send_command(station_id: str, body: dict,
                       ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session)):
    await _get_owned(session, station_id, ctx)  # ensure the station is in this company
    from ..models.machine_state import StationCommand
    cmd = StationCommand(**body)
    ok = await plugin_registry.send_command(station_id, cmd)
    if not ok:
        raise HTTPException(404, "No adapter found for this station")
    return {"ok": True}
