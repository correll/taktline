from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
from .common import utcnow

MachineStatus = Literal["running", "idle", "warning", "fault", "offline"]


class MachineMetric(BaseModel):
    value: Any
    unit: str = ""
    label: str = ""


class MachineState(BaseModel):
    stationId: str
    status: MachineStatus = "offline"
    metrics: Dict[str, MachineMetric] = {}
    currentLotId: Optional[str] = None
    message: str = ""
    lastUpdated: datetime = Field(default_factory=utcnow)


class StationCommand(BaseModel):
    type: str                       # "start" | "stop" | "set_param" | "dispatch_uav"
    params: Dict[str, Any] = {}
