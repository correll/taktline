from fastapi import APIRouter, HTTPException, Depends
from typing import List
from bson import ObjectId
from ..db.connection import get_db
from ..models.route import Route, RouteCreate, RouteUpdate
from ..models.common import utcnow

router = APIRouter(prefix="/routes", tags=["routes"])


def _to_route(doc: dict) -> Route:
    return Route(**{**doc, "_id": str(doc["_id"])})


async def _would_create_cycle(db, process_id: str, new_load: str, new_unload: str) -> bool:
    """DFS from new_unload to check if new_load is reachable (which would form a cycle)."""
    existing = await db.routes.find({"processId": process_id}).to_list(None)
    adj: dict[str, list[str]] = {}
    for r in existing:
        adj.setdefault(r["load"], []).append(r["unload"])
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
async def list_routes(db=Depends(get_db)):
    docs = await db.routes.find().to_list(None)
    return [_to_route(d) for d in docs]


@router.post("/", response_model=Route, status_code=201)
async def create_route(body: RouteCreate, db=Depends(get_db)):
    # Reject duplicate route in same process
    dup = await db.routes.find_one(
        {"processId": body.processId, "load": body.load, "unload": body.unload}
    )
    if dup:
        raise HTTPException(400, "Route already exists between these two locations")

    # Reject if adding this edge would create a cycle
    if await _would_create_cycle(db, body.processId, body.load, body.unload):
        raise HTTPException(400, "This route would create a cycle in the process graph")

    doc = body.model_dump()
    doc["createdAt"] = doc["updatedAt"] = utcnow()
    result = await db.routes.insert_one(doc)
    created = await db.routes.find_one({"_id": result.inserted_id})
    return _to_route(created)


@router.get("/{route_id}", response_model=Route)
async def get_route(route_id: str, db=Depends(get_db)):
    doc = await db.routes.find_one({"_id": ObjectId(route_id)})
    if not doc:
        raise HTTPException(404, "Route not found")
    return _to_route(doc)


@router.put("/{route_id}", response_model=Route)
async def update_route(route_id: str, body: RouteUpdate, db=Depends(get_db)):
    existing = await db.routes.find_one({"_id": ObjectId(route_id)})
    if not existing:
        raise HTTPException(404, "Route not found")

    # If load or unload are changing, re-validate for self-loop and cycles
    new_load   = body.load   or existing["load"]
    new_unload = body.unload or existing["unload"]
    if new_load == new_unload:
        raise HTTPException(400, "A route cannot connect a location to itself")

    if body.load or body.unload:
        # Exclude self from graph before checking cycle
        other_routes = await db.routes.find(
            {"processId": existing["processId"], "_id": {"$ne": existing["_id"]}}
        ).to_list(None)
        adj: dict[str, list[str]] = {}
        for r in other_routes:
            adj.setdefault(r["load"], []).append(r["unload"])
        adj.setdefault(new_load, []).append(new_unload)
        visited: set[str] = set()
        stack = [new_unload]
        cycle = False
        while stack:
            node = stack.pop()
            if node == new_load:
                cycle = True
                break
            if node in visited:
                continue
            visited.add(node)
            stack.extend(adj.get(node, []))
        if cycle:
            raise HTTPException(400, "This change would create a cycle in the process graph")

    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updatedAt"] = utcnow()
    result = await db.routes.find_one_and_update(
        {"_id": ObjectId(route_id)}, {"$set": patch}, return_document=True
    )
    return _to_route(result)


@router.delete("/{route_id}", status_code=204)
async def delete_route(route_id: str, db=Depends(get_db)):
    result = await db.routes.delete_one({"_id": ObjectId(route_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Route not found")
