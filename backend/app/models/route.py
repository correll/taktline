from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
from .common import MAX_WEIGHT, PyObjectId, TimestampedModel


class Route(TimestampedModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    processId: str
    load: str       # source station ID
    unload: str     # destination station ID
    quantity: int = 1   # edge weight: units consumed per assembly (merge) or pieces produced per unit (split)
    outputTemplateId: Optional[str] = None   # product this split branch yields


class RouteCreate(BaseModel):
    processId: str
    load: str
    unload: str
    quantity: int = 1
    outputTemplateId: Optional[str] = None

    @field_validator('quantity')
    @classmethod
    def quantity_at_least_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError('quantity must be at least 1')
        if v > MAX_WEIGHT:
            raise ValueError(f'quantity may not exceed {MAX_WEIGHT:,}')
        return v

    @model_validator(mode='after')
    def no_self_loop(self) -> 'RouteCreate':
        if self.load == self.unload:
            raise ValueError('a route cannot connect a location to itself')
        return self


class RouteUpdate(BaseModel):
    load: Optional[str] = None
    unload: Optional[str] = None
    quantity: Optional[int] = None
    outputTemplateId: Optional[str] = None
    clearOutputTemplate: bool = False   # explicit reset (None means "unchanged")

    @field_validator('quantity')
    @classmethod
    def quantity_at_least_one(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError('quantity must be at least 1')
        if v is not None and v > MAX_WEIGHT:
            raise ValueError(f'quantity may not exceed {MAX_WEIGHT:,}')
        return v
