from pydantic import BaseModel, Field
from typing import Optional, Literal
from .common import PyObjectId, utcnow
from datetime import datetime


class MapSettings(BaseModel):
    id:               Optional[PyObjectId] = Field(default=None, alias="_id")
    floorPlanUrl:     Optional[str]  = None
    pixelsPerUnit:    float          = 100.0  # original PNG pixels per one real-world unit
    unit:             Literal['ft', 'm'] = 'ft'
    stationSizeUnits: float          = 1.0   # station square side-length in real-world units
    mapWidthPx:       Optional[float] = None
    mapHeightPx:      Optional[float] = None
    updatedAt:        datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}


class MapSettingsUpdate(BaseModel):
    floorPlanUrl:     Optional[str]   = None
    pixelsPerUnit:    Optional[float] = None
    unit:             Optional[Literal['ft', 'm']] = None
    stationSizeUnits: Optional[float] = None
    mapWidthPx:       Optional[float] = None
    mapHeightPx:      Optional[float] = None
