"""The price list, as data.

One module owns what a plan *is* — how many stations it allows, whether it can
talk to an ERP, what it costs, and which Stripe Price sells it. Everything else
(the gate, the quotas, the billing endpoints, the marketing page, the staff
dashboard) reads from here, so a price change is one edit rather than a hunt.

Two rules this file exists to enforce:

**A plan code is permanent.** It is stored on every `subscriptions` row and
mapped to a Stripe Price that customers are actively billed against. Renaming
`pro_100` later would orphan live subscriptions. Add codes; never rename them.

**Prices live in cents, as integers.** Money in floats is how a $116.00 charge
becomes $115.99999999999999.
"""

from __future__ import annotations

from dataclasses import dataclass

# ─── The station bands ───────────────────────────────────────────────────────
#
# Bands, not per-unit metering — see pricing.md. The step sizes matter more than
# the absolute numbers: a large jump at a low station count makes customers
# *model fewer stations than they have*, merging the inspection bench into
# assembly to stay under a threshold. That breaks merge/split detection, the
# accumulation warning and every topology finding the line doctor makes. A
# pricing metric that rewards under-modelling is hostile to the product working.

TRIAL_DAYS = 14

# How long a lapsed account stays readable before it is locked. They can still
# see and export everything during this window — the product's promise is that
# your data is yours, and a paywall in front of your own history would break it.
GRACE_DAYS = 7


@dataclass(frozen=True)
class Plan:
    code: str
    label: str
    #: Station cap. **None means uncapped** — used by the self-hosted and
    #: on-premise plans, where we are not the ones metering. A large sentinel
    #: number would have worked for the comparison and then shown up in the UI
    #: as "3 of 100000 stations".
    stations: int | None
    integrations: bool
    monthly_cents: int
    #  Env var holding the Stripe Price id. Not the id itself: test mode and
    #  live mode have different ids, and a checked-in live price id is the kind
    #  of mistake that bills real customers from a staging box.
    price_env: str | None
    #  Shown on the pricing page and the in-app selector.
    blurb: str


TRIAL = "trial"
SANDBOX = "sandbox"

#: Not for sale. Handed out where we do not meter: a customer's own hardware
#: (their licence file governs) and any deployment with no payment provider
#: configured, which is what self-hosting and the test suite are.
SELF_HOSTED = "self_hosted"

PLANS: dict[str, Plan] = {
    SELF_HOSTED: Plan(
        code=SELF_HOSTED, label="Self-hosted", stations=None, integrations=True,
        monthly_cents=0, price_env=None,
        blurb="Running on your own hardware. Not metered by us.",
    ),
    SANDBOX: Plan(
        code=SANDBOX, label="Sandbox", stations=40, integrations=False,
        monthly_cents=0, price_env=None,
        blurb="A throwaway line to try the product. Expires after 7 days.",
    ),
    TRIAL: Plan(
        code=TRIAL, label="Trial", stations=50, integrations=False,
        monthly_cents=0, price_env=None,
        blurb=f"The whole product for {TRIAL_DAYS} days. No card needed.",
    ),
    "basic_50": Plan(
        code="basic_50", label="Basic", stations=50, integrations=False,
        monthly_cents=2900, price_env="STRIPE_PRICE_BASIC_50",
        blurb="Your whole floor on one board — up to 50 stations, "
              "unlimited operators.",
    ),
    "pro_50": Plan(
        code="pro_50", label="Professional", stations=50, integrations=True,
        monthly_cents=5800, price_env="STRIPE_PRICE_PRO_50",
        blurb="Basic plus ERP and shop-system integrations — up to 50 stations.",
    ),
    "pro_100": Plan(
        code="pro_100", label="Professional 100", stations=100, integrations=True,
        monthly_cents=11600, price_env="STRIPE_PRICE_PRO_100",
        blurb="Professional for a larger floor — up to 100 stations.",
    ),
}

# The on-premise add-on: the same plan, running on the customer's own hardware.
# Priced as an add-on rather than a separate tier because it is orthogonal —
# any band can be on-premise.
ONPREM_CENTS = 19900
ONPREM_PRICE_ENV = "STRIPE_PRICE_ONPREM"

#: Plans a customer can actually buy, in the order they are shown.
PURCHASABLE = ["basic_50", "pro_50", "pro_100"]

#: Plans that are granted, not bought. Never gated, never billed, never dunned.
FREE = {SANDBOX, TRIAL}


def get(code: str | None) -> Plan:
    """The plan for a code, falling back to trial.

    A company with no subscription row (a pre-existing account mid-migration, a
    row lost to a bad deploy) must not be handed the most expensive plan by
    accident, nor be bricked. Trial is the safe middle: usable, limited, and
    visibly temporary, so the situation gets noticed and fixed.
    """
    return PLANS.get(code or "", PLANS[TRIAL])


def is_upgrade(from_code: str, to_code: str) -> bool:
    """Is this a move up the price list?

    Stripe needs the answer to decide proration: an upgrade is invoiced
    immediately, a downgrade credits forward. Comparing price rather than
    station count is deliberate — pro_50 costs more than basic_50 while allowing
    the same 50 stations, and it is unambiguously an upgrade.
    """
    return get(to_code).monthly_cents > get(from_code).monthly_cents


def monthly_cents(code: str, on_premise: bool = False) -> int:
    return get(code).monthly_cents + (ONPREM_CENTS if on_premise else 0)


def price_ids() -> dict[str, str | None]:
    """Plan code → configured Stripe Price id (None when unset).

    Read through `core.config.settings` rather than os.environ so a test can
    override it the same way it overrides everything else.
    """
    from .config import settings

    out: dict[str, str | None] = {}
    for code in PURCHASABLE:
        env = PLANS[code].price_env
        out[code] = getattr(settings, env.lower(), None) if env else None
    out["onprem"] = getattr(settings, ONPREM_PRICE_ENV.lower(), None)
    return out
