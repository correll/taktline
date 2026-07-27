# Taktline ERP connectors

Thin, standalone bridges that turn ERP orders into Taktline pull orders and push
Taktline completions back. Every connector shares one orchestration core and the
**same two-endpoint contract** — releasing an order and draining completions —
so adding an ERP means writing one small client, nothing else.

```
ERP order (Odoo MO / NetSuite WO)  ──►  POST /orders            (release a lot)
                                         201 = released · 200 = already known
Taktline finished-goods leaf reached ─►  GET  /orders/outbox?source=<erp>
                                         POST /orders/outbox/{id}/ack    (delivered)
                                         POST /orders/outbox/{id}/fail   (retry, then park)
                                         ──►  ERP order marked done / cancelled
```

## Architecture

```
taktline_connect/
  taktline.py      TaktlineClient   — the one shared dependency (API-key auth)
  core.py          Connector + Mapping — ERP-agnostic orchestration (unit-tested)
  config.py        env → Config
  odoo.py          OdooClient       (XML-RPC, mrp.production)
  netsuite.py      NetSuiteClient   (SuiteTalk REST/SuiteQL, OAuth 1.0a TBA)
  shopify.py       ShopifyClient    (Admin REST; cancel/refund → cancel; opt-in fulfil)
  woocommerce.py   WooClient        (wc/v3; cancel/refund → cancel)
  qbo.py           QboClient        (QuickBooks Online; OAuth2; Estimates → releases)
  xero.py          XeroClient       (Xero; OAuth2; accepted Quotes → releases)
  shipstation.py   ShipStationClient (awaiting_shipment → releases; completion → shipped)
  generic.py       GenericRestClient (poll any JSON orders endpoint — the long tail)
  oauth.py         shared OAuth2 refresh-token grant (QBO, Xero)
  __main__.py      python -m taktline_connect <odoo|netsuite|shopify|woocommerce|quickbooks|xero|shipstation|generic>
```

An ERP client is anything implementing `list_orders`; the shared `Connector`
does the rest. The other methods are **optional** — implement only what the
system supports:

```python
list_orders(states) -> [{'id', 'product_ref', 'qty', 'state'}]   # required (releases)
list_cancellations(states) -> [external_ref]   # ERP is the source of cancels (Shopify/Woo)
mark_done(external_ref) -> None                # Taktline order.completed → close in ERP
cancel(external_ref)    -> None                # Taktline order.cancelled → cancel in ERP
```

Each cycle the connector runs three passes: **release** new ERP orders →
**cancel** (propagate ERP-initiated cancels/refunds to Taktline) → **drain**
Taktline completions back to the ERP. Every write is idempotent, so re-polling
and restarts are safe.

Products are mapped in config (`PRODUCT_MAPPING`) straight to Taktline **template
ids**, so the connector never needs any endpoint beyond `orders` — which is
exactly what the scoped API key grants.

## Setup

```bash
cd connectors
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # fill in TAKTLINE_API_KEY, PRODUCT_MAPPING, ERP creds
```

1. In Taktline: **Settings → Integrations → API keys**, create a key (scope
   `orders`), copy it once into `TAKTLINE_API_KEY`.
2. Same tab, **Product ids**: copy each template id into `PRODUCT_MAPPING`,
   keyed by the ERP's product ref (Odoo `default_code`, NetSuite `itemid`).

## Run

```bash
set -a; source .env; set +a
python -m taktline_connect odoo        # or: netsuite, shopify, woocommerce,
                                       # quickbooks (qbo), xero, shipstation, generic
```

## Test

```bash
pip install pytest
pytest tests/ -v                       # orchestration, all ERPs, no network
```

## Adding another system

Shipped connectors: **Odoo, NetSuite, Shopify, WooCommerce, QuickBooks Online,
Xero, ShipStation**, plus a **generic** JSON poller. The remaining long tail —
**Zoho Inventory, Cin7/DEAR, MRPeasy, Acumatica, Dynamics 365 Business
Central** — is either:

1. **No code:** point the `generic` connector at the system's REST orders
   endpoint and map its field names via `GENERIC_FIELDS`. Works whenever the
   system can expose a JSON list of orders with a bearer/basic auth header.
2. **~30 lines:** if it needs OAuth ceremony, pagination, or a completion
   callback, write a client with `list_orders` (+ optional
   `list_cancellations`/`mark_done`) and a `build(cfg)` — copy `shopify.py`
   (Basic/token) or `xero.py` (OAuth2 refresh) as the template. The shared
   `Connector` is unchanged. Every client factors its parsing into a pure
   `orders_from_*` function so it's unit-tested without a live account.

On-prem systems (**Fishbowl, Epicor, Infor, SAP B1**) use the same client
pattern, but run the connector inside the customer LAN next to the ERP.

**Accounting note:** QBO/Xero have no manufacturing order, so a sales document
(accepted Estimate / Quote) is the "make this" signal — the admin picks the
document type/status. Their line items map by Item name/code via `PRODUCT_MAPPING`.

## Notes

- **Idempotent:** `POST /orders` dedupes on `(source, externalRef)`, and
  `POST /orders/cancel` is a no-op on an already-cancelled order — so restarts
  and overlapping polls never double-release or double-cancel.
- **At-least-once completions:** an outbox event is only ack'd after the ERP
  write succeeds; a failed delivery is reported (`/fail`) and retried next cycle,
  and parks as `failed` after ten attempts so an event the ERP can never accept
  stops consuming a slot in every poll. Because delivery can repeat, `mark_done`
  must be idempotent — NetSuite checks for an existing assemblyBuild first, or a
  redelivery would post the finished goods into inventory twice.
- **Scoped outbox polling:** each connector drains `?source=<its own source>`.
  Releases nobody acks (a manual UI release, a CSV import) stay pending forever,
  and a shared window would eventually fill with them.
- **Pagination:** every client walks all pages (Shopify's `Link` cursor, Woo's
  `X-WP-TotalPages` oldest-first, ShipStation `pages`, Xero `page`, QBO
  `STARTPOSITION`, NetSuite `hasMore`). Page one alone silently starves the
  backlog — an order that never releases never leaves the ERP's open set either.
- **OAuth token rotation:** QBO and Xero invalidate the refresh token on use, so
  the rotated value is persisted to `TOKEN_STORE` (default
  `.taktline-tokens.json`). On an ephemeral filesystem the connector cannot
  authenticate after a restart — mount it.
- **Edits/refunds:** Shopify/Woo cancellations and full refunds map to
  `POST /orders/cancel` (scraps in-flight lots). A quantity *edit* is modelled as
  cancel + re-release, not an in-place order mutation.
- **NetSuite** SuiteQL and `assemblyBuild` shapes are account-configuration
  specific — the queries in `netsuite.py` are a working starting point; tune the
  custom fields/statuses for your instance. The orchestration doesn't change.
- **Storefront keys:** create a Taktline API key with the `orders` scope for
  Shopify/Woo/generic connectors. Scanners/print stations use a `cards:advance`
  key; BI tools a `reports` key.
