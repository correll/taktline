from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from .common import PyObjectId, utcnow

# 'worked' is SYNTHESISED at read time from the work sessions, never stored —
# the timer already records that far better than a duplicate row would, and a
# second copy is a second thing to keep true. The database CHECK constraint
# therefore still knows only the six stored kinds.
EventType = Literal['created', 'moved', 'flagged', 'unflagged', 'updated',
                    'deleted', 'worked']


class CardEvent(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    cardId:       str
    type:         EventType
    fromStation:  Optional[str] = None   # stationId
    toStation:    Optional[str] = None   # stationId
    quantity:     Optional[int] = None
    note:         str = ""
    operatorId:   Optional[str] = None   # set on 'worked'
    durationSec:  Optional[float] = None # set on 'worked'
    timestamp:    datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}


class CardEventCreate(BaseModel):
    cardId:       str
    type:         EventType
    fromStation:  Optional[str] = None
    toStation:    Optional[str] = None
    quantity:     Optional[int] = None
    note:         str = ""
