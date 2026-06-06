from fastapi import APIRouter, HTTPException, Depends
from typing import List
from bson import ObjectId
from ..db.connection import get_db
from ..models.card import Card, CardCreate, CardUpdate
from ..models.common import utcnow
from ..plugins.registry import plugin_registry

router = APIRouter(prefix="/cards", tags=["cards"])


def _to_card(doc: dict) -> Card:
    return Card(**{**doc, "_id": str(doc["_id"])})


@router.get("/", response_model=List[Card])
async def list_cards(db=Depends(get_db)):
    docs = await db.cards.find().to_list(None)
    return [_to_card(d) for d in docs]


@router.post("/", response_model=Card, status_code=201)
async def create_card(body: CardCreate, db=Depends(get_db)):
    doc = body.model_dump()
    doc["createdAt"] = doc["updatedAt"] = utcnow()
    result = await db.cards.insert_one(doc)
    created = await db.cards.find_one({"_id": result.inserted_id})
    card = _to_card(created)
    for station_id, bin_data in card.bins.items():
        if bin_data.count > 0:
            await plugin_registry.notify_lot_arrive(station_id, str(card.id), card.model_dump(mode="json"))
    return card


@router.get("/{card_id}", response_model=Card)
async def get_card(card_id: str, db=Depends(get_db)):
    doc = await db.cards.find_one({"_id": ObjectId(card_id)})
    if not doc:
        raise HTTPException(404, "Card not found")
    return _to_card(doc)


@router.put("/{card_id}", response_model=Card)
async def update_card(card_id: str, body: CardUpdate, db=Depends(get_db)):
    old_doc = await db.cards.find_one({"_id": ObjectId(card_id)})
    if not old_doc:
        raise HTTPException(404, "Card not found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updatedAt"] = utcnow()
    result = await db.cards.find_one_and_update(
        {"_id": ObjectId(card_id)}, {"$set": patch}, return_document=True
    )
    card = _to_card(result)
    if body.bins is not None:
        old_bins = old_doc.get("bins", {})
        for station_id, bin_data in card.bins.items():
            old_count = old_bins.get(station_id, {}).get("count", 0)
            if bin_data.count > 0 and old_count == 0:
                await plugin_registry.notify_lot_arrive(station_id, card_id, card.model_dump(mode="json"))
            elif bin_data.count == 0 and old_count > 0:
                await plugin_registry.notify_lot_depart(station_id, card_id)
    return card


@router.delete("/{card_id}", status_code=204)
async def delete_card(card_id: str, db=Depends(get_db)):
    result = await db.cards.delete_one({"_id": ObjectId(card_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Card not found")
