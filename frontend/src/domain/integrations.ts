/** The integration partners a station can be bound to.
 *
 *  An **integration station** is where work enters or leaves the business.
 *  Until now that boundary was implicit in the graph's shape — any leaf with no
 *  incoming routes could originate lots, and *any* leaf with no outgoing routes
 *  completed orders — so you could not look at the map and see where work came
 *  from or went, and a company with both a warehouse and a shipping desk had no
 *  way to say which one ships.
 *
 *  Marks are one or two letters rather than logos: partner logos are trademarked
 *  artwork with usage rules, they do not survive being drawn at 14px on a map
 *  node, and they would need re-licensing every time a partner rebrands. Two
 *  letters where the initial collides — Shopify and ShipStation are both S.
 *
 *  Colours are the partners' brand hues, used only as an identifying tint on
 *  the node. They are deliberately *not* in the app's palette: an integration
 *  node is a foreign object on the shop floor and should read as one.
 */

export type IntegrationRole = 'source' | 'sink' | 'both'

/** One thing you must fetch from the partner and paste into the connector. */
export interface SetupField {
  /** The environment variable the connector reads (connectors/taktline_connect/config.py). */
  env:   string
  label: string
  /** Where to find it in the partner's UI — the part nobody can guess. */
  where: string
  optional?: boolean
}

export interface IntegrationSetup {
  /** What you have to obtain from the partner's account. */
  fields: SetupField[]
  /** What you must create or change *inside* the partner, beyond copying keys. */
  inPartner: string[]
  /** Which of Taktline's order states the connector should treat as "make this". */
  orderStates?: string
  /** Anything that will bite later if it is not said now. */
  caveats?: string[]
}

export interface IntegrationProvider {
  id:          string
  label:       string
  /** One or two letters. Two where the initial is ambiguous. */
  mark:        string
  /** Partner brand colour. */
  color:       string
  /** Ink on top of `color` — set per provider because some brand hues are light. */
  ink:         string
  defaultRole: IntegrationRole
  /** What the partner does, in the words someone setting it up would use. */
  blurb:       string
  /** Everything needed to connect it, so nobody has to create a trial account
   *  to discover what the connector wants. Env names must match config.py —
   *  connectors/tests/test_config_contract.py fails if they drift. */
  setup:       IntegrationSetup
}

export const INTEGRATION_PROVIDERS: IntegrationProvider[] = [
  { id: 'odoo', label: 'Odoo', mark: 'O', color: '#714B67', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Manufacturing orders in, finished goods back.',
    setup: {
      fields: [
        { env: 'ODOO_URL',      label: 'Instance URL',
          where: 'The address you log in at, e.g. https://acme.odoo.com — no trailing path.' },
        { env: 'ODOO_DB',       label: 'Database name',
          where: 'Settings → shown under the version string; on odoo.com it is usually your subdomain.' },
        { env: 'ODOO_USERNAME', label: 'Login email',
          where: 'The user the connector acts as. Give it a dedicated account, not a person’s.' },
        { env: 'ODOO_API_KEY',  label: 'API key',
          where: 'Preferences → Account Security → New API Key. Shown once. (ODOO_PASSWORD also works but keys can be revoked.)' },
      ],
      inPartner: [
        'Enable Manufacturing (mrp) — the connector reads mrp.production records.',
        'Give the connector user read access to Manufacturing Orders and write access to mark them done.',
      ],
      orderStates: 'confirmed, progress — set ORDER_STATES to the states that mean "make this".',
      caveats: [
        'The connector polls; Odoo is never called by Taktline directly, so no inbound firewall rule is needed.',
      ],
    } },

  { id: 'netsuite', label: 'NetSuite', mark: 'N', color: '#1F5FA9', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Work orders in, assembly builds back.',
    setup: {
      fields: [
        { env: 'NETSUITE_ACCOUNT',         label: 'Account ID',
          where: 'Setup → Company → Company Information → Account ID (e.g. 1234567_SB1 for a sandbox).' },
        { env: 'NETSUITE_CONSUMER_KEY',    label: 'Consumer key',
          where: 'Setup → Integration → Manage Integrations → your integration record.' },
        { env: 'NETSUITE_CONSUMER_SECRET', label: 'Consumer secret', where: 'Same record, shown once at creation.' },
        { env: 'NETSUITE_TOKEN_ID',        label: 'Token ID',
          where: 'Setup → Users/Roles → Access Tokens → New Access Token.' },
        { env: 'NETSUITE_TOKEN_SECRET',    label: 'Token secret', where: 'Same token, shown once.' },
      ],
      inPartner: [
        'Create an Integration record with Token-Based Authentication enabled (OAuth 1.0a, not OAuth 2).',
        'Create an Access Token for the role the connector should act as.',
        'That role needs permission on Work Orders and Assembly Builds.',
      ],
      caveats: [
        'NetSuite completions are idempotent by design: the connector checks for an existing assemblyBuild first, because a lost ack would otherwise post finished goods to inventory twice.',
      ],
    } },

  { id: 'shopify', label: 'Shopify', mark: 'S', color: '#5E8E3E', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Store orders in, fulfilment back.',
    setup: {
      fields: [
        { env: 'SHOPIFY_SHOP',  label: 'Shop domain',
          where: 'my-store.myshopify.com — the myshopify address, not your custom domain.' },
        { env: 'SHOPIFY_TOKEN', label: 'Admin API access token',
          where: 'Settings → Apps and sales channels → Develop apps → your app → API credentials. Starts shpat_ and is shown once.' },
        { env: 'SHOPIFY_API_VERSION', label: 'API version', optional: true,
          where: 'Defaults to 2024-01. Only change it if you have a reason to.' },
        { env: 'SHOPIFY_FULFILL_ON_COMPLETE', label: 'Fulfil on completion', optional: true,
          where: 'Set to 1 to mark the Shopify order fulfilled when the lot ships. Leave unset if your shipper does that.' },
      ],
      inPartner: [
        'Create a custom app (Develop apps) — public apps are for the app store, not for this.',
        'Grant Admin API scopes: read_orders, and write_orders only if you want Taktline to fulfil.',
        'Products must carry the SKU you map to a Taktline product.',
      ],
      orderStates: 'paid — ORDER_STATES filters on financial_status.',
      caveats: [
        'One Kanban lot per line item, not per order: a two-line order releases two lots, each traceable to its own line.',
        'Refunds and cancellations flow back automatically — the connector cancels the matching Taktline order.',
      ],
    } },

  { id: 'woocommerce', label: 'WooCommerce', mark: 'W', color: '#7F54B3', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Store orders in, fulfilment back.',
    setup: {
      fields: [
        { env: 'WOO_URL',             label: 'Store URL', where: 'https://store.example.com — the site root.' },
        { env: 'WOO_CONSUMER_KEY',    label: 'Consumer key',
          where: 'WooCommerce → Settings → Advanced → REST API → Add key. Starts ck_.' },
        { env: 'WOO_CONSUMER_SECRET', label: 'Consumer secret', where: 'Same key, starts cs_, shown once.' },
      ],
      inPartner: [
        'Create a REST API key with Read/Write permissions.',
        'Your store must be reachable over HTTPS — the key is sent as basic auth.',
      ],
      orderStates: 'processing — ORDER_STATES filters on the Woo order status.',
    } },

  { id: 'qbo', label: 'QuickBooks', mark: 'QB', color: '#2CA01C', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Sales orders in, build completions back.',
    setup: {
      fields: [
        { env: 'QBO_CLIENT_ID',     label: 'Client ID',     where: 'Intuit developer portal → your app → Keys & credentials.' },
        { env: 'QBO_CLIENT_SECRET', label: 'Client secret', where: 'Same page.' },
        { env: 'QBO_REFRESH_TOKEN', label: 'Refresh token',
          where: 'From the OAuth 2 consent flow (the Playground is the quickest way). The connector rotates and stores it after that.' },
        { env: 'QBO_REALM_ID',      label: 'Company (realm) ID', where: 'Shown in the OAuth flow; also in your QuickBooks company settings.' },
        { env: 'QBO_ENV',           label: 'Environment', optional: true, where: 'production or sandbox. Defaults to production.' },
        { env: 'QBO_DOC',           label: 'Which document means "make this"', optional: true,
          where: 'Estimate (default) or SalesReceipt / Invoice, depending on how your shop sells.' },
      ],
      inPartner: [
        'Create an app in the Intuit developer portal and complete the OAuth 2 consent once.',
        'Map each QuickBooks item name to a Taktline product.',
      ],
      caveats: [
        'Refresh tokens rotate on every use and expire after ~100 days of inactivity — the connector persists the new one each cycle, so do not run two copies against one token.',
      ],
    } },

  { id: 'xero', label: 'Xero', mark: 'X', color: '#13B5EA', ink: '#00303F',
    defaultRole: 'both', blurb: 'Sales orders in, completions back.',
    setup: {
      fields: [
        { env: 'XERO_CLIENT_ID',     label: 'Client ID',     where: 'Xero developer portal → your app.' },
        { env: 'XERO_CLIENT_SECRET', label: 'Client secret', where: 'Same page, shown once.' },
        { env: 'XERO_REFRESH_TOKEN', label: 'Refresh token', where: 'From the OAuth 2 consent flow; rotated by the connector afterwards.' },
        { env: 'XERO_TENANT_ID',     label: 'Tenant ID',     where: 'The organisation the app was authorised against (connections endpoint returns it).' },
      ],
      inPartner: [
        'Create an OAuth 2 app and authorise it against the right organisation.',
        'Scopes: accounting.transactions (read, and write if completions should post back).',
      ],
      caveats: [
        'Like QuickBooks, the refresh token rotates on use — one connector instance per token.',
      ],
    } },

  { id: 'shipstation', label: 'ShipStation', mark: 'SS', color: '#0F4C81', ink: '#FFFFFF',
    defaultRole: 'sink', blurb: 'Goods leave here. Orders do not start at a shipper.',
    setup: {
      fields: [
        { env: 'SHIPSTATION_API_KEY',    label: 'API key',    where: 'Account → API Settings → API Keys.' },
        { env: 'SHIPSTATION_API_SECRET', label: 'API secret', where: 'Same page, generated alongside the key.' },
      ],
      inPartner: [
        'Generate an API key pair (auth is HTTP Basic).',
        'Item SKUs must match the products you map.',
      ],
      caveats: [
        'Sink only — a shipper cannot raise demand, so this station can never be wired as a source.',
      ],
    } },

  { id: 'generic', label: 'Generic JSON', mark: 'G', color: '#5A5750', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Poll any JSON endpoint you control.',
    setup: {
      fields: [
        { env: 'GENERIC_ORDERS_URL',  label: 'Orders endpoint', where: 'A URL returning a JSON array of open orders.' },
        { env: 'GENERIC_AUTH_HEADER', label: 'Authorization header', optional: true,
          where: 'Sent verbatim, e.g. "Bearer xyz" or "Basic …". Omit for an open endpoint.' },
        { env: 'GENERIC_FIELDS',      label: 'Field mapping', optional: true,
          where: 'JSON naming your fields, e.g. {"id":"ref","product_ref":"sku","qty":"quantity","state":"status"}.' },
      ],
      inPartner: [
        'Expose an endpoint returning the open orders you want made.',
        'Each row needs a stable id, a product reference, and a quantity.',
      ],
    } },

  { id: 'manual', label: 'Manual / CSV', mark: 'M', color: '#8A8681', ink: '#FFFFFF',
    defaultRole: 'source', blurb: 'Releases typed in the app or imported from a spreadsheet.',
    setup: {
      fields: [],
      inPartner: [
        'Nothing to connect — releases come from this app or a CSV upload.',
      ],
      caveats: [
        'Completions for manual releases can only be delivered if the lot leaves through a partner’s station; otherwise they stay in the outbox as a record.',
      ],
    } },
]

const BY_ID = new Map(INTEGRATION_PROVIDERS.map((p) => [p.id, p]))

export function integrationProvider(id: string | null | undefined): IntegrationProvider | undefined {
  return id ? BY_ID.get(id) : undefined
}

/** True for a station that represents the business boundary rather than a
 *  place work happens. Such a station is kept out of the heatmap, out of the
 *  accumulation warnings and out of OEE/takt — nobody stands at an ERP. */
export function isIntegrationStation(s: { integrationProvider?: string | null }): boolean {
  return !!s.integrationProvider
}

/** A partner may only be bound to a role it can play. A shipper genuinely
 *  cannot raise demand — there is no ShipStation order asking a line to make
 *  something — so offering it as a source would be offering a dead control. */
export function allowedRoles(providerId: string): IntegrationRole[] {
  const p = BY_ID.get(providerId)
  if (!p) return ['both']
  return p.defaultRole === 'both' ? ['source', 'sink', 'both'] : [p.defaultRole]
}

export function roleLabel(role: IntegrationRole | null | undefined): string {
  return role === 'source' ? 'Work enters here'
       : role === 'sink'   ? 'Work leaves here'
       : role === 'both'   ? 'Work enters and leaves here'
       : ''
}
