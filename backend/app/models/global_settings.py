from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

from .common import PyObjectId
from ..core.schedule import default_work_hours


def _valid_grid(v: List[List[int]]) -> List[List[int]]:
    if len(v) != 7 or any(len(row) != 24 for row in v):
        raise ValueError("workHours must be a 7×24 grid")
    # Each cell is a 4-bit quarter mask (0–15); see core.schedule.
    return [[max(0, min(15, int(c))) for c in row] for row in v]


class GlobalSettings(BaseModel):
    id:        Optional[PyObjectId] = Field(default=None, alias="_id")
    timezone:  str = "UTC"
    workHours: List[List[int]] = Field(default_factory=default_work_hours)
    # Station-level pace feedback (against measured cycle time) in the Operator view. Never per-operator.
    showCycleArc: bool = False
    orderTracking: bool = False
    orderTrackingSteps: bool = True

    model_config = {"populate_by_name": True}


class GlobalSettingsUpdate(BaseModel):
    timezone:  Optional[str] = None
    workHours: Optional[List[List[int]]] = None
    showCycleArc: Optional[bool] = None
    orderTracking: Optional[bool] = None
    orderTrackingSteps: Optional[bool] = None

    @field_validator("workHours")
    @classmethod
    def _check(cls, v):
        return None if v is None else _valid_grid(v)
