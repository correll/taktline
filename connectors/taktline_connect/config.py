"""Environment-driven config, shared by every connector. One dataclass holds
Taktline auth + the product map + poll cadence, plus the per-ERP credential
blocks (only the block for the ERP you run needs to be populated)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # --- Taktline (shared) ---
    taktline_url: str
    taktline_api_key: str
    product_mapping: dict = field(default_factory=dict)   # ERP product ref -> template id
    poll_interval: int = 30
    order_states: tuple = ()                               # ERP order states to pull; empty → client default

    # --- Odoo ---
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_username: str = ""
    odoo_password: str = ""

    # --- NetSuite (SuiteTalk REST + token-based auth) ---
    ns_account: str = ""
    ns_consumer_key: str = ""
    ns_consumer_secret: str = ""
    ns_token_id: str = ""
    ns_token_secret: str = ""

    # --- Shopify (Admin REST) ---
    shopify_shop: str = ""            # my-store.myshopify.com
    shopify_token: str = ""           # Admin API access token
    shopify_api_version: str = "2024-01"
    shopify_fulfill: bool = False     # on Taktline completion, fulfil the Shopify order

    # --- WooCommerce (WP REST, wc/v3) ---
    woo_url: str = ""                 # https://store.example.com
    woo_consumer_key: str = ""
    woo_consumer_secret: str = ""

    # --- QuickBooks Online (OAuth2 + refresh token) ---
    qbo_client_id: str = ""
    qbo_client_secret: str = ""
    qbo_refresh_token: str = ""
    qbo_realm_id: str = ""
    qbo_env: str = "production"        # production | sandbox
    qbo_doc: str = "Estimate"         # which sales doc signals "make this"

    # --- Xero (OAuth2 + refresh token) ---
    xero_client_id: str = ""
    xero_client_secret: str = ""
    xero_refresh_token: str = ""
    xero_tenant_id: str = ""

    # --- ShipStation (HTTP Basic: API key + secret) ---
    shipstation_api_key: str = ""
    shipstation_api_secret: str = ""

    # --- Generic REST (poll a JSON orders endpoint) ---
    generic_orders_url: str = ""
    generic_auth_header: str = ""     # e.g. "Bearer xyz" or "Basic ..."
    generic_fields: str = ""          # JSON: {"id","product_ref","qty","state"} field names


def load() -> Config:
    api_key = os.environ.get("TAKTLINE_API_KEY")
    if not api_key:
        raise SystemExit("TAKTLINE_API_KEY is required (create one under Settings → Integrations).")
    return Config(
        taktline_url=os.environ.get("TAKTLINE_URL", "http://localhost:8000"),
        taktline_api_key=api_key,
        product_mapping=json.loads(os.environ.get("PRODUCT_MAPPING", "{}")),
        poll_interval=int(os.environ.get("POLL_INTERVAL", "30")),
        order_states=tuple(s.strip() for s in os.environ.get("ORDER_STATES", "").split(",") if s.strip()),
        odoo_url=os.environ.get("ODOO_URL", ""),
        odoo_db=os.environ.get("ODOO_DB", ""),
        odoo_username=os.environ.get("ODOO_USERNAME", ""),
        odoo_password=os.environ.get("ODOO_PASSWORD") or os.environ.get("ODOO_API_KEY", ""),
        ns_account=os.environ.get("NETSUITE_ACCOUNT", ""),
        ns_consumer_key=os.environ.get("NETSUITE_CONSUMER_KEY", ""),
        ns_consumer_secret=os.environ.get("NETSUITE_CONSUMER_SECRET", ""),
        ns_token_id=os.environ.get("NETSUITE_TOKEN_ID", ""),
        ns_token_secret=os.environ.get("NETSUITE_TOKEN_SECRET", ""),
        shopify_shop=os.environ.get("SHOPIFY_SHOP", ""),
        shopify_token=os.environ.get("SHOPIFY_TOKEN", ""),
        shopify_api_version=os.environ.get("SHOPIFY_API_VERSION", "2024-01"),
        shopify_fulfill=os.environ.get("SHOPIFY_FULFILL_ON_COMPLETE", "").lower() in ("1", "true", "yes"),
        woo_url=os.environ.get("WOO_URL", ""),
        woo_consumer_key=os.environ.get("WOO_CONSUMER_KEY", ""),
        woo_consumer_secret=os.environ.get("WOO_CONSUMER_SECRET", ""),
        qbo_client_id=os.environ.get("QBO_CLIENT_ID", ""),
        qbo_client_secret=os.environ.get("QBO_CLIENT_SECRET", ""),
        qbo_refresh_token=os.environ.get("QBO_REFRESH_TOKEN", ""),
        qbo_realm_id=os.environ.get("QBO_REALM_ID", ""),
        qbo_env=os.environ.get("QBO_ENV", "production"),
        qbo_doc=os.environ.get("QBO_DOC", "Estimate"),
        xero_client_id=os.environ.get("XERO_CLIENT_ID", ""),
        xero_client_secret=os.environ.get("XERO_CLIENT_SECRET", ""),
        xero_refresh_token=os.environ.get("XERO_REFRESH_TOKEN", ""),
        xero_tenant_id=os.environ.get("XERO_TENANT_ID", ""),
        shipstation_api_key=os.environ.get("SHIPSTATION_API_KEY", ""),
        shipstation_api_secret=os.environ.get("SHIPSTATION_API_SECRET", ""),
        generic_orders_url=os.environ.get("GENERIC_ORDERS_URL", ""),
        generic_auth_header=os.environ.get("GENERIC_AUTH_HEADER", ""),
        generic_fields=os.environ.get("GENERIC_FIELDS", ""),
    )
