from fastapi import APIRouter, HTTPException, Depends
from typing import List
from bson import ObjectId
from ..db.connection import get_db
from ..models.lot_template import LotTemplate, LotTemplateCreate, LotTemplateUpdate
from ..models.common import utcnow

router = APIRouter(prefix="/lot-templates", tags=["lot-templates"])


def _to_template(doc: dict) -> LotTemplate:
    return LotTemplate(**{**doc, "_id": str(doc["_id"])})


@router.get("/", response_model=List[LotTemplate])
async def list_templates(db=Depends(get_db)):
    docs = await db.lot_templates.find().to_list(None)
    return [_to_template(d) for d in docs]


@router.post("/", response_model=LotTemplate, status_code=201)
async def create_template(body: LotTemplateCreate, db=Depends(get_db)):
    doc = body.model_dump()
    doc["createdAt"] = doc["updatedAt"] = utcnow()
    result = await db.lot_templates.insert_one(doc)
    created = await db.lot_templates.find_one({"_id": result.inserted_id})
    return _to_template(created)


@router.get("/{template_id}", response_model=LotTemplate)
async def get_template(template_id: str, db=Depends(get_db)):
    doc = await db.lot_templates.find_one({"_id": ObjectId(template_id)})
    if not doc:
        raise HTTPException(404, "Template not found")
    return _to_template(doc)


@router.put("/{template_id}", response_model=LotTemplate)
async def update_template(template_id: str, body: LotTemplateUpdate, db=Depends(get_db)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updatedAt"] = utcnow()
    result = await db.lot_templates.find_one_and_update(
        {"_id": ObjectId(template_id)}, {"$set": patch}, return_document=True
    )
    if not result:
        raise HTTPException(404, "Template not found")
    return _to_template(result)


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: str, db=Depends(get_db)):
    result = await db.lot_templates.delete_one({"_id": ObjectId(template_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Template not found")
