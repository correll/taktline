import { client } from './client'

// `client` unwraps `response.data` in an interceptor, so these return the body
// directly — no `.then(r => r.data)`.

/** The whole price list — one metered plan, so it is arithmetic, not tiers. */
export interface Pricing {
  freeStations: number
  perStationCents: number
  minimumCents: number
  capCents: number
  minStations: number
  capStations: number
  onpremCents: number
}

export interface Subscription {
  plan: string
  planLabel: string
  state: 'ok' | 'read_only' | 'locked'
  reason: string | null
  onPremise: boolean
  stationLimit: number | null
  integrations: boolean
  monthlyCents: number
  currentPeriodEnd: string | null
  graceEndsAt: string | null
  settling: boolean
  usage: { stations: number; stationLimit: number | null }
  billingEnabled: boolean
  hasPaymentMethod: boolean
}

export const billingApi = {
  pricing: (): Promise<Pricing> => client.get('/billing/plans'),

  subscription: (companyId: string): Promise<Subscription> =>
    client.get(`/billing/${companyId}/subscription`),

  /** Returns a Stripe-hosted URL to send the browser to. The station count is
   *  not a parameter: the server bills the line it can see. */
  checkout: (companyId: string, onPremise = false): Promise<{ url: string }> =>
    client.post(`/billing/${companyId}/checkout`, { onPremise }),

  /** Payment method, invoices and cancellation — Stripe's own portal. */
  portal: (companyId: string): Promise<{ url: string }> =>
    client.post(`/billing/${companyId}/portal`, {}),

  /** The one plan change that exists. Adding is invoiced today; removing
   *  credits forward. */
  setOnPremise: (companyId: string, enabled: boolean): Promise<Subscription> =>
    client.post(`/billing/${companyId}/on-premise`, { enabled }),
}

/** The clamp, mirrored from `plans.monthly_cents_for` for instant display.
 *  The server's number is authoritative; this exists so the price updates as
 *  the reader thinks about station counts, without a round trip each time. */
export function monthlyCentsFor(stations: number, p: Pricing): number {
  return Math.min(Math.max(stations * p.perStationCents, p.minimumCents), p.capCents)
}

export function money(cents: number): string {
  return `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}
