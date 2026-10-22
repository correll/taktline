from pydantic import BaseModel, Field
from typing import Literal, Optional
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
    durationSec: Optional[float] = None   # work only: stoppages excluded
    pausedSec:   float = 0.0              # stoppage time inside the session
    pausedAt:    Optional[datetime] = None  # set while paused
    pauseReason: Optional[str] = None
    closedBy:    Optional[str] = None     # operator | move | next_start

    model_config = {"populate_by_name": True}


class SessionCreate(BaseModel):
    stationId:  str
    cardId:     Optional[str] = None
    operatorId: str = "default"
    quantity:   int = 1


class SessionEnd(BaseModel):
    quantity: Optional[int] = None   # override if changed during work


StoppageReason = Literal["breakdown", "changeover", "material", "other"]


class SessionPause(BaseModel):
    reason: StoppageReason = "breakdown"


class Stoppage(BaseModel):
    id:          Optional[PyObjectId] = Field(default=None, alias="_id")
    stationId:   str
    sessionId:   Optional[str] = None
    operatorId:  str = "default"
    reason:      StoppageReason
    startedAt:   datetime
    endedAt:     Optional[datetime] = None
    durationSec: Optional[float] = None

    model_config = {"populate_by_name": True}


class StoppageCreate(BaseModel):
    """A stop with no session running: a breakdown while idle, a changeover
    between lots, a wait for material."""
    stationId:  str
    reason:     StoppageReason
    operatorId: str = "default"
