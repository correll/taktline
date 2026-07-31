from pydantic import BaseModel, Field
from pydantic_core import core_schema
from datetime import datetime, timezone
from typing import Any


class PyObjectId(str):
    """Opaque string id (a UUID in the Postgres backend).

    Kept under the historical name so the API models are untouched. Accepts a
    ``uuid.UUID`` or any string and always serialises to ``str``.
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> Any:
        return {"type": "string", "example": "f47ac10b-58cc-4372-a567-0e02b2c3d479"}

    @classmethod
    def _validate(cls, v: Any) -> str:
        if v is None:
            raise ValueError("id cannot be None")
        return str(v)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampedModel(BaseModel):
    createdAt: datetime = Field(default_factory=utcnow)
    updatedAt: datetime = Field(default_factory=utcnow)

    model_config = {"populate_by_name": True}


# ── Ceilings on anything that counts units ──────────────────────────────────
#
# Quantities are Postgres `INTEGER` — four bytes. Nothing bounded them, so a
# number past int32 reached the driver and came back as a 500 whose body was
# the failed INSERT, SQL and bound parameters and all. Worse, a value *just
# under* the limit was accepted happily and then overflowed later, because a
# split MULTIPLIES: two numbers that each fit produce one that does not, and
# the operation that discovers this is an ordinary advance on an ordinary
# Tuesday.
#
# The limits are deliberately far below int32 rather than at it, so that the
# split multiply has room and the refusal happens where the person can still
# see what they typed. A Kanban lot of a million pieces is already past
# anything a physical card is attached to, and a bill-of-materials ratio in the
# thousands is past anything an assembly consumes.
MAX_UNITS = 1_000_000
MAX_WEIGHT = 10_000
