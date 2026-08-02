from fastapi import APIRouter, HTTPException, Depends
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import (Card as CardRow, Route as RouteRow, Station as StationRow,
                         StationFavorite as FavoriteRow)
from ..deps.auth import CompanyContext, ensure_sandbox_quota, get_active_company, require_super_admin
from ..models.station import Station, StationCreate, StationUpdate
from ..models.common import utcnow
from ..plugins.registry import plugin_registry
from ..core.integrations import ROLES, default_role, is_provider, role_allowed
from ..core import undo as undo_core
from ..core import entitlements
from ..core.entitlements import works_read_only

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
        integrationProvider=r.integrationProvider,
        integrationRole=r.integrationRole,
        isStorage=bool(r.isStorage),
        branchMode=r.branchMode,
        createdAt=r.createdAt,
        updatedAt=r.updatedAt,
    )


def _validate_branch_mode(mode) -> None:
    if mode is not None and mode not in ("split", "choice"):
        raise HTTPException(400, "branchMode must be 'split' or 'choice'")


async def _strip_split_semantics(session: AsyncSession, company_id, station_uuid) -> None:
    """Becoming a choice station retires the split-only meaning its outgoing
    routes carried. A declared branch product goes (a choice routes lots
    unchanged, it yields nothing), and a stale branch weight resets to 1 —
    left in place it would multiply the pull math as if the station still cut
    material apart. A weight consumed by a merge at the *target* survives:
    that meaning belongs to the merge, not to this station."""
    outgoing = (await session.execute(
        select(RouteRow).where(RouteRow.companyId == company_id,
                               RouteRow.load == station_uuid)
    )).scalars().all()
    for r in outgoing:
        changed = False
        if r.outputTemplateId is not None:
            r.outputTemplateId = None
            changed = True
        if r.quantity != 1:
            feeds = (await session.execute(
                select(RouteRow.id).where(RouteRow.companyId == company_id,
                                          RouteRow.processId == r.processId,
                                          RouteRow.unload == r.unload)
            )).scalars().all()
            if len(feeds) < 2:            # not a merge feed — the weight was split-only
                r.quantity = 1
                changed = True
        if changed:
            r.updatedAt = utcnow()


def _validate_integration(provider, role, ent=None) -> None:
    """A bound location must name a partner Taktline ships a connector for, and
    a role it can actually play. Rejecting here rather than at the DB keeps the
    error a 400 with a readable message.

    This is also the plan gate for *new* bindings — the one funnel both create
    and update pass through. It does nothing for an integration that already
    exists on an account that has since downgraded; that is caught at the
    API-key branch in `deps/auth.require_scope`, which is the only check a
    running connector goes through."""
    if provider is None and role is None:
        return
    if ent is not None:
        entitlements.ensure_integrations(ent)
    if provider is not None and not is_provider(provider):
        raise HTTPException(400, f"Unknown integration provider '{provider}'")
    if role is not None and role not in ROLES:
        raise HTTPException(400, f"Integration role must be one of {sorted(ROLES)}")
    if provider is None:
        raise HTTPException(400, "An integration role needs a provider")
    if role is not None and not role_allowed(provider, role):
        raise HTTPException(
            400, f"{provider} can only be bound as '{default_role(provider)}' — "
                 f"a shipper cannot raise demand, only receive finished goods")


async def _get_owned(session: AsyncSession, station_id: str, ctx: CompanyContext) -> StationRow:
    row = await session.get(StationRow, require_uuid(station_id, "Station not found"))
    if row is None or row.companyId != ctx.company_id:
        raise HTTPException(404, "Station not found")
    return row


@router.get("/", response_model=List[Station])
async def list_stations(ctx: CompanyContext = Depends(get_active_company),
                        session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    rows = (await session.execute(
        select(StationRow).where(StationRow.companyId == ctx.company_id)
    )).scalars().all()
    return [_to_station(r) for r in rows]


@router.post("/", response_model=Station, status_code=201)
async def create_station(body: StationCreate, ctx: CompanyContext = Depends(require_super_admin),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    before = await undo_core.snapshot(session, ctx.company_id)
    await ensure_sandbox_quota(session, ctx, StationRow)
    _validate_integration(body.integrationProvider, body.integrationRole, ctx.entitlement)
    _validate_branch_mode(body.branchMode)
    row = StationRow(**body.model_dump(), companyId=ctx.company_id)
    session.add(row)
    await session.flush()
    station = _to_station(row)
    if station.adapterType:
        await plugin_registry.register(str(row.id), station.adapterType, station.adapterConfig)
    await undo_core.record(session, ctx, f"Add {row.name}",
                           before, await undo_core.snapshot(session, ctx.company_id))
    return station


# ── Favorites (declared before /{station_id} so the literal path wins) ────────

def _require_user(ctx: CompanyContext):
    """Favorites are per-person; an API-key (service) principal has no user."""
    if ctx.user is None:
        raise HTTPException(403, "Favorites require a signed-in user")
    return ctx.user


@router.get("/favorites", response_model=List[str])
async def list_favorites(ctx: CompanyContext = Depends(get_active_company),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
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
@works_read_only   # A per-user UI preference, not company data.
async def add_favorite(station_id: str, ctx: CompanyContext = Depends(get_active_company),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    user = _require_user(ctx)
    row = await _get_owned(session, station_id, ctx)
    if await session.get(FavoriteRow, (user.id, row.id)) is None:   # idempotent
        session.add(FavoriteRow(userId=user.id, stationId=row.id))
        await session.flush()


@router.delete("/{station_id}/favorite", status_code=204)
async def remove_favorite(station_id: str, ctx: CompanyContext = Depends(get_active_company),
                          session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    user = _require_user(ctx)
    fav = await session.get(
        FavoriteRow, (user.id, require_uuid(station_id, "Station not found")))
    if fav is not None:                                                  # idempotent
        await session.delete(fav)


@router.get("/{station_id}", response_model=Station)
async def get_station(station_id: str, ctx: CompanyContext = Depends(get_active_company),
                      session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    return _to_station(await _get_owned(session, station_id, ctx))


@router.put("/{station_id}", response_model=Station)
async def update_station(station_id: str, body: StationUpdate,
                         ctx: CompanyContext = Depends(require_super_admin),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    before = await undo_core.snapshot(session, ctx.company_id)
    row = await _get_owned(session, station_id, ctx)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    # Only charge the plan gate when this request is actually *setting* a
    # provider. A downgraded account still has to be able to rename a station
    # that happens to carry an old binding — and, more to the point, has to be
    # able to clear it in order to downgrade cleanly.
    changing_provider = ("integrationProvider" in patch
                         and patch["integrationProvider"] != row.integrationProvider)
    _validate_integration(patch.get("integrationProvider", row.integrationProvider),
                          patch.get("integrationRole", row.integrationRole),
                          ctx.entitlement if changing_provider else None)
    _validate_branch_mode(patch.get("branchMode"))
    became_choice = patch.get("branchMode") == "choice" and row.branchMode != "choice"
    for k, v in patch.items():
        setattr(row, k, v)
    row.updatedAt = utcnow()
    if became_choice:
        await _strip_split_semantics(session, ctx.company_id, row.id)
    await session.flush()
    station = _to_station(row)
    if "adapterType" in patch or "adapterConfig" in patch:
        await plugin_registry.unregister(station_id)
        if station.adapterType:
            await plugin_registry.register(station_id, station.adapterType, station.adapterConfig)
    await undo_core.record(session, ctx, f"Edit {row.name}",
                           before, await undo_core.snapshot(session, ctx.company_id))
    return station


@router.delete("/{station_id}", status_code=204)
async def delete_station(station_id: str, ctx: CompanyContext = Depends(require_super_admin),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    before = await undo_core.snapshot(session, ctx.company_id)
    row = await _get_owned(session, station_id, ctx)

    # A station holding material may not be removed.
    #
    # `card.bins` is a JSONB map keyed by station id — the one reference in the
    # schema with no foreign key, so the database cannot cascade or refuse on
    # our behalf. Deleting the station therefore did neither: the units stayed,
    # keyed to an id that now resolves to nothing. They vanish from the board
    # (a deleted station draws no column) while still counting in every total,
    # and nothing can move them, because the UI cannot offer a source that does
    # not exist. Inventory that exists in the system and nowhere else.
    #
    # Refusing is the honest answer, and it matches the floor: you do not take
    # a bench out while there are parts on it. Clearing the line wholesale is
    # what `/admin/reset` and `/map-io/import` are for, and both delete lots
    # before stations.
    standing = (await session.execute(
        select(CardRow).where(CardRow.companyId == ctx.company_id,
                              CardRow.bins.has_key(str(row.id)))   # noqa: W601
    )).scalars().all()
    if standing:
        units = sum((c.bins or {}).get(str(row.id), {}).get("count", 0) for c in standing)
        raise HTTPException(400,
            f"{units} unit{'s' if units != 1 else ''} on {len(standing)} lot"
            f"{'s' if len(standing) != 1 else ''} are still at {row.name}. "
            "Move or delete them first.")

    name = row.name
    await session.delete(row)
    await session.flush()
    await plugin_registry.unregister(station_id)
    await undo_core.record(session, ctx, f"Delete {name}",
                           before, await undo_core.snapshot(session, ctx.company_id))


@router.post("/{station_id}/command")
async def send_command(station_id: str, body: dict,
                       ctx: CompanyContext = Depends(require_super_admin),
                       session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    await _get_owned(session, station_id, ctx)  # ensure the station is in this company
    from ..models.machine_state import StationCommand
    cmd = StationCommand(**body)
    ok = await plugin_registry.send_command(station_id, cmd)
    if not ok:
        raise HTTPException(404, "No adapter found for this station")
    return {"ok": True}
