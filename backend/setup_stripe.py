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


#: How the tiers are applied. Not cosmetic: the same numbers under `volume`
#: bill every unit at one rate and under `graduated` bill each unit at its own
#: tier's rate, so a price that matches on amounts alone can still charge the
#: wrong thing. Checked because this repo has switched modes once already.
TIERS_MODE = "graduated"


def _tiers_match(price, want: list[dict]) -> bool:
    # Attribute access, not .get(): StripeObject stopped being a dict subclass
    # in stripe v15, and this branch only runs when the lookup key already
    # exists — an account state the sandbox bootstrap never had.
    if getattr(price, "tiers_mode", None) != TIERS_MODE:
        return False
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


def ensure_station_price(stripe, replace: bool = False) -> tuple[str, bool]:
    """The station price, created if absent.

    A Stripe price is **immutable**: changing what a station costs means a new
    price object, not an edit. When one already exists under our lookup key and
    disagrees with `plans.py`, that is a live price charging something the
    pricing page no longer says — the single most expensive drift in this
    system, and one no test can see because it lives in Stripe.

    So this refuses by default and says exactly how to fix it. `--replace`
    mints the new price and moves the lookup key onto it in one call
    (`transfer_lookup_key`), which is the whole remedy: existing subscriptions
    keep billing on the old price object until they are moved deliberately, and
    every *new* checkout gets the new one.
    """
    want = plans.station_tiers()
    found = stripe.Price.list(lookup_keys=[STATION_LOOKUP], limit=1,
                              expand=["data.tiers"])["data"]
    if found:
        price = found[0]
        if _tiers_match(price, want):
            print(f"  ok {STATION_LOOKUP}: {price['id']} (existing)")
            return price["id"], True
        if not replace:
            print(f"  !! {STATION_LOOKUP}: {price['id']} exists with different "
                  f"tiers or mode than plans.py.")
            print(f"     A Stripe price cannot be edited. Until this is "
                  f"resolved the site advertises one price and checkout "
                  f"charges another.")
            print(f"     Re-run with --replace to create the new price and "
                  f"move the lookup key onto it, then set "
                  f"{plans.STATION_PRICE_ENV} to the id it prints.")
            print(f"     Subscriptions already on {price['id']} keep billing "
                  f"at the old price until you move them on purpose.")
            return price["id"], False
        print(f"  ~~ {STATION_LOOKUP}: {price['id']} disagrees with plans.py — "
              f"creating a replacement and transferring the lookup key")
    price = stripe.Price.create(
        lookup_key=STATION_LOOKUP,
        # Takes the key off whatever held it. Only reachable via --replace, and
        # only after the tiers were found to disagree.
        transfer_lookup_key=bool(found),
        currency="usd",
        recurring={"interval": "month"},
        billing_scheme="tiered",
        # GRADUATED: each tier prices only the units that fall inside it, so the
        # first 8 stations take the flat base and station 9 onward takes the
        # step. Volume mode would apply one rate to every unit, which is the
        # retired flat-rate model — and switching a live price between the two
        # is impossible (Stripe prices are immutable), which is what the
        # mismatch refusal above exists to catch.
        tiers_mode=TIERS_MODE,
        tiers=want,
        tax_behavior="exclusive",
        product_data={"name": "Taktline Shop — per station",
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

    replace = "--replace" in sys.argv
    station_id, ok1 = ensure_station_price(stripe, replace=replace)
    onprem_id, ok2 = ensure_onprem_price(stripe)

    # Only print an env line for a price that is actually right. Printing the
    # id of a price we just refused invites someone to paste it into the
    # deployment, which is how the pricing page and the invoice come to
    # disagree in the first place.
    print("\nEnvironment:")
    print(f"  {plans.STATION_PRICE_ENV}={station_id}" if ok1
          else f"  {plans.STATION_PRICE_ENV}=  ** unresolved — see above, "
               f"do NOT paste the id printed there **")
    print(f"  {plans.ONPREM_PRICE_ENV}={onprem_id}" if ok2
          else f"  {plans.ONPREM_PRICE_ENV}=  ** unresolved — see above **")

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
