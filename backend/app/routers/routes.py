from fastapi import APIRouter, HTTPException, Depends
from typing import List
from bson import ObjectId
from ..db.connection import get_db
from ..models.route import Route, RouteCreate, RouteUpdate
from ..models.common import utcnow

router = APIRouter(prefix="/routes", tags=["routes"])


def _to_route(doc: dict) -> Route:
    return Route(**{**doc, "_id": str(doc["_id"])})


@router.get("/", response_model=List[Route])
async def list_routes(db=Depends(get_db)):
    docs = await db.routes.find().to_list(None)
    return [_to_route(d) for d in docs]


@router.post("/", response_model=Route, status_code=201)
async def create_route(body: RouteCreate, db=Depends(get_db)):
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
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updatedAt"] = utcnow()
    result = await db.routes.find_one_and_update(
        {"_id": ObjectId(route_id)}, {"$set": patch}, return_document=True
    )
    if not result:
        raise HTTPException(404, "Route not found")
    return _to_route(result)


@router.delete("/{route_id}", status_code=204)
async def delete_route(route_id: str, db=Depends(get_db)):
    result = await db.routes.delete_one({"_id": ObjectId(route_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Route not found")
