"""Pydantic schemas for production orders and the integration outbox."""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


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
