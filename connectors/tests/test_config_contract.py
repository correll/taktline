"""The setup instructions shown in the app must name the variables the
connector actually reads.

Taktline's Settings → Integrations panel tells people exactly which values to
fetch from Odoo, Shopify, NetSuite… and which environment variable each one
goes into. That list lives in the frontend
(``frontend/src/domain/integrations.ts``) because the backend never imports
this package — which means nothing stops the two from drifting.

Drift here is worse than a typo: someone follows the instructions, sets
``ODOO_KEY`` because the panel said so, the connector reads ``ODOO_API_KEY``,
finds nothing, and fails with an authentication error that points at Odoo
rather than at us. This test is the tripwire — rename a variable in
``config.py`` and it fails here, naming the file that has to change with it.
"""

import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "taktline_connect" / "config.py"
UI_REGISTRY = (Path(__file__).resolve().parents[2]
               / "frontend" / "src" / "domain" / "integrations.ts")


def _env_names_read_by_the_connector() -> set[str]:
    src = CONFIG.read_text()
    return set(re.findall(r"os\.environ\.get\(\s*[\"']([A-Z0-9_]+)[\"']", src))


def _env_names_promised_by_the_ui() -> set[str]:
    if not UI_REGISTRY.exists():          # connectors ship standalone
        return set()
    return set(re.findall(r"env:\s*'([A-Z0-9_]+)'", UI_REGISTRY.read_text()))


def test_every_variable_the_ui_promises_is_actually_read():
    promised = _env_names_promised_by_the_ui()
    if not promised:
        return                            # frontend not present in this checkout
    read = _env_names_read_by_the_connector()
    missing = sorted(promised - read)
    assert not missing, (
        f"Settings → Integrations tells people to set {missing}, but config.py "
        f"never reads them. Fix frontend/src/domain/integrations.ts or config.py."
    )


def test_every_per_provider_variable_is_documented():
    """The reverse direction, limited to provider settings: a new ERP field
    that nobody is told to set is a support ticket waiting to happen.

    Shared plumbing (TAKTLINE_URL, POLL_INTERVAL…) is deliberately excluded —
    it belongs to the connector's own deployment, not to the partner account.
    """
    shared = {"TAKTLINE_URL", "TAKTLINE_API_KEY", "PRODUCT_MAPPING",
              "POLL_INTERVAL", "ORDER_STATES", "CANCEL_LOOKBACK_DAYS",
              "ODOO_PASSWORD"}          # legacy alias; the UI documents ODOO_API_KEY
    read = _env_names_read_by_the_connector() - shared
    promised = _env_names_promised_by_the_ui()
    if not promised:
        return
    undocumented = sorted(read - promised)
    assert not undocumented, (
        f"config.py reads {undocumented} but nothing in the app tells anyone to "
        f"set them — add them to frontend/src/domain/integrations.ts."
    )
