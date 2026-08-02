from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal, Optional, Dict, Any
from .common import MAX_UNITS, PyObjectId, TimestampedModel


class Bin(BaseModel):
    count: int = 0

    @field_validator('count')
    @classmethod
    def count_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError('bin count cannot be negative')
        return v


LotStatus = Literal['idle', 'working', 'done']


def _clean_lot_num(v: Optional[str]) -> Optional[str]:
    """Lot code: user-defined or generated (e.g. "E4096A"). Trim; empty → None
    (the backend then generates one); cap length for label printing."""
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    if len(v) > 24:
        raise ValueError('lotNum must be at most 24 characters')
    return v


class Card(TimestampedModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    lotTemplateId: str
    processId: str
    lotNum: Optional[str] = None
    totalQuantity: int = 1
    bins: Dict[str, Bin] = {}
    fields: Dict[str, Any] = {}
    flagged: bool = False
    description: str = ""
    status: LotStatus = 'idle'
    orderId: Optional[str] = None      # set when released by a production order
    #: Read-only link for the customer who ordered this lot. Always
    #: present; the page only answers while the company has customer
    #: order tracking switched on (Settings → Global).
    trackingUrl: Optional[str] = None


class CardCreate(BaseModel):
    lotTemplateId: str
    processId: str
    lotNum: Optional[str] = None
    totalQuantity: int = 1
    bins: Dict[str, Bin] = {}
    fields: Dict[str, Any] = {}
    flagged: bool = False
    description: str = ""
    status: LotStatus = 'idle'

    @field_validator('lotNum')
    @classmethod
    def _clean_lot(cls, v: Optional[str]) -> Optional[str]:
        return _clean_lot_num(v)

    @field_validator('totalQuantity')
    @classmethod
    def total_quantity_positive(cls, v: int) -> int:
        if v is not None and v > MAX_UNITS:
            raise ValueError(f'totalQuantity may not exceed {MAX_UNITS:,}')
        if v < 1:
            raise ValueError('totalQuantity must be at least 1')
        return v

    @model_validator(mode='after')
    def bins_within_total(self) -> 'CardCreate':
        total_in_bins = sum(b.count for b in self.bins.values())
        if total_in_bins > self.totalQuantity:
            raise ValueError(
                f'sum of bin counts ({total_in_bins}) exceeds totalQuantity ({self.totalQuantity})'
            )
        return self


class CardUpdate(BaseModel):
    lotNum: Optional[str] = None
    totalQuantity: Optional[int] = None
    bins: Optional[Dict[str, Bin]] = None
    fields: Optional[Dict[str, Any]] = None
    flagged: Optional[bool] = None
    description: Optional[str] = None
    status: Optional[LotStatus] = None

    @field_validator('lotNum')
    @classmethod
    def _clean_lot(cls, v: Optional[str]) -> Optional[str]:
        return _clean_lot_num(v)

    @field_validator('totalQuantity')
    @classmethod
    def total_quantity_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError('totalQuantity must be at least 1')
        return v
