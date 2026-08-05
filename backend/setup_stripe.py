"""Create the two Stripe prices Taktline sells, idempotently.

    STRIPE_SECRET_KEY=sk_... .venv/bin/python setup_stripe.py

Prints the STRIPE_PRICE_* lines to paste into .env / render.yaml. Run once per
mode — the sandbox/test key and the live key are different accounts with
different price ids, which is why the ids live in env vars and not in code.

Two prices, that is all:

**The station price** (`taktline_station`) is a single tiered price carrying
the whole model — $2 per station with the $29 floor and the $399 cap expressed
as volume tiers, so Stripe does the clamp and an invoice can never disagree
with pricing.md. The subscription's *quantity* is the station count, reported
by the app whenever the floor changes (`entitlements.report_station_count`).

**The on-premise add-on** is a flat monthly line on the same subscription.

Idempotent by **lookup key**: a re-run finds the existing price and prints its
id rather than minting a sibling. Prices are immutable in Stripe, so if the
tiers or amount found disagree with `plans.py` the script says so and exits
nonzero — changing the price is a deliberate operation (create the new price,
move the lookup key, keep billing existing subscribers the old one), not
something a bootstrap should do on its own.

Tax: both prices are `txcd_10103001` (SaaS, business use) with
`tax_behavior=exclusive` — with automatic tax on, a price with no tax
behavior fails at checkout. The on-premise add-on is sold as the *service* of
running the software (licence + updates), so it keeps the SaaS code; the Box
hardware is invoiced separately and is NOT set up here.
"""

from __future__ import annotations

import os
import sys

from app.core import plans

SAAS_TAX_CODE = "txcd_10103001"     # business use — NOT ..000, which is personal

STATION_LOOKUP = "taktline_station"
ONPREM_LOOKUP = "taktline_onprem"


def _tiers_match(price, want: list[dict]) -> bool:
    # Attribute access, not .get(): StripeObject stopped being a dict subclass
    # in stripe v15, and this branch only runs when the lookup key already
    # exists — an account state the sandbox bootstrap never had.
    got = getattr(price, "tiers", None) or []
    if len(got) != len(want):
        return False
    for g, w in zip(got, want):
        up_to = getattr(g, "up_to", None)            # None = the inf tier
        if (w["up_to"] == "inf") != (up_to is None):
            return False
        if w["up_to"] != "inf" and up_to != w["up_to"]:
            return False
        if getattr(g, "flat_amount", None) != w.get("flat_amount"):
            return False
        if getattr(g, "unit_amount", None) != w.get("unit_amount"):
            return False
    return True


def ensure_station_price(stripe) -> tuple[str, bool]:
    want = plans.station_tiers()
    found = stripe.Price.list(lookup_keys=[STATION_LOOKUP], limit=1,
                              expand=["data.tiers"])["data"]
    if found:
        price = found[0]
        if not _tiers_match(price, want):
            print(f"  !! {STATION_LOOKUP}: exists with different tiers than "
                  f"plans.py — create the new price and move the lookup key "
                  f"by hand, this script will not.")
            return price["id"], False
        print(f"  ok {STATION_LOOKUP}: {price['id']} (existing)")
        return price["id"], True
    price = stripe.Price.create(
        lookup_key=STATION_LOOKUP,
        currency="usd",
        recurring={"interval": "month"},
        billing_scheme="tiered",
        tiers_mode="volume",         # the tier containing the total applies to
        tiers=want,                  # ALL units — the clamp, not a staircase
        tax_behavior="exclusive",
        product_data={"name": "Taktline — per station",
                      "tax_code": SAAS_TAX_CODE,
                      "metadata": {"taktline": "station"}},
        metadata={"taktline": "station"},
    )
    print(f"  ok {STATION_LOOKUP}: {price['id']} (created)")
    return price["id"], True


def ensure_onprem_price(stripe) -> tuple[str, bool]:
    found = stripe.Price.list(lookup_keys=[ONPREM_LOOKUP], limit=1)["data"]
    if found:
        price = found[0]
        if price["unit_amount"] != plans.ONPREM_CENTS:
            print(f"  !! {ONPREM_LOOKUP}: exists at {price['unit_amount']}¢, "
                  f"plans.py says {plans.ONPREM_CENTS}¢ — resolve by hand.")
            return price["id"], False
        print(f"  ok {ONPREM_LOOKUP}: {price['id']} (existing)")
        return price["id"], True
    price = stripe.Price.create(
        lookup_key=ONPREM_LOOKUP,
        currency="usd",
        unit_amount=plans.ONPREM_CENTS,
        recurring={"interval": "month"},
        tax_behavior="exclusive",
        product_data={"name": "Taktline on-premise add-on",
                      "tax_code": SAAS_TAX_CODE,
                      "metadata": {"taktline": "onprem"}},
        metadata={"taktline": "onprem"},
    )
    print(f"  ok {ONPREM_LOOKUP}: {price['id']} (created)")
    return price["id"], True


def main() -> int:
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        print("Set STRIPE_SECRET_KEY (the sandbox/test key for a dry run, "
              "the live key for production).")
        return 1
    import stripe

    stripe.api_key = key
    mode = "LIVE" if key.startswith(("sk_live", "rk_live")) else "test/sandbox"
    print(f"Creating Taktline prices ({mode} mode)…")

    station_id, ok1 = ensure_station_price(stripe)
    onprem_id, ok2 = ensure_onprem_price(stripe)

    print("\nEnvironment:")
    print(f"  {plans.STATION_PRICE_ENV}={station_id}")
    print(f"  {plans.ONPREM_PRICE_ENV}={onprem_id}")

    print("\nStill manual, in the Dashboard:")
    print("  - Tax: origin address + your registrations "
          "(https://dashboard.stripe.com/tax) — no registration, no collection")
    print("  - Payment methods: enable ACH (us_bank_account); card and Link "
          "are on by default")
    print("  - Billing → Revenue recovery: Smart Retries + failed-payment "
          "emails; align the retry end-state with the 7-day grace window")
    print("  - Developers → Webhooks: endpoint /billing/webhook with the "
          "events in billing_stripe.HANDLED → STRIPE_WEBHOOK_SECRET")
    return 0 if ok1 and ok2 else 2


if __name__ == "__main__":
    sys.exit(main())
