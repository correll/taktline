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
    floorPlanOpacity: float          = 1.0   # 0 = hidden, 1 = full strength
    mapWidthPx:       Optional[float] = None
    mapHeightPx:      Optional[float] = None
    updatedAt:        datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}


class MapSettingsUpdate(BaseModel):
    floorPlanUrl:     Optional[str]   = None
    pixelsPerUnit:    Optional[float] = None
    unit:             Optional[Literal['ft', 'm']] = None
    stationSizeUnits: Optional[float] = None
    # Clamped rather than merely documented: an opacity outside 0..1 renders as
    # an invisible or over-bright plan with no error anywhere, and the value
    # arrives from a slider that a script can bypass.
    floorPlanOpacity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    mapWidthPx:       Optional[float] = None
    mapHeightPx:      Optional[float] = None
