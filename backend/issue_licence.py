#!/usr/bin/env python
"""Issue an on-premise licence. Run on the release machine, never on a server.

    # once, ever — keep the private key offline
    python issue_licence.py keygen

    # per customer, per month
    python issue_licence.py sign --key "$TAKTLINE_LICENCE_PRIVATE_KEY" \
        --to "Bramble Metalworks" --plan plant_250 --days 35 > bramble.json

The customer pastes the file into Settings → Billing, or it is dropped beside
the server as `taktline-licence.json`. It outlives its billing month on purpose:
a licence lapse must never be how a factory finds out its internet is down.
"""

import argparse
import json
import sys

sys.path.insert(0, ".")
from app.core import licence, plans   # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="print a fresh keypair")

    sign = sub.add_parser("sign", help="issue a licence")
    sign.add_argument("--key", required=True, help="base64 private key")
    sign.add_argument("--to", required=True, help="customer name")
    sign.add_argument("--plan", default="plant_250",
                      choices=sorted(plans.PLANS), help="plan code")
    sign.add_argument("--days", type=int, default=licence.DEFAULT_DAYS)
    sign.add_argument("--stations", type=int, default=None,
                     help="override the plan's station cap")
    sign.add_argument("--connectors", type=int, default=None)
    sign.add_argument("--note", default="")

    args = ap.parse_args()
    if args.cmd == "keygen":
        private, public = licence.generate_keypair()
        print(f"TAKTLINE_LICENCE_PRIVATE_KEY={private}   # keep this offline")
        print(f"LICENCE_PUBLIC_KEY={public}              # bake into the image")
        return

    doc = licence.issue(args.key, issued_to=args.to, plan_code=args.plan,
                        stations=args.stations, connectors=args.connectors,
                        days=args.days, note=args.note)
    print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    main()
