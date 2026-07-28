"""Pydantic schemas for production orders and the integration outbox."""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, field_validator


class OrderCreate(BaseModel):
    productTemplateId: str
    quantity: int
    # Where to release the run. Defaults to the product template's origination
    # station (the top merge for an assembled product).
    mergeStationId: Optional[str] = None
    source: str = "manual"            # manual | odoo | netsuite
    externalRef: Optional[str] = None  # ERP order id (idempotency key)
    # Human lot code printed on the released Kanban card(s), e.g. a Shopify order
    # name "#1001" or an Odoo MO reference "MO/00042". Optional — when omitted the
    # order's externalRef is used, so the lot always traces back to its ERP order.
    lotCode: Optional[str] = None
    note: str = ""
    # ERP-provided context riding along with the release: customer, due date,
    # ship-to, priority. Deliberately a FLAT map of scalars — it is stamped onto
    # every seeded lot's fields (so it shows on the card and survives the whole
    # journey) and echoed back to the sink at handoff. Nesting would make it
    # unprintable on a Kanban card, and unbounded blobs would make every card
    # heavy, hence the caps.
    attributes: Dict[str, Any] = {}

    @field_validator("attributes")
    @classmethod
    def _flat_and_bounded(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if len(v) > 32:
            raise ValueError("attributes: at most 32 keys")
        out: Dict[str, Any] = {}
        for k, val in v.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError("attributes: keys must be non-empty strings")
            if val is not None and not isinstance(val, (str, int, float, bool)):
                raise ValueError(f"attributes[{k!r}]: values must be scalars")
            if isinstance(val, str) and len(val) > 500:
                val = val[:500]
            out[k.strip()] = val
        return out


class CancelByRef(BaseModel):
    """Cancel an order the connector only knows by its ERP reference — the
    Shopify/Woo path (cancel/refund) that doesn't have the Taktline order id."""
    source: str
    externalRef: str


class OrderPublic(BaseModel):
    id: str
    source: str
    externalRef: Optional[str] = None
    productTemplateId: Optional[str] = None
    mergeStationId: Optional[str] = None
    quantity: int
    quantityDone: int
    status: str
    note: str
    attributes: Dict[str, Any] = {}
    createdAt: datetime
    updatedAt: datetime


class OutboxEvent(BaseModel):
    id: str
    orderId: Optional[str] = None
    eventType: str
    payload: Dict[str, Any]
    status: str
    attempts: int
    createdAt: datetime
