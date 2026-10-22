"""Export a company's whole line as JSON, and import one — safely.

The file is the **line definition**: stations, processes, routes, products.
Not the live state — lots, sessions and orders describe a moment, not a map —
and not the floor-plan image, which is uploaded separately.

── Why this cannot inject anything ──────────────────────────────────────────
The file is data, never instructions, and four walls keep it that way:

1. **Schema first.** The body is parsed into strict Pydantic models with
   length-capped strings, bounded numbers and hard list caps; unknown keys are
   rejected outright (`extra="forbid"`), so there is nowhere to smuggle a
   payload the importer would even read.
2. **Every id is re-minted.** The file references entities by opaque local refs
   ("s1", "p2"); the server maps each to a fresh UUID. Nothing in the file can
   name, collide with, or overwrite an id in the database — including another
   tenant's.
3. **Enums are allow-listed** (integration providers/roles, field types) and
   free text is stored as inert text: parameterized SQL end to end, and a React
   frontend that escapes on render — the same guarantees every other endpoint
   has, checked by tests that import hostile strings and read them back
   verbatim.
4. **The graph rules still apply.** Routes are created through the same checks
   the UI goes through — cycle detection, boundary placement, the handoff
   mirror rule, weight eligibility, output-template validation — in the same
   order (production routes, then boundary links, then weights), so a crafted
   file cannot build a shape the editor would refuse.

Import **replaces** the current line: sessions, lots, products, routes,
processes and stations go, in child-before-parent order (the same order as
`/admin/reset`); the `card_events` audit log survives, as it does deletion
everywhere else. The whole import runs in the request's one transaction — a
file that fails validation halfway leaves the old line untouched.
"""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.integrations import ROLES, is_provider, role_allowed
from ..core import entitlements
from ..db.connection import SESSION_SCOPE, get_session
from ..db.tables import (
    Card as CardRow,
    LotTemplate as LotTemplateRow,
    Process as ProcessRow,
    Route as RouteRow,
    Station as StationRow,
    WorkSession as SessionRow,
)
from ..deps.auth import CompanyContext, ensure_full_account, require_super_admin
from ..models.common import utcnow
from .routes import (_check_boundary_placement, _process_edges, _validate_output_template,
                     _weight_allowed, _would_create_cycle)

router = APIRouter(prefix="/map-io", tags=["map-io"])

# MAX_ROUTES was 500, which a high-mix line passes long before anything else:
# 50 product variants of a dozen steps each is 600 routes. Found by replaying a
# day of the Bosch production-line data set (24 stations, 50 paths, 598 routes).
MAX_STATIONS, MAX_PROCESSES, MAX_ROUTES, MAX_TEMPLATES = 200, 50, 2000, 300

_NAME = Field(min_length=1, max_length=120)
_REF = Field(min_length=1, max_length=64)


class IoPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(0, ge=-1e6, le=1e6)
    y: float = Field(0, ge=-1e6, le=1e6)
    width: float = Field(60, ge=1, le=10000)
    height: float = Field(60, ge=1, le=10000)


class IoStation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = _REF
    name: str = _NAME
    description: str = Field("", max_length=2000)
    position: IoPosition = Field(default_factory=IoPosition)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{3,8}$")
    icon: Optional[str] = Field(None, max_length=40)
    isStorage: bool = False
    # 'split' (default) or 'choice' — what several outgoing routes mean here.
    branchMode: Optional[Literal["split", "choice"]] = None
    integrationProvider: Optional[str] = Field(None, max_length=40)
    integrationRole: Optional[str] = Field(None, max_length=10)

    @field_validator("integrationProvider")
    @classmethod
    def _provider(cls, v):
        if v is not None and not is_provider(v):
            raise ValueError(f"unknown integration provider {v!r}")
        return v

    @field_validator("integrationRole")
    @classmethod
    def _role(cls, v):
        if v is not None and v not in ROLES:
            raise ValueError(f"integration role must be one of {sorted(ROLES)}")
        return v


class IoProcess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = _REF
    name: str = _NAME
    description: str = Field("", max_length=2000)
    desiredTaktSec: Optional[float] = Field(None, gt=0, le=1e7)


class IoField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=120)
    type: Literal["text", "number", "date", "select"] = "text"
    options: List[str] = Field(default_factory=list, max_length=50)
    required: bool = False

    @field_validator("options")
    @classmethod
    def _opts(cls, v):
        for o in v:
            if len(o) > 120:
                raise ValueError("option too long")
        return v


class IoTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = _REF
    name: str = _NAME
    description: str = Field("", max_length=2000)
    process: Optional[str] = Field(None, max_length=64)      # process ref
    startStation: Optional[str] = Field(None, max_length=64)  # station ref
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{3,8}$")
    fields: List[IoField] = Field(default_factory=list, max_length=40)


class IoRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    process: str = _REF
    load: str = _REF
    unload: str = _REF
    quantity: int = Field(1, ge=1, le=10000)
    outputTemplate: Optional[str] = Field(None, max_length=64)


class IoMapSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit: Literal["m", "ft"] = "m"
    pixelsPerUnit: float = Field(100, gt=0, le=10000)
    stationSizeUnits: float = Field(1, gt=0, le=1000)


class MapDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["taktline-map"]
    version: Literal[1]
    name: str = Field("", max_length=200)
    mapSettings: Optional[IoMapSettings] = None
    stations: List[IoStation] = Field(default_factory=list, max_length=MAX_STATIONS)
    processes: List[IoProcess] = Field(default_factory=list, max_length=MAX_PROCESSES)
    templates: List[IoTemplate] = Field(default_factory=list, max_length=MAX_TEMPLATES)
    routes: List[IoRoute] = Field(default_factory=list, max_length=MAX_ROUTES)


# ─── Export ──────────────────────────────────────────────────────────────────

@router.get("/export", response_model=MapDocument)
async def export_map(ctx: CompanyContext = Depends(require_super_admin),
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    stations = (await session.execute(
        select(StationRow).where(StationRow.companyId == ctx.company_id)
        .order_by(StationRow.createdAt))).scalars().all()
    processes = (await session.execute(
        select(ProcessRow).where(ProcessRow.companyId == ctx.company_id)
        .order_by(ProcessRow.createdAt))).scalars().all()
    templates = (await session.execute(
        select(LotTemplateRow).where(LotTemplateRow.companyId == ctx.company_id)
        .order_by(LotTemplateRow.createdAt))).scalars().all()
    routes = (await session.execute(
        select(RouteRow).where(RouteRow.companyId == ctx.company_id)
        .order_by(RouteRow.createdAt))).scalars().all()

    s_ref = {s.id: f"s{i+1}" for i, s in enumerate(stations)}
    p_ref = {p.id: f"p{i+1}" for i, p in enumerate(processes)}
    t_ref = {t.id: f"t{i+1}" for i, t in enumerate(templates)}

    from .map_settings import get_map_settings  # avoid cycle at import time
    ms = None
    try:
        got = await get_map_settings(ctx=ctx, session=session)
        ms = IoMapSettings(unit=got.unit, pixelsPerUnit=got.pixelsPerUnit,
                           stationSizeUnits=got.stationSizeUnits or 1)
    except Exception:
        ms = None                      # settings are optional in the file

    return MapDocument(
        kind="taktline-map", version=1, name="",
        mapSettings=ms,
        stations=[IoStation(
            ref=s_ref[s.id], name=s.name, description=s.description or "",
            position=IoPosition(**{k: (s.position or {}).get(k, d)
                                   for k, d in (("x", 0), ("y", 0), ("width", 60), ("height", 60))}),
            color=s.color, icon=s.icon, isStorage=bool(s.isStorage),
            branchMode=s.branchMode,
            integrationProvider=s.integrationProvider, integrationRole=s.integrationRole,
        ) for s in stations],
        processes=[IoProcess(ref=p_ref[p.id], name=p.name, description=p.description or "",
                             desiredTaktSec=p.desiredTaktSec) for p in processes],
        templates=[IoTemplate(
            ref=t_ref[t.id], name=t.name, description=t.description or "",
            process=p_ref.get(t.processId), startStation=s_ref.get(t.startStationId),
            color=t.color, fields=[IoField(**f) for f in (t.fields or [])],
        ) for t in templates],
        routes=[IoRoute(
            process=p_ref.get(r.processId, ""), load=s_ref.get(r.load, ""),
            unload=s_ref.get(r.unload, ""), quantity=r.quantity or 1,
            outputTemplate=t_ref.get(r.outputTemplateId),
        ) for r in routes if r.processId in p_ref and r.load in s_ref and r.unload in s_ref],
    )


# ─── Import ──────────────────────────────────────────────────────────────────

def _dupes(refs):
    seen, out = set(), set()
    for r in refs:
        (out if r in seen else seen).add(r)
    return out


@router.post("/import")
async def import_map(doc: MapDocument,
                     ctx: CompanyContext = Depends(require_super_admin),
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Replace this company's line with the file's. One transaction: a file
    that fails any rule leaves the old line untouched."""
    # Not in the sandbox. A visitor is super-admin of their throwaway company,
    # so nothing else stopped them pasting a line file — and while an import
    # REPLACES rather than appends, the per-row quotas do not cover routes at
    # all (forty stations, but a file may carry five hundred edges), and each
    # attempt is a full delete-and-reinsert of every station, route, template,
    # lot and session. The sandbox exists to let someone try the product, and
    # it already locks the rest of the configuration surface; a bulk loader
    # that writes hundreds of rows per request is not what it is for.
    ensure_full_account(ctx)
    # Refs must be unambiguous before anything is touched.
    for kind, refs in (("station", [s.ref for s in doc.stations]),
                       ("process", [p.ref for p in doc.processes]),
                       ("template", [t.ref for t in doc.templates])):
        d = _dupes(refs)
        if d:
            raise HTTPException(422, f"Duplicate {kind} ref(s): {sorted(d)}")

    ent = ctx.entitlement or await entitlements.resolve(session, ctx.company_id,
                                                        user=ctx.user)
    file_providers: set = set()

    # Provider capability is a rule, not just an enum (a shipper cannot be a source).
    for st in doc.stations:
        if st.integrationRole is not None and st.integrationProvider is None:
            raise HTTPException(422, f"Station {st.ref!r}: an integration role needs a provider")
        if st.integrationProvider is not None:
            entitlements.ensure_integrations(ent)
            file_providers.add(st.integrationProvider)
            role = st.integrationRole or "both"
            if not role_allowed(st.integrationProvider, role):
                raise HTTPException(422,
                    f"Station {st.ref!r}: {st.integrationProvider} cannot be bound as '{role}'")

    # Connectors are deliberately unmetered (plans.py) — a file may wire in as
    # many providers as it likes; only the integrations capability was checked
    # above, per bound station.

    # Quotas apply to a file exactly as they apply to the editor.
    #
    # This check used to run only `if ctx.user.isSandbox`, so every *real*
    # account skipped it — and because an import REPLACES the line, the
    # per-create quota never sees these rows either. The result was a side door
    # wide enough to drive MAX_STATIONS (200) through on a 50-station plan.
    for key, count in (("stations", len(doc.stations)), ("processes", len(doc.processes)),
                       ("lot_templates", len(doc.templates))):
        limit = entitlements.limit_for(ent, key)
        if limit is not None and count > limit:
            raise HTTPException(403, {
                "message": (f"This file has {count} {key.replace('_', ' ')}; your "
                            f"{ent.plan.label} plan covers {limit}."),
                "code": "plan_limit", "resource": key,
                "plan": ent.plan.code, "limit": limit, "used": count,
            })

    # ── Out with the old (child before parent; audit log survives). ──
    for table in (SessionRow, CardRow, LotTemplateRow, RouteRow, ProcessRow, StationRow):
        await session.execute(delete(table).where(table.companyId == ctx.company_id))

    # ── Stations ──
    s_id = {}
    for st in doc.stations:
        row = StationRow(
            companyId=ctx.company_id, name=st.name, description=st.description,
            position=st.position.model_dump(), adapterType=None, adapterConfig={},
            color=st.color, icon=st.icon, isStorage=st.isStorage,
            branchMode=st.branchMode,
            integrationProvider=st.integrationProvider,
            integrationRole=(st.integrationRole or ("both" if st.integrationProvider else None)),
        )
        session.add(row)
        await session.flush()
        s_id[st.ref] = row.id

    # ── Processes ──
    p_id = {}
    for pr in doc.processes:
        row = ProcessRow(companyId=ctx.company_id, name=pr.name, description=pr.description,
                         routes=[], mapId=None, desiredTaktSec=pr.desiredTaktSec)
        session.add(row)
        await session.flush()
        p_id[pr.ref] = row.id

    # ── Templates (before routes: demand-link placement wants products named) ──
    t_id = {}
    for t in doc.templates:
        if t.process is not None and t.process not in p_id:
            raise HTTPException(422, f"Template {t.ref!r}: unknown process ref {t.process!r}")
        if t.startStation is not None and t.startStation not in s_id:
            raise HTTPException(422, f"Template {t.ref!r}: unknown station ref {t.startStation!r}")
        row = LotTemplateRow(
            companyId=ctx.company_id, name=t.name, description=t.description,
            processId=p_id.get(t.process), startStationId=s_id.get(t.startStation),
            color=t.color, fields=[f.model_dump() for f in t.fields],
        )
        session.add(row)
        await session.flush()
        t_id[t.ref] = row.id

    # ── Routes, through the same rules as the editor. Production first, then
    #    boundary links (the mirror rule refuses production drawn after a
    #    handoff), then weights once the branch shapes exist. ──
    def _bound(ref: str) -> bool:
        st = next((x for x in doc.stations if x.ref == ref), None)
        return st is not None and st.integrationProvider is not None

    ordered = sorted(doc.routes, key=lambda r: (_bound(r.load) or _bound(r.unload)))
    made: list[tuple[IoRoute, RouteRow]] = []
    for r in ordered:
        for ref, kind in ((r.process, "process"), (r.load, "station"), (r.unload, "station")):
            table = p_id if kind == "process" else s_id
            if ref not in table:
                raise HTTPException(422, f"Route: unknown {kind} ref {ref!r}")
        if r.load == r.unload:
            raise HTTPException(422, f"Route {r.load!r}→{r.unload!r}: load equals unload")
        await _check_boundary_placement(session, ctx.company_id, p_id[r.process],
                                        s_id[r.load], s_id[r.unload])
        edges = await _process_edges(session, ctx.company_id, p_id[r.process])
        if _would_create_cycle(edges, str(s_id[r.load]), str(s_id[r.unload])):
            raise HTTPException(422,
                f"Route {r.load!r}→{r.unload!r} would create a cycle in its process")
        row = RouteRow(companyId=ctx.company_id, processId=p_id[r.process],
                       load=s_id[r.load], unload=s_id[r.unload], quantity=1)
        session.add(row)
        await session.flush()
        made.append((r, row))

    for r, row in made:
        if r.quantity != 1:
            if not await _weight_allowed(session, ctx.company_id, row.load, row.unload,
                                         exclude_id=row.id, process_id=row.processId):
                raise HTTPException(422,
                    f"Route {r.load!r}→{r.unload!r}: a weight of {r.quantity} needs a "
                    "merge feed or a split branch; this route does not branch in its process")
            row.quantity = r.quantity
        if r.outputTemplate is not None:
            if r.outputTemplate not in t_id:
                raise HTTPException(422, f"Route {r.load!r}→{r.unload!r}: unknown template "
                                         f"ref {r.outputTemplate!r}")
            row.outputTemplateId = await _validate_output_template(
                session, ctx.company_id, str(t_id[r.outputTemplate]), row.load, row.processId,
                unload_uuid=row.unload)
        row.updatedAt = utcnow()

    # ── Map scale, if the file carries it ──
    if doc.mapSettings is not None:
        from ..db.connection import get_or_create_singleton
        from ..db.tables import MapSettings as MapSettingsRow
        ms = await get_or_create_singleton(session, MapSettingsRow, ctx.company_id,
                                           floorPlanUrl=None, pixelsPerUnit=100.0, unit="ft",
                                           mapWidthPx=None, mapHeightPx=None, updatedAt=utcnow())
        ms.unit = doc.mapSettings.unit
        ms.pixelsPerUnit = doc.mapSettings.pixelsPerUnit
        ms.stationSizeUnits = doc.mapSettings.stationSizeUnits
        ms.updatedAt = utcnow()

    # The import replaced the whole line — the new station count is the new
    # price, so report it (best-effort; never blocks the import).
    await entitlements.report_station_count(session, ctx.company_id)

    return {
        "stations": len(doc.stations), "processes": len(doc.processes),
        "templates": len(doc.templates), "routes": len(doc.routes),
        "replaced": True,
    }
