from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel

from ..db.connection import get_db
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


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _source_template_ids(db, source_station_id: str) -> list[str]:
    return [
        str(t["_id"])
        async for t in db.lot_templates.find({"startStationId": source_station_id})
    ]


async def _available_units(db, station_id: str, template_ids: list[str]) -> int:
    """Sum of bin counts at station_id across all cards with the given template IDs."""
    if not template_ids:
        return 0
    cards = await db.cards.find({
        "lotTemplateId": {"$in": template_ids},
        f"bins.{station_id}.count": {"$gt": 0},
    }).to_list(None)
    return sum(c.get("bins", {}).get(station_id, {}).get("count", 0) for c in cards)


async def _build_requirements(db, station_id: str, incoming: list[dict]) -> list[RequirementInfo]:
    result: list[RequirementInfo] = []
    for route in incoming:
        source_id = route["load"]
        route_qty = max(1, route.get("quantity", 1))
        tmpl_ids  = await _source_template_ids(db, source_id)
        available = await _available_units(db, station_id, tmpl_ids)
        can_make  = available // route_qty
        result.append(RequirementInfo(
            routeId=str(route["_id"]),
            sourceStationId=source_id,
            requiredPerAssembly=route_qty,
            availableUnits=available,
            canMake=can_make,
        ))
    return result


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/{station_id}", response_model=MergePreview)
async def get_merge_preview(station_id: str, db=Depends(get_db)):
    """Return merge opportunity info with no side effects."""
    incoming = await db.routes.find({"unload": station_id}).to_list(None)

    if len(incoming) < 2:
        return MergePreview(
            isMergeStation=False,
            hasAssemblyTemplate=False,
            assembliesPossible=0,
            requirements=[],
        )

    assembly_tmpl = await db.lot_templates.find_one({"startStationId": station_id})
    requirements  = await _build_requirements(db, station_id, incoming)
    assemblies    = min(r.canMake for r in requirements) if requirements else 0

    return MergePreview(
        isMergeStation=True,
        hasAssemblyTemplate=assembly_tmpl is not None,
        assemblyTemplateId=str(assembly_tmpl["_id"]) if assembly_tmpl else None,
        assemblyTemplateName=assembly_tmpl.get("name")  if assembly_tmpl else None,
        assembliesPossible=assemblies,
        requirements=requirements,
    )


@router.post("/{station_id}", response_model=MergeResult, status_code=201)
async def perform_merge(station_id: str, db=Depends(get_db)):
    """Consume precursor units and create an assembly lot card."""
    incoming = await db.routes.find({"unload": station_id}).to_list(None)

    if len(incoming) < 2:
        raise HTTPException(400, "Not a merge station (fewer than 2 incoming routes)")

    assembly_tmpl = await db.lot_templates.find_one({"startStationId": station_id})
    if not assembly_tmpl:
        raise HTTPException(422, "No assembly template configured for this merge station")

    # Compute assemblies possible
    requirements = await _build_requirements(db, station_id, incoming)
    if not requirements:
        raise HTTPException(400, "No precursor routes found")

    assemblies = min(r.canMake for r in requirements)
    if assemblies < 1:
        raise HTTPException(400, "Not enough precursor units to assemble")

    # Consume precursors route by route, smallest lots first (absorbs dangling lots)
    for route in incoming:
        source_id  = route["load"]
        route_qty  = max(1, route.get("quantity", 1))
        tmpl_ids   = await _source_template_ids(db, source_id)
        to_consume = assemblies * route_qty

        cards = await db.cards.find({
            "lotTemplateId": {"$in": tmpl_ids},
            f"bins.{station_id}.count": {"$gt": 0},
        }).to_list(None)
        # Smallest lots first — ensures dangling single-unit lots are consumed
        cards.sort(key=lambda c: c.get("bins", {}).get(station_id, {}).get("count", 0))

        for card in cards:
            if to_consume <= 0:
                break
            card_id   = card["_id"]
            bin_count = card.get("bins", {}).get(station_id, {}).get("count", 0)
            take      = min(bin_count, to_consume)
            new_count = bin_count - take
            to_consume -= take

            if new_count <= 0:
                new_bins = {k: v for k, v in card.get("bins", {}).items() if k != station_id}
                if not new_bins:
                    await db.cards.delete_one({"_id": card_id})
                else:
                    await db.cards.update_one(
                        {"_id": card_id},
                        {"$set": {"bins": new_bins, "updatedAt": utcnow()}},
                    )
            else:
                await db.cards.update_one(
                    {"_id": card_id},
                    {"$set": {f"bins.{station_id}.count": new_count, "updatedAt": utcnow()}},
                )

    # Derive processId from any incoming route
    process_id = incoming[0].get("processId", "")

    new_doc = {
        "lotTemplateId": str(assembly_tmpl["_id"]),
        "processId":     process_id,
        "lotNum":        None,
        "totalQuantity": assemblies,
        "bins":          {station_id: {"count": assemblies}},
        "fields":        {},
        "flagged":       False,
        "description":   "",
        "status":        "idle",
        "createdAt":     utcnow(),
        "updatedAt":     utcnow(),
    }
    result = await db.cards.insert_one(new_doc)

    return MergeResult(assemblies=assemblies, createdCardId=str(result.inserted_id))
