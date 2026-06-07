from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from .common import PyObjectId, utcnow


class WorkSession(BaseModel):
    id:          Optional[PyObjectId] = Field(default=None, alias="_id")
    stationId:   str
    cardId:      Optional[str] = None
    operatorId:  str = "default"
    quantity:    int = 1
    startedAt:   datetime = Field(default_factory=utcnow)
    endedAt:     Optional[datetime] = None
    durationSec: Optional[float] = None   # computed on close

    model_config = {"populate_by_name": True}


class SessionCreate(BaseModel):
    stationId:  str
    cardId:     Optional[str] = None
    operatorId: str = "default"
    quantity:   int = 1


class SessionEnd(BaseModel):
    quantity: Optional[int] = None   # override if changed during work
