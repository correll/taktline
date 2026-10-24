from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

from .common import PyObjectId
from ..core import languages
from ..core.schedule import MAX_BREAKS, default_work_hours, normalise_breaks


def _valid_grid(v: List[List[int]]) -> List[List[int]]:
    if len(v) != 7 or any(len(row) != 24 for row in v):
        raise ValueError("workHours must be a 7×24 grid")
    # Each cell is a 4-bit quarter mask (0–15); see core.schedule.
    return [[max(0, min(15, int(c))) for c in row] for row in v]


class GlobalSettings(BaseModel):
    id:        Optional[PyObjectId] = Field(default=None, alias="_id")
    timezone:  str = "UTC"
    workHours: List[List[int]] = Field(default_factory=default_work_hours)
    # Breaks as minutes of the local day, [[start, end], ...]: not open time.
    breaks: List[List[int]] = Field(default_factory=list)
    # Station-level pace feedback (against measured cycle time) in the Operator view. Never per-operator.
    showCycleArc: bool = False
    orderTracking: bool = False
    orderTrackingSteps: bool = True
    # Answer MCP calls from AI agents (core/mcp.py). Off until switched on.
    mcpEnabled: bool = False
    supportedLanguages: List[str] = Field(
        default_factory=lambda: list(languages.LANGUAGES))

    model_config = {"populate_by_name": True}


class GlobalSettingsUpdate(BaseModel):
    timezone:  Optional[str] = None
    workHours: Optional[List[List[int]]] = None
    breaks: Optional[List[List[int]]] = None
    showCycleArc: Optional[bool] = None
    orderTracking: Optional[bool] = None
    orderTrackingSteps: Optional[bool] = None
    mcpEnabled: Optional[bool] = None
    supportedLanguages: Optional[List[str]] = None

    @field_validator("workHours")
    @classmethod
    def _check(cls, v):
        return None if v is None else _valid_grid(v)

    @field_validator("breaks")
    @classmethod
    def _breaks(cls, v):
        if v is None:
            return None
        if len(v) > MAX_BREAKS:
            raise ValueError(f"at most {MAX_BREAKS} breaks")
        for b in v:
            if len(b) != 2 or not (0 <= int(b[0]) < int(b[1]) <= 24 * 60):
                raise ValueError("a break is [start, end] in minutes of the day, start before end")
        return normalise_breaks(v)

    @field_validator("supportedLanguages")
    @classmethod
    def _langs(cls, v):
        return None if v is None else languages.clean_supported(v)
