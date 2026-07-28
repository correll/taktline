"""The integration partners Taktline knows how to bind a location to.

An **integration location** is where work enters or leaves the business. Until
now that boundary was implicit in the shape of the graph — any leaf with no
incoming routes could originate lots, and *any* leaf with no outgoing routes
completed orders — so nothing in Taktline knew that a particular dock belonged
to Shopify, or which of two finished-goods leaves was the one that ships.

Binding a provider to a station makes it explicit and answers three things the
topology alone could not:

* where work enters (a goods-in dock that a release seeds), and
* where it leaves, and
* **which connector to tell when it does**, independently of which connector
  released the order. That last one is why a manually released order landing on
  a ShipStation dock can now be delivered at all; before, its completion event
  carried ``source='manual'`` and no connector could ever ack it.

The role is what a partner can be, not what it is called:

* ``source`` — releases arrive from it (a purchase order, a store order)
* ``sink``   — finished goods leave through it (ShipStation)
* ``both``   — most full ERPs

Kept server-side as well as in the frontend registry because the API validates
against it; the frontend copy carries the brand colours and letter marks, which
the server has no use for.
"""

from typing import Literal

IntegrationRole = Literal["source", "sink", "both"]

ROLES: set[str] = {"source", "sink", "both"}

# provider id → what the partner is *capable of*, which also serves as the
# default when binding one. This is not cosmetic: a shipper genuinely cannot
# raise demand — there is no such thing as a ShipStation order asking the line
# to make something — so binding one as a source has to be refused rather than
# quietly accepted and then never firing.
#
# The id matches the connector module name in connectors/taktline_connect/,
# which is what makes `payload.source` line up with the connector polling for it.
PROVIDERS: dict[str, str] = {
    "odoo":          "both",
    "netsuite":      "both",
    "shopify":       "both",
    "woocommerce":   "both",
    "qbo":           "both",
    "xero":          "both",
    "shipstation":   "sink",     # a shipper: goods leave, orders do not start here
    "generic":       "both",     # poll any JSON endpoint
    "manual":        "source",   # the UI / CSV import, given a home of its own
}


def is_provider(value: str | None) -> bool:
    return value is not None and value in PROVIDERS


def default_role(provider: str) -> str:
    return PROVIDERS.get(provider, "both")


def role_allowed(provider: str, role: str) -> bool:
    """A partner may only be bound to a role it can actually play."""
    capability = PROVIDERS.get(provider, "both")
    if capability == "both":
        return role in ROLES
    return role == capability


def can_sink(provider: str | None, role: str | None) -> bool:
    return provider is not None and role in ("sink", "both")


def can_source(provider: str | None, role: str | None) -> bool:
    return provider is not None and role in ("source", "both")
