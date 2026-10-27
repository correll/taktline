from pydantic import BaseModel, Field, field_validator
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
    # Storage, not work: excluded from the heatmap, utilisation and accumulation warnings.
    isStorage: bool = False
    supplierUrl: Optional[str] = None
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
    supplierUrl: Optional[str] = None

    @field_validator('supplierUrl')
    @classmethod
    def _clean_supplier(cls, v):
        """Only a real tracking link gets stored.

        This value is later rendered and fetched by a browser, so it is
        validated at the boundary rather than at the point of use — a
        `javascript:` URL in a field that becomes an href is the oldest trick
        there is. `network.parse_tracking_url` also strips query and fragment,
        so nothing can be smuggled through.
        """
        if v is None or v == "":
            return None
        from ..core.network import parse_tracking_url
        clean = parse_tracking_url(v)
        if clean is None:
            raise ValueError("not a Taktline tracking link")
        return clean

