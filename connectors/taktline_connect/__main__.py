"""Run a connector:  python -m taktline_connect <odoo|netsuite|shopify|woocommerce|generic>

Config comes entirely from the environment (see .env.example). The ERP client is
lazy-imported so each connector only pulls in the deps it actually needs.
"""
from __future__ import annotations

import logging
import sys
import time

from .config import load

CONNECTORS = ("odoo", "netsuite", "shopify", "woocommerce",
              "quickbooks", "xero", "shipstation", "generic")
ALIASES = {"qbo": "quickbooks", "woo": "woocommerce"}   # the module names, as documented
USAGE = f"usage: python -m taktline_connect <{'|'.join(CONNECTORS)}>"


def _builder(erp: str):
    if erp == "odoo":
        from .odoo import build
    elif erp == "netsuite":
        from .netsuite import build
    elif erp == "shopify":
        from .shopify import build
    elif erp == "woocommerce":
        from .woocommerce import build
    elif erp == "quickbooks":
        from .qbo import build
    elif erp == "xero":
        from .xero import build
    elif erp == "shipstation":
        from .shipstation import build
    elif erp == "generic":
        from .generic import build
    else:
        print(USAGE, file=sys.stderr)
        raise SystemExit(2)
    return build


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("taktline_connect")
    if len(sys.argv) < 2:
        print(USAGE, file=sys.stderr)
        raise SystemExit(2)
    erp = ALIASES.get(sys.argv[1], sys.argv[1])
    cfg = load()
    connector = _builder(erp)(cfg)
    log.info("%s connector started · poll=%ss · %d product(s) mapped",
             erp, cfg.poll_interval, len(cfg.product_mapping))
    while True:
        try:
            connector.run_once()
        except Exception as e:  # noqa: BLE001 — never let one bad cycle kill the loop
            log.exception("cycle error: %s", e)
        time.sleep(cfg.poll_interval)


if __name__ == "__main__":
    main()
