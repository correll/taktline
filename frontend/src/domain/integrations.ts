/** The integration partners a location can be bound to.
 *
 *  An **integration location** is where work enters or leaves the business.
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
}

export const INTEGRATION_PROVIDERS: IntegrationProvider[] = [
  { id: 'odoo',        label: 'Odoo',         mark: 'O',  color: '#714B67', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Manufacturing orders in, finished goods back.' },
  { id: 'netsuite',    label: 'NetSuite',     mark: 'N',  color: '#1F5FA9', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Work orders in, assembly builds back.' },
  { id: 'shopify',     label: 'Shopify',      mark: 'S',  color: '#5E8E3E', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Store orders in, fulfilment back.' },
  { id: 'woocommerce', label: 'WooCommerce',  mark: 'W',  color: '#7F54B3', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Store orders in, fulfilment back.' },
  { id: 'qbo',         label: 'QuickBooks',   mark: 'QB', color: '#2CA01C', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Sales orders in, build completions back.' },
  { id: 'xero',        label: 'Xero',         mark: 'X',  color: '#13B5EA', ink: '#00303F',
    defaultRole: 'both', blurb: 'Sales orders in, completions back.' },
  { id: 'shipstation', label: 'ShipStation',  mark: 'SS', color: '#0F4C81', ink: '#FFFFFF',
    defaultRole: 'sink', blurb: 'Goods leave here. Orders do not start at a shipper.' },
  { id: 'generic',     label: 'Generic JSON', mark: 'G',  color: '#5A5750', ink: '#FFFFFF',
    defaultRole: 'both', blurb: 'Poll any JSON endpoint you control.' },
  { id: 'manual',      label: 'Manual / CSV', mark: 'M',  color: '#8A8681', ink: '#FFFFFF',
    defaultRole: 'source', blurb: 'Releases typed in the app or imported from a spreadsheet.' },
]

const BY_ID = new Map(INTEGRATION_PROVIDERS.map((p) => [p.id, p]))

export function integrationProvider(id: string | null | undefined): IntegrationProvider | undefined {
  return id ? BY_ID.get(id) : undefined
}

/** True for a location that represents the business boundary rather than a
 *  place work happens. Such a location is kept out of the heatmap, out of the
 *  accumulation warnings and out of OEE/takt — nobody stands at an ERP. */
export function isIntegrationStation(s: { integrationProvider?: string | null }): boolean {
  return !!s.integrationProvider
}

export function roleLabel(role: IntegrationRole | null | undefined): string {
  return role === 'source' ? 'Work enters here'
       : role === 'sink'   ? 'Work leaves here'
       : role === 'both'   ? 'Work enters and leaves here'
       : ''
}
