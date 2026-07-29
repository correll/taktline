from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from .common import PyObjectId, TimestampedModel


class StationPosition(BaseModel):
    x: float = 0.0
    y: float = 0.0
    width: float = 60.0
    height: float = 60.0


class Station(TimestampedModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str
    position: StationPosition = Field(default_factory=StationPosition)
    adapterType: Optional[str] = None      # "mock" | "plc_modbus" | "plc_opc_ua" | "uav"
    adapterConfig: Dict[str, Any] = {}
    description: str = ""
    color: Optional[str] = None
    icon: Optional[str] = None             # lucide icon id, e.g. "Warehouse"
    # Where work enters/leaves the business. None on an ordinary work location.
    integrationProvider: Optional[str] = None   # 'odoo' | 'shopify' | 'shipstation' | …
    integrationRole: Optional[str] = None       # 'source' | 'sink' | 'both'
    # Storage, not work: excluded from the heatmap, OEE and accumulation warnings.
    isStorage: bool = False
    # What multiple outgoing routes mean here: 'split' (default) fans a lot out
    # to every branch at once; 'choice' moves each lot 1:1 down one chosen branch.
    branchMode: Optional[str] = None


class StationCreate(BaseModel):
    name: str
    position: StationPosition = Field(default_factory=StationPosition)
    adapterType: Optional[str] = None
    adapterConfig: Dict[str, Any] = {}
    description: str = ""
    color: Optional[str] = None
    icon: Optional[str] = None
    integrationProvider: Optional[str] = None
    integrationRole: Optional[str] = None
    isStorage: bool = False
    branchMode: Optional[str] = None


class StationUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[StationPosition] = None
    adapterType: Optional[str] = None
    adapterConfig: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    integrationProvider: Optional[str] = None
    integrationRole: Optional[str] = None
    isStorage: Optional[bool] = None
    branchMode: Optional[str] = None
