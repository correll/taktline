from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from .common import PyObjectId, TimestampedModel


class Bin(BaseModel):
    count: int = 0


class Card(TimestampedModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    lotTemplateId: str
    processId: str
    lotNum: Optional[int] = None
    totalQuantity: int = 1
    bins: Dict[str, Bin] = {}       # stationId → Bin
    fields: Dict[str, Any] = {}     # user-defined field values
    flagged: bool = False
    description: str = ""


class CardCreate(BaseModel):
    lotTemplateId: str
    processId: str
    lotNum: Optional[int] = None
    totalQuantity: int = 1
    bins: Dict[str, Bin] = {}
    fields: Dict[str, Any] = {}
    flagged: bool = False
    description: str = ""


class CardUpdate(BaseModel):
    lotNum: Optional[int] = None
    totalQuantity: Optional[int] = None
    bins: Optional[Dict[str, Bin]] = None
    fields: Optional[Dict[str, Any]] = None
    flagged: Optional[bool] = None
    description: Optional[str] = None
