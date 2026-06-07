from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from bson import ObjectId
from pydantic import BaseModel
from ..db.connection import get_db
from ..models.card import Card, CardCreate, CardUpdate
from ..models.card_event import CardEvent, EventType
from ..models.common import utcnow
from ..plugins.registry import plugin_registry

router = APIRouter(prefix="/cards", tags=["cards"])


def _to_card(doc: dict) -> Card:
    return Card(**{**doc, "_id": str(doc["_id"])})

def _to_event(doc: dict) -> CardEvent:
    return CardEvent(**{**doc, "_id": str(doc["_id"])})


async def _record_event(db, card_id: str, event_type: EventType, **kwargs) -> None:
    evt = {
        "cardId":      card_id,
        "type":        event_type,
        "timestamp":   utcnow(),
        "fromStation": kwargs.get("fromStation"),
        "toStation":   kwargs.get("toStation"),
        "quantity":    kwargs.get("quantity"),
        "note":        kwargs.get("note", ""),
    }
    await db.card_events.insert_one(evt)


# ─── CRUD ─────────────────────────────────────────────────────────────────────

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
    card_id = str(result.inserted_id)
    await _record_event(db, card_id, "created")
    for station_id, bin_data in card.bins.items():
        if bin_data.count > 0:
            await plugin_registry.notify_lot_arrive(station_id, card_id, card.model_dump(mode="json"))
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

    if body.flagged is not None:
        evt_type: EventType = "flagged" if body.flagged else "unflagged"
        await _record_event(db, card_id, evt_type)

    if body.bins is not None:
        old_bins = old_doc.get("bins", {})
        for station_id, bin_data in card.bins.items():
            old_count = old_bins.get(station_id, {}).get("count", 0)
            if bin_data.count > 0 and old_count == 0:
                await plugin_registry.notify_lot_arrive(station_id, card_id, card.model_dump(mode="json"))
            elif bin_data.count == 0 and old_count > 0:
                await plugin_registry.notify_lot_depart(station_id, card_id)
        await _record_event(db, card_id, "updated")

    return card


@router.delete("/{card_id}", status_code=204)
async def delete_card(card_id: str, db=Depends(get_db)):
    doc = await db.cards.find_one({"_id": ObjectId(card_id)})
    if not doc:
        raise HTTPException(404, "Card not found")
    await db.cards.delete_one({"_id": ObjectId(card_id)})
    await _record_event(db, card_id, "deleted")


# ─── Move endpoint ────────────────────────────────────────────────────────────

class MoveBody(BaseModel):
    fromStationId: str
    toStationId:   str
    quantity:      int = 1


@router.post("/{card_id}/move", response_model=Card)
async def move_card(card_id: str, body: MoveBody, db=Depends(get_db)):
    doc = await db.cards.find_one({"_id": ObjectId(card_id)})
    if not doc:
        raise HTTPException(404, "Card not found")

    old_bins = doc.get("bins", {})
    from_count = old_bins.get(body.fromStationId, {}).get("count", 0)
    if body.quantity < 1 or body.quantity > from_count:
        raise HTTPException(400, f"Cannot move {body.quantity}: only {from_count} available at source")

    new_bins = dict(old_bins)
    new_from = from_count - body.quantity
    if new_from <= 0:
        new_bins.pop(body.fromStationId, None)
    else:
        new_bins[body.fromStationId] = {"count": new_from}

    to_count = old_bins.get(body.toStationId, {}).get("count", 0)
    new_bins[body.toStationId] = {"count": to_count + body.quantity}

    result = await db.cards.find_one_and_update(
        {"_id": ObjectId(card_id)},
        {"$set": {"bins": new_bins, "updatedAt": utcnow()}},
        return_document=True,
    )
    card = _to_card(result)

    await _record_event(
        db, card_id, "moved",
        fromStation=body.fromStationId,
        toStation=body.toStationId,
        quantity=body.quantity,
    )

    if from_count > 0 and new_from <= 0:
        await plugin_registry.notify_lot_depart(body.fromStationId, card_id)
    if to_count == 0:
        await plugin_registry.notify_lot_arrive(body.toStationId, card_id, card.model_dump(mode="json"))

    return card


# ─── Events / history ─────────────────────────────────────────────────────────

@router.get("/{card_id}/events", response_model=List[CardEvent])
async def get_card_events(card_id: str, db=Depends(get_db)):
    docs = await db.card_events.find({"cardId": card_id}).sort("timestamp", 1).to_list(None)
    return [_to_event(d) for d in docs]
