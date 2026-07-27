import uuid
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, require_uuid
from ..db.tables import (
    Route as RouteRow, LotTemplate as LotTemplateRow,
    Card as CardRow, Station as StationRow,
)
from ..deps.auth import CompanyContext, get_active_company, require_admin
from ..models.common import utcnow

router = APIRouter(prefix="/merge", tags=["merge"])


# ─── Response models ──────────────────────────────────────────────────────────

class RequirementInfo(BaseModel):
    routeId: str
    sourceStationId: str
    requiredPerAssembly: int
    availableUnits: int
    canMake: int


class MergePreview(BaseModel):
    isMergeStation: bool
    hasAssemblyTemplate: bool
    assemblyTemplateId: Optional[str] = None
    assemblyTemplateName: Optional[str] = None
    assembliesPossible: int
    requirements: List[RequirementInfo]


class MergeResult(BaseModel):
    assemblies: int
    createdCardId: str


class MergePerformBody(BaseModel):
    # None/empty → auto mode: consume from any precursor cards at the station.
    # Non-empty → manual mode: consume only from these selected cards.
    cardIds: Optional[List[str]] = None


class PullRequest(BaseModel):
    quantity: int


class PullSourceInfo(BaseModel):
    stationId:    str
    stationName:  str
    templateId:   str
    templateName: str
    quantity:     int


class PullResult(BaseModel):
    sources:        List[PullSourceInfo]
    createdCardIds: List[str]


# ─── Helpers (all scoped to a company) ─────────────────────────────────────────

async def _assert_station(session: AsyncSession, station_uuid: uuid.UUID, company_id: uuid.UUID) -> None:
    st = await session.get(StationRow, station_uuid)
    if st is None or st.companyId != company_id:
        raise HTTPException(404, "Station not found")


async def _incoming_routes(session, company_id, station_uuid, process_id=None) -> list[RouteRow]:
    """Routes feeding a station — scoped to one process when given. Stations are
    physical and may be shared by several processes (the documented pattern for
    either/or routing), but merges, like splits, only ever exist *within* a
    process: an unscoped read makes one process's merge demand another
    process's material."""
    stmt = select(RouteRow).where(
        RouteRow.companyId == company_id, RouteRow.unload == station_uuid)
    if process_id is not None:
        stmt = stmt.where(RouteRow.processId == process_id)
    return list((await session.execute(stmt)).scalars().all())


def _merge_process(incoming: list[RouteRow]):
    """The process whose merge lives at this station: the one with 2+ feeds.

    A station shared by several processes only assembles within one of them
    (either/or routing passes through, it does not merge). Should a factory ever
    point two different processes' merges at one physical bench, the choice is
    made deterministic — most feeds first, then process id — so preview and
    perform always agree."""
    by_proc: dict = {}
    for r in incoming:
        by_proc.setdefault(r.processId, []).append(r)
    qualifying = [(pid, rs) for pid, rs in by_proc.items() if len(rs) >= 2]
    if not qualifying:
        return None, []
    qualifying.sort(key=lambda x: (-len(x[1]), str(x[0])))
    return qualifying[0]


async def _assembly_template(session, company_id, station_uuid, process_id=None) -> Optional[LotTemplateRow]:
    stmt = select(LotTemplateRow).where(
        LotTemplateRow.companyId == company_id,
        LotTemplateRow.startStationId == station_uuid,
    )
    if process_id is not None:
        stmt = stmt.where(LotTemplateRow.processId == process_id)
    return (await session.execute(stmt.order_by(LotTemplateRow.createdAt.asc()))).scalars().first()


async def _ensure_origination_template(session, company_id, station_uuid, process_id=None) -> LotTemplateRow:
    """Return the template that originates lots at this station, creating a
    sensible **default** (named after the station) if none exists. This is what
    lets a line run — pull and merge — without an admin hand-defining a template
    for every source and every merge. An explicit template still wins; the
    default only fills the gap."""
    tmpl = await _assembly_template(session, company_id, station_uuid, process_id)
    if tmpl is not None:
        return tmpl
    station = await session.get(StationRow, station_uuid)
    tmpl = LotTemplateRow(
        companyId=company_id,
        name=(station.name if station and station.name else "Lot"),
        startStationId=station_uuid,
        processId=process_id,
    )
    session.add(tmpl)
    await session.flush()
    return tmpl


async def _source_template_ids(session, company_id, source_station_uuid,
                               process_id=None) -> list[uuid.UUID]:
    stmt = select(LotTemplateRow.id).where(
        LotTemplateRow.companyId == company_id,
        LotTemplateRow.startStationId == source_station_uuid,
    )
    if process_id is not None:
        stmt = stmt.where(LotTemplateRow.processId == process_id)
    return list((await session.execute(stmt)).scalars().all())


async def _precursor_template_ids(session, company_id, route: RouteRow) -> list[uuid.UUID]:
    """Which products count as *this* incoming branch's precursor at the merge.

    A disassembly branch says what it yields (battery → cable), so the merge
    matches that product. Otherwise the branch is identified the ordinary way:
    whatever originates at its source station — within the branch's own process,
    so a sibling process's product standing at the same bench is never eaten."""
    if route.outputTemplateId is not None:
        return [route.outputTemplateId]
    return await _source_template_ids(session, company_id, route.load, route.processId)


async def _station_lock(session: AsyncSession, company_id, station_id: str) -> None:
    """Serialize merge/consume operations per (company, station). Without this,
    two concurrent merges (e.g. React StrictMode double-firing the operator
    view's auto-merge) both read the same precursor availability and each mint
    an assembly card — duplicating lots. The advisory xact lock is released
    automatically at commit/rollback."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"merge:{company_id}:{station_id}"},
    )


async def _cards_with_bin(session, company_id, station_id: str, template_ids: list[uuid.UUID],
                          for_update: bool = False,
                          card_ids: Optional[set] = None) -> list[CardRow]:
    if not template_ids:
        return []
    stmt = select(CardRow).where(
        CardRow.companyId == company_id, CardRow.lotTemplateId.in_(template_ids)
    )
    if for_update:
        stmt = stmt.with_for_update()
    cards = (await session.execute(stmt)).scalars().all()
    return [c for c in cards
            if (c.bins or {}).get(station_id, {}).get("count", 0) > 0
            and (card_ids is None or c.id in card_ids)]


def _bin_count(card: CardRow, station_id: str) -> int:
    return (card.bins or {}).get(station_id, {}).get("count", 0)


def _gen_lot_code() -> str:
    """Random short lot code (e.g. "E4096A") for system-created cards, so every
    physical Kanban card carries a human-usable identifier. Users may also
    define their own code when creating a lot; splitting a lot apart keeps it."""
    return uuid.uuid4().hex[:6].upper()


async def _available_units(session, company_id, station_id: str, template_ids: list[uuid.UUID],
                           card_ids: Optional[set] = None) -> int:
    cards = await _cards_with_bin(session, company_id, station_id, template_ids, card_ids=card_ids)
    return sum(_bin_count(c, station_id) for c in cards)


async def _build_requirements(session, company_id, station_id: str, incoming: list[RouteRow],
                              card_ids: Optional[set] = None) -> list[RequirementInfo]:
    result: list[RequirementInfo] = []
    for route in incoming:
        route_qty = max(1, route.quantity)
        tmpl_ids = await _precursor_template_ids(session, company_id, route)
        available = await _available_units(session, company_id, station_id, tmpl_ids, card_ids=card_ids)
        result.append(RequirementInfo(
            routeId=str(route.id),
            sourceStationId=str(route.load),
            requiredPerAssembly=route_qty,
            availableUnits=available,
            canMake=available // route_qty,
        ))
    return result


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/{station_id}", response_model=MergePreview)
async def get_merge_preview(station_id: str, ctx: CompanyContext = Depends(get_active_company),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    station_uuid = require_uuid(station_id, "Station not found")
    await _assert_station(session, station_uuid, ctx.company_id)
    process_id, incoming = _merge_process(
        await _incoming_routes(session, ctx.company_id, station_uuid))

    if process_id is None:
        return MergePreview(isMergeStation=False, hasAssemblyTemplate=False,
                            assembliesPossible=0, requirements=[])

    assembly_tmpl = await _assembly_template(session, ctx.company_id, station_uuid, process_id)
    requirements = await _build_requirements(session, ctx.company_id, station_id, incoming)
    assemblies = min((r.canMake for r in requirements), default=0)

    return MergePreview(
        isMergeStation=True,
        hasAssemblyTemplate=assembly_tmpl is not None,
        assemblyTemplateId=str(assembly_tmpl.id) if assembly_tmpl else None,
        assemblyTemplateName=assembly_tmpl.name if assembly_tmpl else None,
        assembliesPossible=assemblies,
        requirements=requirements,
    )


@router.post("/{station_id}", response_model=MergeResult, status_code=201)
async def perform_merge(station_id: str, body: Optional[MergePerformBody] = None,
                        ctx: CompanyContext = Depends(get_active_company),
                        session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Member-allowed: merging precursors into the assembled good is the first
    step of working at a merge station, so operators must be able to do it.
    With ``cardIds`` the worker chooses exactly which precursor lot cards get
    consumed (manual mode); without it any available precursors are used (the
    operator view's AUTO button). Pull and unmerge stay admin-only."""
    station_uuid = require_uuid(station_id, "Station not found")
    await _assert_station(session, station_uuid, ctx.company_id)
    # Take the per-station merge lock BEFORE reading availability, so a
    # concurrent duplicate merge waits and then sees the already-consumed state.
    await _station_lock(session, ctx.company_id, station_id)
    process_id, incoming = _merge_process(
        await _incoming_routes(session, ctx.company_id, station_uuid))

    if process_id is None:
        raise HTTPException(400, "Not a merge station (fewer than 2 incoming routes)")

    # Manual mode: restrict planning AND consumption to the selected cards.
    selected: Optional[set] = None
    if body is not None and body.cardIds:
        selected = {require_uuid(cid, "Card not found") for cid in body.cardIds}

    # Provision a default assembly template if the admin never made one — the
    # merge should just work.
    assembly_tmpl = await _ensure_origination_template(
        session, ctx.company_id, station_uuid, process_id)

    requirements = await _build_requirements(session, ctx.company_id, station_id, incoming,
                                             card_ids=selected)
    if not requirements:
        raise HTTPException(400, "No precursor routes found")

    assemblies = min(r.canMake for r in requirements)
    if assemblies < 1:
        raise HTTPException(400, "Not enough precursor units to assemble"
                                 + (" among the selected cards" if selected else ""))

    # Lazy import: cards.py imports from this module at load time, so the emit
    # helpers can only be pulled in at call time.
    from .cards import _emit_card_update, _emit_card_delete

    consumed_order_ids: set = set()   # to attribute the assembly back to its order
    consumed_codes: set = set()       # to carry the lot code through when all agree
    for route in incoming:
        route_qty = max(1, route.quantity)
        tmpl_ids = await _precursor_template_ids(session, ctx.company_id, route)
        to_consume = assemblies * route_qty

        # Row-lock the cards being consumed so a concurrent /move can't shift
        # the same units out from under the merge.
        cards = await _cards_with_bin(session, ctx.company_id, station_id, tmpl_ids,
                                      for_update=True, card_ids=selected)
        cards.sort(key=lambda c: _bin_count(c, station_id))

        for card in cards:
            if to_consume <= 0:
                break
            bin_count = _bin_count(card, station_id)
            take = min(bin_count, to_consume)
            new_count = bin_count - take
            to_consume -= take
            if take > 0 and card.orderId is not None:
                consumed_order_ids.add(card.orderId)
            if take > 0 and card.lotNum:
                consumed_codes.add(card.lotNum)

            new_bins = dict(card.bins or {})
            if new_count <= 0:
                new_bins.pop(station_id, None)
                if not new_bins:
                    await session.delete(card)
                    _emit_card_delete(session, ctx.company_id, str(card.id))
                    continue
            else:
                new_bins[station_id] = {"count": new_count}
            card.bins = new_bins
            card.updatedAt = utcnow()
            if take > 0:
                _emit_card_update(session, ctx.company_id, card)

        if to_consume > 0:
            # Units disappeared between planning and consumption (concurrent
            # move). Abort — the transaction rolls back all partial consumption.
            raise HTTPException(409, "Precursor units changed during merge — try again")

    new_card = CardRow(
        companyId=ctx.company_id,
        lotTemplateId=assembly_tmpl.id,
        processId=process_id,
        # Carry the lot code through when every consumed precursor shares one (an
        # order's precursors all carry its code → the finished good keeps it too);
        # otherwise the assembly is a new lot and gets a fresh code.
        lotNum=(next(iter(consumed_codes)) if len(consumed_codes) == 1 else _gen_lot_code()),
        totalQuantity=assemblies,
        bins={station_id: {"count": assemblies}},
        fields={},
        flagged=False,
        description="",
        status="idle",
        # Attribute the assembly to its order if all precursors agreed on one.
        orderId=(next(iter(consumed_order_ids)) if len(consumed_order_ids) == 1 else None),
    )
    session.add(new_card)
    await session.flush()
    _emit_card_update(session, ctx.company_id, new_card)
    return MergeResult(assemblies=assemblies, createdCardId=str(new_card.id))


# ─── Pull: create precursor lots at all upstream source stations ──────────────

async def _outgoing_count(session, company_id, load_uuid, process_id=None) -> int:
    """Outgoing routes of a station. Scoped to one process when given: an
    alternative routing lives in its own process and must not read as a split."""
    stmt = select(func.count()).select_from(RouteRow).where(
        RouteRow.companyId == company_id, RouteRow.load == load_uuid)
    if process_id is not None:
        stmt = stmt.where(RouteRow.processId == process_id)
    return (await session.execute(stmt)).scalar_one()


def _coalesce_sources(sources: list[dict]) -> list[dict]:
    """Recombine demand that reconverges on the same source — the reverse of a
    split. In a diamond (one source feeding two branches that merge again) each
    branch walks back to the same station, but one unit there becomes a piece on
    *every* branch at once, so the requirement is the largest branch's demand,
    not their sum. Distinct sources are left alone (that is a plain merge)."""
    merged: dict[tuple, dict] = {}
    for src in sources:
        key = (src["station_id"], src["template"].id)
        prev = merged.get(key)
        if prev is None or src["quantity"] > prev["quantity"]:
            merged[key] = src
    return list(merged.values())


async def _leaf_sources(session, company_id, station_uuid, multiplier: int = 1, process_id=None) -> list[dict]:
    # The walk stays inside one process: a shared station's feeds from OTHER
    # processes are different value streams, and walking them would spawn
    # precursors for material this pull never consumes.
    incoming = await _incoming_routes(session, company_id, station_uuid, process_id)
    if not incoming:
        # A leaf source always yields a lot — provisioning a default template if
        # the admin never made one, so pulling never silently skips a branch.
        tmpl = await _ensure_origination_template(session, company_id, station_uuid, process_id)
        return [{"station_id": str(station_uuid), "template": tmpl, "quantity": multiplier}]
    results: list[dict] = []
    for route in incoming:
        route_qty = max(1, route.quantity)
        if len(incoming) == 1 and await _outgoing_count(
                session, company_id, route.load, route.processId) >= 2:
            # Split: the upstream unit becomes route_qty pieces, so demand for N
            # pieces needs only ceil(N / route_qty) of it — one bar, four tubes.
            upstream = -(-multiplier // route_qty)
        else:
            # Merge feed (or a plain 1:1 hop): each downstream unit consumes
            # route_qty upstream units.
            upstream = multiplier * route_qty
        results.extend(await _leaf_sources(
            session, company_id, route.load, upstream,
            process_id if process_id is not None else route.processId,
        ))
    return _coalesce_sources(results)


@router.post("/{station_id}/pull", response_model=PullResult, status_code=201)
async def pull_for_merge(station_id: str, body: PullRequest,
                         ctx: CompanyContext = Depends(require_admin),
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    if body.quantity < 1:
        raise HTTPException(400, "quantity must be ≥ 1")

    station_uuid = require_uuid(station_id, "Station not found")
    await _assert_station(session, station_uuid, ctx.company_id)
    incoming = await _incoming_routes(session, ctx.company_id, station_uuid)
    if len(incoming) < 1:
        raise HTTPException(400, "This location has no upstream sources to pull from")

    # The pull walks ONE process's upstream chain. On a shared station prefer
    # the process that actually merges here (most feeds), deterministically.
    by_proc: dict = {}
    for r in incoming:
        by_proc.setdefault(r.processId, []).append(r)
    process_id = sorted(by_proc, key=lambda pid: (-len(by_proc[pid]), str(pid)))[0]
    sources = await _leaf_sources(session, ctx.company_id, station_uuid, body.quantity, process_id)
    if not sources:
        raise HTTPException(422, "No upstream source stations found")

    from .cards import _emit_card_update   # lazy: avoids the cards↔merge import cycle

    created_ids: list[str] = []
    source_infos: list[PullSourceInfo] = []

    for src in sources:
        tmpl = src["template"]
        src_qty = src["quantity"]
        station_row = await session.get(StationRow, require_uuid(src["station_id"]))
        station_name = station_row.name if station_row else src["station_id"]

        new_card = CardRow(
            companyId=ctx.company_id,
            lotTemplateId=tmpl.id,
            processId=process_id,
            lotNum=_gen_lot_code(),
            totalQuantity=src_qty,
            bins={src["station_id"]: {"count": src_qty}},
            fields={},
            flagged=False,
            description="",
            status="idle",
        )
        session.add(new_card)
        await session.flush()
        created_ids.append(str(new_card.id))
        _emit_card_update(session, ctx.company_id, new_card)
        source_infos.append(PullSourceInfo(
            stationId=src["station_id"],
            stationName=station_name,
            templateId=str(tmpl.id),
            templateName=tmpl.name,
            quantity=src_qty,
        ))

    return PullResult(sources=source_infos, createdCardIds=created_ids)
