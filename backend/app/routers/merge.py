import uuid
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import SESSION_SCOPE, get_session, parse_uuid, require_uuid
from ..db.tables import (
    ProductionOrder as OrderRow, Process as ProcessRow,
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
    # Which products count as this branch's precursor. Authoritative: it honours
    # a declared branch product and the branch's own process, so a client never
    # has to re-derive the matching (and offer a sibling line's lots by mistake).
    precursorTemplateIds: List[str] = []
    # The lot cards an unguided merge would draw from — the modal's opening
    # selection, so the worker adjusts a proposal instead of guessing.
    proposedCardIds: List[str] = []


class MergeProcessInfo(BaseModel):
    """A process that merges at this station — the pickable lines when a bench
    is shared."""
    id: str
    name: str
    feeds: int


class MergePreview(BaseModel):
    isMergeStation: bool
    hasAssemblyTemplate: bool
    assemblyTemplateId: Optional[str] = None
    assemblyTemplateName: Optional[str] = None
    assembliesPossible: int
    requirements: List[RequirementInfo]
    # Which line this preview describes, and every line that merges here. A
    # shared bench assembles one process at a time, so the client can say which.
    processId: Optional[str] = None
    processes: List[MergeProcessInfo] = []


class MergeResult(BaseModel):
    assemblies: int
    createdCardId: str


class MergePerformBody(BaseModel):
    # None/empty → auto mode: consume from any precursor cards at the station.
    # Non-empty → manual mode: consume only from these selected cards.
    cardIds: Optional[List[str]] = None
    # Which process's merge to run, when two share this bench. Usually inferred
    # from cardIds; explicit for AUTO on a shared bench.
    processId: Optional[str] = None


class PullRequest(BaseModel):
    quantity: int
    # On a station several processes share, the pull walks ONE process's
    # upstream chain — this names it. Omitted, the deterministic default
    # (most feeds, then process id) applies.
    processId: Optional[str] = None


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


async def _boundary_station_ids(session, company_id) -> set:
    """Stations bound to an integration partner.

    An edge touching one of these is a **boundary link, not material flow**: it
    records which queue an ERP raises demand against, or which location hands
    finished goods to a shipper. Cards never sit on an integration node, so
    such an edge must be invisible to every piece of graph reasoning — merge
    detection, split detection, the pull walk and the release decision — or an
    Odoo node wired to an intake queue would make that queue look "made here"
    and the pull would try to seed the ERP itself.

    Memoised on the session: the pull walk is recursive and would otherwise
    re-query this on every hop.
    """
    cache = session.info.setdefault("_boundary_stations", {})
    if company_id not in cache:
        cache[company_id] = set((await session.execute(
            select(StationRow.id).where(StationRow.companyId == company_id,
                                        StationRow.integrationProvider.isnot(None))
        )).scalars().all())
    return cache[company_id]


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
    rows = list((await session.execute(stmt)).scalars().all())
    # A feed from an integration node is demand, not material: the ERP does not
    # hand this station parts, it asks it for them.
    boundary = await _boundary_station_ids(session, company_id)
    return [r for r in rows if r.load not in boundary]


def _merge_candidates(incoming: list[RouteRow]):
    """Every process with a merge at this station (2+ feeds), in deterministic
    order — most feeds first, then process id."""
    by_proc: dict = {}
    for r in incoming:
        by_proc.setdefault(r.processId, []).append(r)
    qualifying = [(pid, rs) for pid, rs in by_proc.items() if len(rs) >= 2]
    qualifying.sort(key=lambda x: (-len(x[1]), str(x[0])))
    return qualifying


def _merge_process(incoming: list[RouteRow], process_id=None):
    """The process whose merge lives at this station.

    A station shared by several processes only assembles within one of them
    (either/or routing passes through, it does not merge). When two processes
    both merge at one bench, ``process_id`` — from the worker's selected cards,
    or an explicit request — picks which; without it the choice falls to the
    deterministic order.

    Resolution used to ignore both, which made the losing process's merge
    unreachable: with two merges tied at one bench the same process won every
    call, a worker's selected cards from the other line 400'd "not enough among
    the selected", and AUTO consumed the winner's material while the worker
    stood at the bench to assemble the loser's."""
    qualifying = _merge_candidates(incoming)
    if process_id is not None:
        for pid, rs in qualifying:
            if pid == process_id:
                return pid, rs
        return None, []
    if not qualifying:
        return None, []
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


async def _proposed_cards(session, company_id, station_id: str, incoming: list[RouteRow],
                          assemblies: int) -> dict:
    """Which lot cards an unguided merge would draw from, per route.

    The same cards, in the same order, that ``perform_merge`` consumes —
    smallest bin first, so partial lots are cleared before whole ones are
    broken into. The modal opens with these ticked, which is what turns "press
    AUTO and hope" into a proposal a worker can read and adjust.
    """
    out: dict = {}
    for route in incoming:
        route_qty = max(1, route.quantity)
        tmpl_ids = await _precursor_template_ids(session, company_id, route)
        cards = await _cards_with_bin(session, company_id, station_id, tmpl_ids)
        cards.sort(key=lambda c: _bin_count(c, station_id))
        need = assemblies * route_qty
        picked: list[str] = []
        for card in cards:
            if need <= 0:
                break
            picked.append(str(card.id))
            need -= min(_bin_count(card, station_id), need)
        out[str(route.id)] = picked
    return out


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
            precursorTemplateIds=[str(t) for t in tmpl_ids],
        ))
    return result


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/{station_id}", response_model=MergePreview)
async def get_merge_preview(station_id: str, processId: Optional[str] = None,
                            ctx: CompanyContext = Depends(get_active_company),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """What one assembly needs here, and how many are possible.

    Scoped to ONE process: a bench two lines share has each line's recipe, and
    showing them together describes a merge that does not exist. `processId`
    names the line (the modal's picker); without it the deterministic order
    applies. Every line that merges here is listed either way, so a client can
    offer the choice.
    """
    station_uuid = require_uuid(station_id, "Station not found")
    await _assert_station(session, station_uuid, ctx.company_id)
    all_incoming = await _incoming_routes(session, ctx.company_id, station_uuid)
    candidates = _merge_candidates(all_incoming)

    proc_rows = {}
    if candidates:
        proc_rows = {p.id: p for p in (await session.execute(
            select(ProcessRow).where(ProcessRow.id.in_([pid for pid, _ in candidates]))
        )).scalars().all()}
    process_list = [
        MergeProcessInfo(id=str(pid), name=(proc_rows[pid].name if pid in proc_rows else "Process"),
                         feeds=len(rs))
        for pid, rs in candidates
    ]

    wanted = parse_uuid(processId) if processId else None
    process_id, incoming = _merge_process(all_incoming, wanted)

    if process_id is None:
        return MergePreview(isMergeStation=False, hasAssemblyTemplate=False,
                            assembliesPossible=0, requirements=[], processes=process_list)

    assembly_tmpl = await _assembly_template(session, ctx.company_id, station_uuid, process_id)
    requirements = await _build_requirements(session, ctx.company_id, station_id, incoming)
    assemblies = min((r.canMake for r in requirements), default=0)
    if assemblies >= 1:
        proposal = await _proposed_cards(session, ctx.company_id, station_id, incoming, assemblies)
        for r in requirements:
            r.proposedCardIds = proposal.get(r.routeId, [])

    return MergePreview(
        isMergeStation=True,
        hasAssemblyTemplate=assembly_tmpl is not None,
        assemblyTemplateId=str(assembly_tmpl.id) if assembly_tmpl else None,
        assemblyTemplateName=assembly_tmpl.name if assembly_tmpl else None,
        assembliesPossible=assemblies,
        requirements=requirements,
        processId=str(process_id),
        processes=process_list,
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
    all_incoming = await _incoming_routes(session, ctx.company_id, station_uuid)

    # Manual mode: restrict planning AND consumption to the selected cards —
    # and let the selection say WHICH process's merge the worker means.
    selected: Optional[set] = None
    wanted_process = None
    if body is not None and body.processId:
        wanted_process = parse_uuid(body.processId)
    if body is not None and body.cardIds:
        selected = {require_uuid(cid, "Card not found") for cid in body.cardIds}
        if wanted_process is None:
            procs = set()
            for cid in selected:
                card = await session.get(CardRow, cid)
                if card is not None and card.companyId == ctx.company_id:
                    procs.add(card.processId)
            if len(procs) == 1:
                wanted_process = next(iter(procs))
            elif len(procs) > 1:
                raise HTTPException(400, "Selected cards span two processes — a merge "
                                         "assembles within one value stream.")

    process_id, incoming = _merge_process(all_incoming, wanted_process)

    # AUTO on a shared bench: prefer a process that can actually assemble now,
    # in the same deterministic order the preview reports.
    if process_id is not None and wanted_process is None and selected is None:
        for pid, rs in _merge_candidates(all_incoming):
            reqs = await _build_requirements(session, ctx.company_id, station_id, rs)
            if reqs and min(r.canMake for r in reqs) >= 1:
                process_id, incoming = pid, rs
                break

    if process_id is None:
        raise HTTPException(400, "Not a merge station (fewer than 2 incoming routes)"
                                 if wanted_process is None else
                                 "That process has no merge at this station")

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

    # The order's ERP context follows the same rule as its id: when every
    # consumed precursor agrees on one order, the assembly keeps carrying what
    # the ERP sent (re-read from the order — the single source of truth — not
    # unioned from precursor cards, whose own template fields describe parts,
    # not the finished good).
    order_id = next(iter(consumed_order_ids)) if len(consumed_order_ids) == 1 else None
    inherited_fields: dict = {}
    if order_id is not None:
        src_order = await session.get(OrderRow, order_id)
        if src_order is not None and src_order.attributes:
            inherited_fields = dict(src_order.attributes)

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
        fields=inherited_fields,
        flagged=False,
        description="",
        status="idle",
        # Attribute the assembly to its order if all precursors agreed on one.
        orderId=order_id,
    )
    session.add(new_card)
    await session.flush()
    _emit_card_update(session, ctx.company_id, new_card)
    return MergeResult(assemblies=assemblies, createdCardId=str(new_card.id))


# ─── Pull: create precursor lots at all upstream source stations ──────────────

async def _outgoing_count(session, company_id, load_uuid, process_id=None) -> int:
    """Outgoing routes of a station. Scoped to one process when given: an
    alternative routing lives in its own process and must not read as a split."""
    stmt = select(RouteRow.unload).where(
        RouteRow.companyId == company_id, RouteRow.load == load_uuid)
    if process_id is not None:
        stmt = stmt.where(RouteRow.processId == process_id)
    targets = list((await session.execute(stmt)).scalars().all())
    # Handing finished goods to a shipper is not a second production branch,
    # so a boundary link must never make a station look like a split.
    boundary = await _boundary_station_ids(session, company_id)
    return sum(1 for t in targets if t not in boundary)


async def _is_choice_station(session, station_uuid) -> bool:
    """Declared either/or routing: lots leave 1:1 down one branch, so nothing
    about this station multiplies, fans out, or recombines."""
    row = await session.get(StationRow, station_uuid)
    return row is not None and row.branchMode == "choice"


def _coalesce_sources(sources: list[dict]) -> list[dict]:
    """Recombine demand that reconverges on the same source — the reverse of a
    split. In a diamond (one source feeding two branches that merge again) each
    branch walks back to the same station, but one unit there becomes a piece on
    *every* branch at once, so the requirement is the largest branch's demand,
    not their sum. Distinct sources are left alone (that is a plain merge).

    A **choice** diamond is the opposite: each unit goes down ONE branch, so
    demand arriving via a choice fan is additive — two branches that each need
    one unit need two, and taking the max would starve one of them. Entries are
    tagged `via_choice` by the walk; a mixed nest errs toward the sum, which
    over-orders rather than starves."""
    merged: dict[tuple, dict] = {}
    for src in sources:
        key = (src["station_id"], src["template"].id)
        prev = merged.get(key)
        if prev is None:
            merged[key] = dict(src)
        elif src.get("via_choice") or prev.get("via_choice"):
            prev["quantity"] += src["quantity"]
            prev["via_choice"] = True
        elif src["quantity"] > prev["quantity"]:
            merged[key] = dict(src)
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
        fans_out = len(incoming) == 1 and await _outgoing_count(
            session, company_id, route.load, route.processId) >= 2
        is_choice = fans_out and await _is_choice_station(session, route.load)
        if fans_out and not is_choice:
            # Split: the upstream unit becomes route_qty pieces, so demand for N
            # pieces needs only ceil(N / route_qty) of it — one bar, four tubes.
            upstream = -(-multiplier // route_qty)
        else:
            # Merge feed, a choice branch, or a plain 1:1 hop: each downstream
            # unit consumes route_qty upstream units (1 on a choice branch —
            # its weight is only ever a merge feed's).
            upstream = multiplier * route_qty
        branch_sources = await _leaf_sources(
            session, company_id, route.load, upstream,
            process_id if process_id is not None else route.processId,
        )
        if is_choice:
            # Mark demand routed through an either/or fan: if it reconverges on
            # a shared source, it adds up instead of collapsing to the max.
            for src in branch_sources:
                src["via_choice"] = True
        results.extend(branch_sources)
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
        raise HTTPException(400, "This station has no upstream sources to pull from")

    # The pull walks ONE process's upstream chain. The caller may name it (the
    # modal's process picker on a shared station); otherwise prefer the process
    # that actually merges here (most feeds), deterministically.
    by_proc: dict = {}
    for r in incoming:
        by_proc.setdefault(r.processId, []).append(r)
    if body.processId is not None:
        wanted = parse_uuid(body.processId)
        if wanted is None or wanted not in by_proc:
            raise HTTPException(400, "That process does not feed this station")
        process_id = wanted
    else:
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
