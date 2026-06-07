from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal, Optional, Dict, Any
from .common import PyObjectId, TimestampedModel


class Bin(BaseModel):
    count: int = 0

    @field_validator('count')
    @classmethod
    def count_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError('bin count cannot be negative')
        return v


LotStatus = Literal['idle', 'working', 'done']


class Card(TimestampedModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    lotTemplateId: str
    processId: str
    lotNum: Optional[int] = None
    totalQuantity: int = 1
    bins: Dict[str, Bin] = {}
    fields: Dict[str, Any] = {}
    flagged: bool = False
    description: str = ""
    status: LotStatus = 'idle'


class CardCreate(BaseModel):
    lotTemplateId: str
    processId: str
    lotNum: Optional[int] = None
    totalQuantity: int = 1
    bins: Dict[str, Bin] = {}
    fields: Dict[str, Any] = {}
    flagged: bool = False
    description: str = ""
    status: LotStatus = 'idle'

    @field_validator('totalQuantity')
    @classmethod
    def total_quantity_positive(cls, v: int) -> int:
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
    lotNum: Optional[int] = None
    totalQuantity: Optional[int] = None
    bins: Optional[Dict[str, Bin]] = None
    fields: Optional[Dict[str, Any]] = None
    flagged: Optional[bool] = None
    description: Optional[str] = None
    status: Optional[LotStatus] = None

    @field_validator('totalQuantity')
    @classmethod
    def total_quantity_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError('totalQuantity must be at least 1')
        return v
