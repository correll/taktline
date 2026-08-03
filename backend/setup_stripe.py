"""Create the Stripe products and prices Taktline sells, idempotently.

    STRIPE_SECRET_KEY=sk_... .venv/bin/python setup_stripe.py

Prints the STRIPE_PRICE_* lines to paste into .env / render.yaml. Run once per
mode — the sandbox/test key and the live key are different accounts with
different price ids, which is why the ids live in env vars and not in code.

Idempotent by **lookup key** (`taktline_<code>`): a re-run finds the existing
price and prints its id rather than minting a sibling. A price's amount is
immutable in Stripe, so if the amount here disagrees with the one found, the
script says so and exits nonzero — changing a sell price is a deliberate
operation (create the new price, move the lookup key, keep billing existing
subscribers the old one), not something a bootstrap should do on its own.

Two decisions worth writing down:

**Tax codes are set here, on the product,** because with `automatic_tax` on
they are what Stripe Tax reasons from. The cloud plans and the connector
add-on are `txcd_10103001` (SaaS, business use) — several states exempt
exactly this while taxing downloaded software, so the *specific* code is the
difference between charging a customer tax their state does not owe and not.
The on-premise add-on is `txcd_10202003` (downloadable software, business
use): it runs on the customer's hardware, which is the distinction those same
states draw.

**`tax_behavior` is exclusive** (tax added on top). US B2B convention — and
with automatic tax enabled, a price with no tax behavior fails at checkout,
so it must be said explicitly.
"""

from __future__ import annotations

import os
import sys

from app.core import plans

#: SaaS, business use. NOT txcd_10103000, which is personal use — states tax
#: the two differently.
SAAS_TAX_CODE = "txcd_10103001"
#: Downloadable software, business use — the on-premise build.
ONPREM_TAX_CODE = "txcd_10202003"


def sellables() -> list[dict]:
    items = []
    for plan in plans.PLANS.values():
        if not plan.price_env:
            continue
        items.append({
            "code": plan.code,
            "name": f"Taktline {plan.label} — up to {plan.stations} stations",
            "cents": plan.monthly_cents,
            "env": plan.price_env,
            "tax_code": SAAS_TAX_CODE,
        })
    items.append({
        "code": "onprem",
        "name": "Taktline on-premise add-on",
        "cents": plans.ONPREM_CENTS,
        "env": plans.ONPREM_PRICE_ENV,
        "tax_code": ONPREM_TAX_CODE,
    })
    items.append({
        "code": "connector",
        "name": "Taktline additional connector",
        "cents": plans.CONNECTOR_CENTS,
        "env": plans.CONNECTOR_PRICE_ENV,
        "tax_code": SAAS_TAX_CODE,
    })
    return items


def ensure_price(stripe, item: dict) -> tuple[str, bool]:
    """Return (price id, ok). ok=False means an amount mismatch was found."""
    lookup_key = f"taktline_{item['code']}"
    found = stripe.Price.list(lookup_keys=[lookup_key], limit=1)["data"]
    if found:
        price = found[0]
        if price["unit_amount"] != item["cents"]:
            print(f"  !! {lookup_key}: exists at {price['unit_amount']}¢, "
                  f"code says {item['cents']}¢ — create the new price and "
                  f"move the lookup key by hand, this script will not.")
            return price["id"], False
        print(f"  ok {lookup_key}: {price['id']} (existing)")
        return price["id"], True
    price = stripe.Price.create(
        lookup_key=lookup_key,
        currency="usd",
        unit_amount=item["cents"],
        recurring={"interval": "month"},
        tax_behavior="exclusive",
        product_data={"name": item["name"],
                      "tax_code": item["tax_code"],
                      "metadata": {"taktline": item["code"]}},
        metadata={"taktline": item["code"]},
    )
    print(f"  ok {lookup_key}: {price['id']} (created)")
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
    print(f"Creating Taktline products and prices ({mode} mode)…")

    env_lines, ok = [], True
    for item in sellables():
        price_id, item_ok = ensure_price(stripe, item)
        ok = ok and item_ok
        env_lines.append(f"{item['env']}={price_id}")

    print("\nEnvironment:")
    for line in env_lines:
        print(f"  {line}")

    print("\nStill manual, in the Dashboard:")
    print("  - Tax: origin address + your registrations "
          "(https://dashboard.stripe.com/tax) — no registration, no collection")
    print("  - Payment methods: enable ACH (us_bank_account); card and Link "
          "are on by default")
    print("  - Billing → Revenue recovery: Smart Retries + failed-payment "
          "emails; align the retry end-state with the 7-day grace window")
    print("  - Developers → Webhooks: endpoint /billing/webhook with the "
          "events in billing_stripe.HANDLED → STRIPE_WEBHOOK_SECRET")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
