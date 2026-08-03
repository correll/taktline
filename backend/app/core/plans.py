"""The price, as data.

One module owns what an account may do — how many stations, whether it can
talk to an ERP, what it costs. Everything else (the gate, the quotas, the
billing endpoints, the marketing page, the staff dashboard) reads from here,
so a price change is one edit rather than a hunt.

The model (pricing.md is the argument; this file is the arithmetic):

**One paid plan, metered by station.** $2 per station per month, with a $29
floor and a $399 ceiling. Linear on purpose: a banded price makes customers
model 10 stations instead of their actual 14 to stay under a threshold, and
everything of value here — merge/split detection, the accumulation warning,
every Line Doctor finding — rests on the graph being a faithful map of the
floor. A pricing metric that rewards under-modelling is hostile to the product
working. The ceiling is a deliberate refusal of the enterprise upside, bought
in exchange for never having a deal large enough to need a salesperson; the
floor is the smallest number at which an account covers its own cost to serve.

**A free tier, not a trial.** Up to 3 stations, no card, no expiry — and free
accounts are never deleted. Someone who drew a three-station cell and came
back six months later should find it waiting.

**Connectors are included. Operators are free.** Charging monthly for a
connector taxes integration depth, and integration depth is the strongest
predictor of a floor worth talking to about automation. Charging per operator
is the competitor anti-pattern this product is positioned against. Neither is
metered, anywhere, and there is deliberately no code with which to meter them.

Two rules this file exists to enforce:

**A plan code is permanent.** It is stored on every `subscriptions` row.
Codes may be added and aliased; never renamed. The retired banded codes are
aliased below so a row written before this model resolves to something sane.

**Prices live in cents, as integers.** Money in floats is how a $116.00
charge becomes $115.99999999999999.
"""

from __future__ import annotations

from dataclasses import dataclass

# ─── The numbers ─────────────────────────────────────────────────────────────

#: The free tier's station cap. If people park pilots there indefinitely the
#: answer is to raise it, never to lower it (pricing.md, open questions).
FREE_STATIONS = 3

PER_STATION_CENTS = 200      # $2 / station / month
MIN_CENTS = 2_900            # the floor — bites below 15 stations
CAP_CENTS = 39_900           # the ceiling — bites at 200 stations

#: Derived, for display and for building the Stripe tiers. The floor covers
#: 1–14 stations (14 × $2 = $28 < $29); station 15 is the first metered one.
#: 199 × $2 = $398 is the last metered count; 200 up is the flat cap.
MIN_STATIONS = MIN_CENTS // PER_STATION_CENTS + 1        # 15
CAP_STATIONS = CAP_CENTS // PER_STATION_CENTS + 1        # 200

GRACE_DAYS = 7   # read-only window after a failed payment, before pausing


def monthly_cents_for(stations: int) -> int:
    """What a paid account with this many stations pays per month.

    The clamp IS the price list: min($29) below 15 stations, $2 × n between,
    max($399) from 200 up. `station_tiers()` below must describe the same
    function to Stripe — `tests/test_billing.py` holds the two together.
    """
    return min(max(stations * PER_STATION_CENTS, MIN_CENTS), CAP_CENTS)


def station_tiers() -> list[dict]:
    """The same price, in Stripe's vocabulary: volume tiers on one price.

    Volume mode (the tier containing the total applies to ALL units), not
    graduated — graduated would charge the floor *plus* $2 for station 15,
    and the promise is "between the floor and the cap it is just $2 a
    station". The cap is a flat final tier, so Stripe enforces it rather
    than us. Cents, like everything else in this file.
    """
    return [
        {"up_to": MIN_STATIONS - 1, "flat_amount": MIN_CENTS},
        {"up_to": CAP_STATIONS - 1, "unit_amount": PER_STATION_CENTS},
        {"up_to": "inf", "flat_amount": CAP_CENTS},
    ]


# The on-premise add-on: the same product, running on the customer's own
# hardware, enforced by a signed licence file rather than by this database.
# An add-on rather than a tier because it is orthogonal — any size can be
# on-premise.
ONPREM_CENTS = 19_900
ONPREM_PRICE_ENV = "STRIPE_PRICE_ONPREM"

#: The metered station price (a single Stripe price with `station_tiers()`).
STATION_PRICE_ENV = "STRIPE_PRICE_TAKTLINE"


# ─── The plans ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Plan:
    code: str
    label: str
    #: Station cap. **None means uncapped** — the paid plan is metered, not
    #: capped, and a large sentinel would show up in the UI as
    #: "3 of 100000 stations".
    stations: int | None
    integrations: bool
    blurb: str


FREE = "free"
PAID = "taktline"
SANDBOX = "sandbox"

#: Not for sale. Handed out where we do not meter: a customer's own hardware
#: (their licence file governs) and any deployment with no payment provider
#: configured, which is what self-hosting and the test suite are.
SELF_HOSTED = "self_hosted"

PLANS: dict[str, Plan] = {
    SELF_HOSTED: Plan(
        code=SELF_HOSTED, label="Self-hosted", stations=None, integrations=True,
        blurb="Running on your own hardware. Not metered by us.",
    ),
    SANDBOX: Plan(
        code=SANDBOX, label="Sandbox", stations=40, integrations=False,
        blurb="A throwaway line to try the product. Expires after 7 days.",
    ),
    FREE: Plan(
        code=FREE, label="Free", stations=FREE_STATIONS, integrations=False,
        blurb=f"Up to {FREE_STATIONS} stations. No card, no expiry — your line "
              f"is kept for whenever you come back.",
    ),
    PAID: Plan(
        code=PAID, label="Taktline", stations=None, integrations=True,
        blurb="Unlimited stations at $2 each per month — never less than $29, "
              "never more than $399. Every connector included. Operators are "
              "free, always.",
    ),
}

#: Codes that no longer exist, mapped to what they now mean. A subscription
#: row written under the banded model resolves here rather than crashing the
#: gate; the trial maps to free because that is what replaced it.
_LEGACY = {
    "trial": FREE,
    "basic_50": PAID, "pro_50": PAID, "pro_100": PAID, "plant_250": PAID,
    "enterprise": PAID,
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
