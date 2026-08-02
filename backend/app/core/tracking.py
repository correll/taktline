"""Order tracking: a read-only link a shop can give its own customer.

"Where is my order?" is a phone call every job shop takes several times a week,
and answering it is the one thing a live board is uniquely good at. Handing the
customer a link answers it once and for all — and puts Taktline in front of
exactly the people who run other factories, which is the only viral loop this
product has that a stranger has a business reason to open.

Three things make it safe to point at a customer.

**It is opt-in per company** (`GlobalSettings.orderTracking`, default off).
Publishing anything about production is a decision for the shop, not a default
we choose for them.

**The token is derived, not stored.** HMAC of the order id under the app secret,
so there is no column, nothing to leak in a backup, and no way to enumerate
orders by guessing. Turning the setting off stops every link at once — the token
still verifies, but `resolve` refuses — and turning it back on restores the same
links rather than invalidating every one a customer has bookmarked.

**It answers exactly one question.** One order: what it is, how far along, when
it moved. No other order, no other customer, no prices, no station detail beyond
the step it is on — and even that is a separate switch, because a shop's process
is its own business and some will not want it described to the people buying
from them.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings

#: Long enough that guessing is hopeless, short enough to paste into an email.
_TOKEN_CHARS = 24


def _secret() -> bytes:
    # The same derivation the trial opt-out uses: a value that is already secret
    # and already deployment-specific, so there is no new key to manage or
    # rotate — and rotating the database URL invalidates old links, which is the
    # correct blast radius for something this low-stakes.
    return (settings.stripe_webhook_secret or settings.database_url).encode()


def token_for(order_id) -> str:
    return hmac.new(_secret(), f"order-track:{order_id}".encode(),
                    hashlib.sha256).hexdigest()[:_TOKEN_CHARS]


def verify(order_id, token: str) -> bool:
    return hmac.compare_digest(token_for(order_id), token or "")


@dataclass(frozen=True)
class Step:
    name: str
    #: Units of this order currently sitting here.
    units: int
    done: bool
    current: bool


@dataclass(frozen=True)
class Tracked:
    reference: str
    product: str
    quantity: int
    quantity_done: int
    status: str
    #: None when the shop has chosen not to describe its process.
    steps: Optional[list]
    step_index: Optional[int]
    step_total: Optional[int]
    updated_at: Optional[object]
    show_steps: bool

    @property
    def percent(self) -> int:
        if self.quantity <= 0:
            return 0
        if self.status == "completed":
            return 100
        by_units = self.quantity_done / self.quantity
        # Before the first unit is finished, position on the line is the only
        # signal there is — otherwise a customer watching an order that is
        # genuinely half-built sees a flat 0% for days and concludes nothing is
        # happening.
        if self.step_total and self.step_index is not None and by_units == 0:
            return int(min(95, (self.step_index / max(1, self.step_total)) * 100))
        return int(min(100, by_units * 100))


async def enabled_for(session: AsyncSession, company_id) -> tuple[bool, bool]:
    """(tracking on, show step names)."""
    from ..db.tables import GlobalSettings

    row = (await session.execute(
        select(GlobalSettings).where(GlobalSettings.companyId == company_id)
    )).scalars().first()
    if row is None:
        return False, False
    return bool(row.orderTracking), bool(row.orderTrackingSteps)


async def _ordered_stations(session: AsyncSession, company_id, process_id) -> list:
    """The process's stations in flow order.

    A topological walk over the production routes. Cycles cannot occur (the
    route editor refuses them), but the walk is written to terminate anyway —
    this runs on a public endpoint and must not be a way to hang a worker.
    """
    from ..db.tables import Route as RouteRow, Station as StationRow

    stations = (await session.execute(
        select(StationRow).where(StationRow.companyId == company_id)
    )).scalars().all()
    names = {s.id: s.name for s in stations}
    # Integration nodes are not steps. A link into Shopify or out to ShipStation
    # is a boundary, not a place work happens: including them would show a
    # customer "Shopify" as an operation and count it in the denominator, so a
    # four-step line would report 50% when it was three quarters done. They also
    # never hold units, so they would sit permanently empty.
    partners = {s.id for s in stations if s.integrationProvider}

    routes = [r for r in (await session.execute(
        select(RouteRow).where(RouteRow.companyId == company_id,
                               RouteRow.processId == process_id)
    )).scalars().all() if r.load not in partners and r.unload not in partners]
    if not routes:
        return []

    nodes = {r.load for r in routes} | {r.unload for r in routes}
    incoming = {n: 0 for n in nodes}
    out: dict = {n: [] for n in nodes}
    for r in routes:
        incoming[r.unload] += 1
        out[r.load].append(r.unload)

    queue = sorted([n for n, c in incoming.items() if c == 0], key=str)
    order: list = []
    guard = len(nodes) + len(routes) + 1
    while queue and guard > 0:
        guard -= 1
        node = queue.pop(0)
        order.append(node)
        for nxt in out.get(node, []):
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
    for n in nodes:                     # anything a cycle stranded, appended
        if n not in order:
            order.append(n)

    return [(n, names.get(n, "—")) for n in order]


async def resolve(session: AsyncSession, order_id, token: str) -> Optional[Tracked]:
    """The public view of one order, or None if it may not be shown.

    None covers every refusal — unknown order, wrong token, tracking switched
    off — deliberately, so the caller can only ever answer 404 and the page
    cannot be used to test whether an order exists.
    """
    from ..db.tables import Card as CardRow, LotTemplate, ProductionOrder

    order = await session.get(ProductionOrder, order_id)
    if order is None or not verify(order.id, token):
        return None

    on, show_steps = await enabled_for(session, order.companyId)
    if not on:
        return None

    template = (await session.get(LotTemplate, order.productTemplateId)
                if order.productTemplateId else None)

    cards = (await session.execute(
        select(CardRow).where(CardRow.companyId == order.companyId,
                              CardRow.orderId == order.id)
    )).scalars().all()

    steps: Optional[list] = None
    step_index = step_total = None
    process_id = template.processId if template is not None else None
    if process_id is not None:
        ordered = await _ordered_stations(session, order.companyId, process_id)
        step_total = len(ordered) or None
        if ordered:
            units_at: dict = {}
            for c in cards:
                for sid, b in (c.bins or {}).items():
                    units_at[sid] = units_at.get(sid, 0) + int(b.get("count", 0) or 0)
            furthest = -1
            for i, (sid, _name) in enumerate(ordered):
                if units_at.get(str(sid), 0) > 0:
                    furthest = i
            step_index = furthest if furthest >= 0 else None
            if show_steps:
                steps = [
                    Step(name=name,
                         units=units_at.get(str(sid), 0),
                         done=step_index is not None and i < step_index,
                         current=(i == step_index))
                    for i, (sid, name) in enumerate(ordered)
                ]

    return Tracked(
        reference=(order.externalRef or str(order.id)[:8]),
        product=(template.name if template is not None else "Order"),
        quantity=order.quantity,
        quantity_done=order.quantityDone,
        status=order.status,
        steps=steps,
        step_index=step_index,
        step_total=step_total,
        updated_at=getattr(order, "updatedAt", None) or order.createdAt,
        show_steps=show_steps,
    )
