from bson import ObjectId
from pydantic import BaseModel, Field
from pydantic_core import core_schema
from datetime import datetime, timezone
from typing import Any


class PyObjectId(str):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        return core_schema.no_info_plain_validator_function(cls._validate)

    @classmethod
    def _validate(cls, v: Any) -> str:
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, str) and ObjectId.is_valid(v):
            return v
        raise ValueError(f"Invalid ObjectId: {v!r}")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampedModel(BaseModel):
    createdAt: datetime = Field(default_factory=utcnow)
    updatedAt: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}
