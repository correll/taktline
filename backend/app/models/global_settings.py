from pydantic import BaseModel, Field
from typing import Optional
from .common import PyObjectId


class GlobalSettings(BaseModel):
    id:       Optional[PyObjectId] = Field(default=None, alias="_id")
    timezone: str = "UTC"

    model_config = {"populate_by_name": True}


class GlobalSettingsUpdate(BaseModel):
    timezone: Optional[str] = None
