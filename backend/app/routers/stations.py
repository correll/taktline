from fastapi import APIRouter, HTTPException, Depends
from typing import List
from bson import ObjectId
from ..db.connection import get_db
from ..models.station import Station, StationCreate, StationUpdate
from ..models.common import utcnow
from ..plugins.registry import plugin_registry

router = APIRouter(prefix="/stations", tags=["stations"])


def _to_station(doc: dict) -> Station:
    return Station(**{**doc, "_id": str(doc["_id"])})


@router.get("/", response_model=List[Station])
async def list_stations(db=Depends(get_db)):
    docs = await db.stations.find().to_list(None)
    return [_to_station(d) for d in docs]


@router.post("/", response_model=Station, status_code=201)
async def create_station(body: StationCreate, db=Depends(get_db)):
    doc = body.model_dump()
    doc["createdAt"] = doc["updatedAt"] = utcnow()
    result = await db.stations.insert_one(doc)
    created = await db.stations.find_one({"_id": result.inserted_id})
    station = _to_station(created)
    if station.adapterType:
        await plugin_registry.register(str(station.id), station.adapterType, station.adapterConfig)
    return station


@router.get("/{station_id}", response_model=Station)
async def get_station(station_id: str, db=Depends(get_db)):
    doc = await db.stations.find_one({"_id": ObjectId(station_id)})
    if not doc:
        raise HTTPException(404, "Station not found")
    return _to_station(doc)


@router.put("/{station_id}", response_model=Station)
async def update_station(station_id: str, body: StationUpdate, db=Depends(get_db)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updatedAt"] = utcnow()
    result = await db.stations.find_one_and_update(
        {"_id": ObjectId(station_id)},
        {"$set": patch},
        return_document=True,
    )
    if not result:
        raise HTTPException(404, "Station not found")
    station = _to_station(result)
    if "adapterType" in patch or "adapterConfig" in patch:
        await plugin_registry.unregister(station_id)
        if station.adapterType:
            await plugin_registry.register(station_id, station.adapterType, station.adapterConfig)
    return station


@router.delete("/{station_id}", status_code=204)
async def delete_station(station_id: str, db=Depends(get_db)):
    result = await db.stations.delete_one({"_id": ObjectId(station_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Station not found")
    await plugin_registry.unregister(station_id)


@router.post("/{station_id}/command")
async def send_command(station_id: str, body: dict):
    from ..models.machine_state import StationCommand
    cmd = StationCommand(**body)
    ok = await plugin_registry.send_command(station_id, cmd)
    if not ok:
        raise HTTPException(404, "No adapter found for this station")
    return {"ok": True}
