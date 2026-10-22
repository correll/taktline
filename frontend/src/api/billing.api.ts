import { client } from './client'

// `client` unwraps `response.data` in an interceptor, so these return the body
// directly — no `.then(r => r.data)`.

/** The **published** price list: Free and Shop, the two tiers bought without
 *  talking to anyone. Plant and Enterprise carry no number by design and so
 *  have no field here — see `PricingOut` in `routers/billing.py`. */
export interface Pricing {
  freeStations: number
  /** Shop: a base covering the first `shopBaseStations`, then a step each. */
  shopBaseCents: number
  shopBaseStations: number
  shopPerStationCents: number
  /** Past this, Shop stops and the answer is a conversation. */
  shopStations: number
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
  /** When a voucher grant runs out (null otherwise). While it is in the
   *  future and there is no payment method, the plan is free until then. */
  compedUntil: string | null
  voucherCode: string | null
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

  /** Redeem a voucher code (e.g. EXAMPLE2026): the plan it names, free, for the
   *  months it says. Case-insensitive; a leading # is fine. No card asked. */
  redeemVoucher: (companyId: string, code: string): Promise<Subscription> =>
    client.post(`/billing/${companyId}/voucher`, { code }),
}

/** Shop's base-plus-step, mirrored from `plans.monthly_cents_for` for instant
 *  display. The server's number is authoritative; this exists so the price
 *  updates as the reader thinks about station counts, without a round trip
 *  each time. Clamped at the cap for the same reason the server clamps: past
 *  it there is no Shop price to quote. */
export function monthlyCentsFor(stations: number, p: Pricing): number {
  const billable = Math.min(Math.max(stations, p.shopBaseStations), p.shopStations)
  return p.shopBaseCents + (billable - p.shopBaseStations) * p.shopPerStationCents
}

export function money(cents: number): string {
  return `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}
