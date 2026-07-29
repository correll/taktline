from pydantic import BaseModel, Field
from typing import Optional, List
from .common import PyObjectId, TimestampedModel


class Process(TimestampedModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str
    routes: List[str] = []
    mapId: Optional[str] = None
    description: str = ""
    # Desired takt: the interval the line is meant to hold (seconds).
    desiredTaktSec: Optional[float] = None


class ProcessCreate(BaseModel):
    name: str
    routes: List[str] = []
    mapId: Optional[str] = None
    description: str = ""
    desiredTaktSec: Optional[float] = None


class ProcessUpdate(BaseModel):
    name: Optional[str] = None
    routes: Optional[List[str]] = None
    mapId: Optional[str] = None
    description: Optional[str] = None
    desiredTaktSec: Optional[float] = None
