from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator

# Canonical scope catalog. Each integration is granted the minimum it needs:
#   orders        — release pull orders + drain/ack the completion outbox + cancel
#   cards:advance  — advance a lot forward along a route (scan-to-advance / scanners)
#   reports        — read-only order/throughput data for BI (Power BI, Grafana)
AVAILABLE_SCOPES = {
    "orders":       "Release orders, drain completions, cancel",
    "cards:advance": "Advance lots forward (scan-to-advance)",
    "reports":      "Read orders & throughput (BI dashboards)",
}


class ApiKeyCreate(BaseModel):
    name: str
    scopes: List[str] = ["orders"]

    @field_validator("scopes")
    @classmethod
    def _known_scopes(cls, v: List[str]) -> List[str]:
        v = list(dict.fromkeys(v or ["orders"]))   # de-dupe, preserve order
        bad = [s for s in v if s not in AVAILABLE_SCOPES]
        if bad:
            raise ValueError(f"Unknown scope(s): {', '.join(bad)}")
        if not v:
            raise ValueError("At least one scope is required")
        return v


class ApiKeyPublic(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: List[str]
    createdAt: datetime
    lastUsedAt: Optional[datetime] = None
    revoked: bool


class ApiKeyCreated(ApiKeyPublic):
    key: str   # the full secret — shown exactly once, on creation
