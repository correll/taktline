from pydantic import BaseModel, Field
from typing import Optional, List
from .common import PyObjectId, TimestampedModel


class FieldDefinition(BaseModel):
    key: str
    label: str
    type: str = "text"       # "text" | "number" | "date" | "select"
    options: List[str] = []
    required: bool = False


class LotTemplate(TimestampedModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str
    processId: Optional[str] = None
    startStationId: Optional[str] = None
    fields: List[FieldDefinition] = []
    color: Optional[str] = None
    description: str = ""


class LotTemplateCreate(BaseModel):
    name: str
    processId: Optional[str] = None
    startStationId: Optional[str] = None
    fields: List[FieldDefinition] = []
    color: Optional[str] = None
    description: str = ""


class LotTemplateUpdate(BaseModel):
    name: Optional[str] = None
    processId: Optional[str] = None
    startStationId: Optional[str] = None
    fields: Optional[List[FieldDefinition]] = None
    color: Optional[str] = None
    description: Optional[str] = None
