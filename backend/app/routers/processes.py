from fastapi import APIRouter, HTTPException, Depends
from typing import List
from bson import ObjectId
from ..db.connection import get_db
from ..models.process import Process, ProcessCreate, ProcessUpdate
from ..models.common import utcnow

router = APIRouter(prefix="/processes", tags=["processes"])


def _to_process(doc: dict) -> Process:
    return Process(**{**doc, "_id": str(doc["_id"])})


@router.get("/", response_model=List[Process])
async def list_processes(db=Depends(get_db)):
    docs = await db.processes.find().to_list(None)
    return [_to_process(d) for d in docs]


@router.post("/", response_model=Process, status_code=201)
async def create_process(body: ProcessCreate, db=Depends(get_db)):
    doc = body.model_dump()
    doc["createdAt"] = doc["updatedAt"] = utcnow()
    result = await db.processes.insert_one(doc)
    created = await db.processes.find_one({"_id": result.inserted_id})
    return _to_process(created)


@router.get("/{process_id}", response_model=Process)
async def get_process(process_id: str, db=Depends(get_db)):
    doc = await db.processes.find_one({"_id": ObjectId(process_id)})
    if not doc:
        raise HTTPException(404, "Process not found")
    return _to_process(doc)


@router.put("/{process_id}", response_model=Process)
async def update_process(process_id: str, body: ProcessUpdate, db=Depends(get_db)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updatedAt"] = utcnow()
    result = await db.processes.find_one_and_update(
        {"_id": ObjectId(process_id)}, {"$set": patch}, return_document=True
    )
    if not result:
        raise HTTPException(404, "Process not found")
    return _to_process(result)


@router.delete("/{process_id}", status_code=204)
async def delete_process(process_id: str, db=Depends(get_db)):
    result = await db.processes.delete_one({"_id": ObjectId(process_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Process not found")
