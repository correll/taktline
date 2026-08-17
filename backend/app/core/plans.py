"""The price, as data.

One module owns what an account may do — how many stations, whether it can
talk to an ERP, whether it gets the Line Doctor, what it costs. Everything else
(the gate, the quotas, the billing endpoints, the marketing page, the staff
dashboard) reads from here, so a price change is one edit rather than a hunt.

The model (pricing.md is the argument; this file is the arithmetic):

**Four tiers, two of them published.** Free and Shop carry a number on the
pricing page and are bought without talking to anyone. Plant and Enterprise
carry no number at all — they are a conversation, and the page says so. That
split is the whole design: the bottom stays frictionless so a small shop
installs a line on a whim and tells people, and the top stays open so a
200-station plant is not silently sold a $399 subscription because a ceiling
was written into the product three years earlier.

**Free is ≤7 stations.** No card, no expiry, never deleted — someone who drew a
six-station cell and came back six months later should find it waiting. This is
the tier the growth loop runs on and it should be raised, never lowered, if
people park on it.

**Shop is 8–30 stations, and it is a base plus a step.** $200 a month covers
the first 8; every station after that is $45. That is a rising *effective*
rate — $25 a station at 8, about $40 at 30 — which is deliberate: a small shop
sees a number it can expense, and a shop with thirty stations is running most
of a plant on this and pays accordingly. Above 30 stations the answer is not a
bigger number, it is a phone call, so Shop is **capped** at 30 and the cap
refusal points at sales.

**Plant and Enterprise are capacity, not price.** They exist here so an
entitlement resolves and a limit is enforced; what they cost is agreed with a
person and set on the subscription by staff. No self-serve checkout reaches
them.

**Connectors are included on every paid tier. Operators are free, always.**
Charging monthly for a connector taxes integration depth, and integration depth
is the strongest predictor of a floor worth talking to about automation.
Charging per operator is the competitor anti-pattern this product is positioned
against. Neither is metered, anywhere, and there is deliberately no code with
which to meter them.

Three rules this file exists to enforce:

**A plan code is permanent.** It is stored on every `subscriptions` row. Codes
may be added and aliased; never renamed. The retired codes are aliased below so
a row written under an older model resolves to something sane.

**Prices live in cents, as integers.** Money in floats is how a $116.00 charge
becomes $115.99999999999999.

**A capability is a field on Plan, not an `if` somewhere.** `integrations` and
`line_doctor` are booleans here and are read by `entitlements.ensure_*`. A gate
written any other way is a gate the pricing page will eventually contradict.
"""

from __future__ import annotations

from dataclasses import dataclass

# ─── The numbers ─────────────────────────────────────────────────────────────

#: The free tier's station cap. If people park pilots there indefinitely the
#: answer is to raise it, never to lower it (pricing.md, open questions).
FREE_STATIONS = 7

#: Shop: 8–30 stations. A base that covers the first `SHOP_BASE_STATIONS`, then
#: a flat step per station up to the cap.
SHOP_BASE_CENTS = 20_000        # $200 / month, covers the first 8 stations
SHOP_BASE_STATIONS = 8
SHOP_PER_STATION_CENTS = 4_500  # $45 for each station above the base
SHOP_STATIONS = 30              # the cap — past this it is a conversation

#: Sales-assisted capacity. No price here on purpose: what these cost is agreed
#: with a person, and a number in this file would leak onto the pricing page.
PLANT_STATIONS = 100
#: Enterprise is uncapped (None), like self-hosted.

GRACE_DAYS = 7   # read-only window after a failed payment, before pausing


def monthly_cents_for(stations: int) -> int:
    """What a Shop account with this many stations pays per month.

    Base plus step: $200 covers the first 8, then $45 each. Below the base the
    base still applies — "$200 covers up to 8 stations" is the promise, not
    "$200 is what 8 stations cost". Above the cap the number stops meaning
    anything, because a line that size cannot be on Shop (`SHOP_STATIONS`), so
    it clamps rather than inventing a price nobody can buy.

    `station_tiers()` below must describe the same function to Stripe —
    `tests/test_billing.py` holds the two together.
    """
    billable = min(max(stations, SHOP_BASE_STATIONS), SHOP_STATIONS)
    return SHOP_BASE_CENTS + (billable - SHOP_BASE_STATIONS) * SHOP_PER_STATION_CENTS


def station_tiers() -> list[dict]:
    """The same price, in Stripe's vocabulary: **graduated** tiers.

    Graduated, not volume — the opposite of the old flat-rate model. Under
    graduated, the first 8 units are charged the flat base and only units 9 and
    up take the per-station rate, which is exactly "a base plus a step". Volume
    mode would apply one rate to every unit and make station 9 re-price the
    first eight.

    The final tier is unreachable in practice: the app caps a Shop line at
    `SHOP_STATIONS`, so Stripe is never asked to price a 31st station. It exists
    because Stripe requires the last tier to be open-ended, and it continues the
    step rather than being free — an unreachable tier that bills $0 is how an
    unnoticed cap bug becomes an unnoticed revenue bug.
    """
    return [
        {"up_to": SHOP_BASE_STATIONS, "flat_amount": SHOP_BASE_CENTS},
        {"up_to": SHOP_STATIONS, "unit_amount": SHOP_PER_STATION_CENTS},
        {"up_to": "inf", "unit_amount": SHOP_PER_STATION_CENTS},
    ]


# The on-premise add-on: the same product, running on the customer's own
# hardware, enforced by a signed licence file rather than by this database. An
# add-on rather than a tier because it is orthogonal — any size can be
# on-premise — and it is **no longer advertised with a price**: it is listed
# under Enterprise, where the conversation happens. The mechanism stays, because
# accounts that have it need it to keep working and issued licences depend on it.
ONPREM_CENTS = 19_900
ONPREM_PRICE_ENV = "STRIPE_PRICE_ONPREM"

#: The Shop station price (a single Stripe price carrying `station_tiers()`).
STATION_PRICE_ENV = "STRIPE_PRICE_TAKTLINE"


# ─── The plans ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Plan:
    code: str
    label: str
    #: Station cap. **None means uncapped** — a large sentinel would show up in
    #: the UI as "3 of 100000 stations".
    stations: int | None
    integrations: bool
    #: The Line Doctor (`GET /analysis/`). The report, not the runout clock the
    #: operator's lot picker reads — that is queue ordering and stays open on
    #: every tier, because gating it would break the operator view rather than
    #: withhold a feature.
    line_doctor: bool
    #: Can this tier be bought without talking to anyone? False means the
    #: pricing page shows "talk to us" and no checkout reaches it.
    self_serve: bool
    blurb: str


FREE = "free"
SHOP = "shop"
PLANT = "plant"
ENTERPRISE = "enterprise"
SANDBOX = "sandbox"

#: The self-serve paid plan. Kept as a name because a lot of code and several
#: tests ask "is this the plan a checkout produces"; it is Shop now.
PAID = SHOP

#: Not for sale. Handed out where we do not meter: a customer's own hardware
#: (their licence file governs) and any deployment with no payment provider
#: configured, which is what self-hosting and the test suite are.
SELF_HOSTED = "self_hosted"

PLANS: dict[str, Plan] = {
    SELF_HOSTED: Plan(
        code=SELF_HOSTED, label="Self-hosted", stations=None, integrations=True,
        line_doctor=True, self_serve=False,
        blurb="Running on your own hardware. Not metered by us.",
    ),
    SANDBOX: Plan(
        code=SANDBOX, label="Sandbox", stations=40, integrations=False,
        line_doctor=False, self_serve=False,
        blurb="A throwaway line to try the product. Expires after 7 days.",
    ),
    FREE: Plan(
        code=FREE, label="Free", stations=FREE_STATIONS, integrations=False,
        line_doctor=False, self_serve=True,
        blurb=f"Up to {FREE_STATIONS} stations. No card, no expiry — your line "
              f"is kept for whenever you come back.",
    ),
    SHOP: Plan(
        code=SHOP, label="Shop", stations=SHOP_STATIONS, integrations=True,
        line_doctor=True, self_serve=True,
        blurb=f"{SHOP_BASE_STATIONS}–{SHOP_STATIONS} stations. $200 a month "
              f"covers the first {SHOP_BASE_STATIONS}, then $45 each. Every "
              f"connector, the Line Doctor, and email support.",
    ),
    # Plant and Enterprise differ from Shop in **capacity and service**, not in
    # features — deliberately. Everything a blurb claims here is either a
    # station count this file enforces or a commitment a person can honour on
    # the day it is asked for. Nothing that has to be built first.
    PLANT: Plan(
        code=PLANT, label="Plant", stations=PLANT_STATIONS, integrations=True,
        line_doctor=True, self_serve=False,
        blurb=f"Up to {PLANT_STATIONS} stations, priced with you. Priority "
              f"support with a response-time SLA.",
    ),
    ENTERPRISE: Plan(
        code=ENTERPRISE, label="Enterprise", stations=None, integrations=True,
        line_doctor=True, self_serve=False,
        blurb="Beyond 100 stations, priced with you. On-premise, a named "
              "contact and compliance support.",
    ),
}

#: Codes that no longer exist, mapped to what they now mean. A subscription row
#: written under an older model resolves here rather than crashing the gate.
#:
#: `taktline` was the single metered plan that Shop replaces, and the retired
#: bands before it are mapped by the capacity they sold rather than all funnelled
#: to one tier — `pro_100` bought a hundred stations and should not resolve to a
#: plan that caps at thirty.
_LEGACY = {
    "trial": FREE,
    "taktline": SHOP,
    "basic_50": SHOP, "pro_50": PLANT, "pro_100": PLANT, "plant_250": ENTERPRISE,
}


def get(code: str | None) -> Plan:
    if code in PLANS:
        return PLANS[code]
    if code in _LEGACY:
        return PLANS[_LEGACY[code]]
    # Unknown code: the least harmful guess. Neither bricks a paying customer
    # nor hands out unlimited stations.
    return PLANS[FREE]


def price_ids() -> dict[str, str | None]:
    """Configured Stripe price ids, straight from settings."""
    from .config import settings

    return {
        "taktline": settings.stripe_price_taktline,
        "onprem": settings.stripe_price_onprem,
    }
