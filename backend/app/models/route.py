from pydantic import BaseModel, Field
from typing import Optional
from .common import PyObjectId, TimestampedModel


class Route(TimestampedModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    processId: str
    load: str       # source station ID
    unload: str     # destination station ID
    quantity: int = 1   # edge weight: units of this input consumed per assembly cycle


class RouteCreate(BaseModel):
    processId: str
    load: str
    unload: str
    quantity: int = 1


class RouteUpdate(BaseModel):
    load: Optional[str] = None
    unload: Optional[str] = None
    quantity: Optional[int] = None
