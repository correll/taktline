from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from .common import PyObjectId, utcnow

EventType = Literal['created', 'moved', 'flagged', 'unflagged', 'updated', 'deleted']


class CardEvent(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    cardId:       str
    type:         EventType
    fromStation:  Optional[str] = None   # stationId
    toStation:    Optional[str] = None   # stationId
    quantity:     Optional[int] = None
    note:         str = ""
    timestamp:    datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}


class CardEventCreate(BaseModel):
    cardId:       str
    type:         EventType
    fromStation:  Optional[str] = None
    toStation:    Optional[str] = None
    quantity:     Optional[int] = None
    note:         str = ""
