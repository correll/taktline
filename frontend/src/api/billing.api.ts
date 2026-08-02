import { client } from './client'

// `client` unwraps `response.data` in an interceptor, so these return the body
// directly — no `.then(r => r.data)`.

export interface Plan {
  code: string
  label: string
  stations: number | null
  integrations: boolean
  monthlyCents: number
  blurb: string
  purchasable: boolean
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
  trialEndsAt: string | null
  currentPeriodEnd: string | null
  graceEndsAt: string | null
  settling: boolean
  usage: { stations: number; stationLimit: number | null }
  billingEnabled: boolean
  hasPaymentMethod: boolean
}

export interface TrialStop {
  companyName: string
  valid: boolean
  stations: number
  lots: number
}

export const billingApi = {
  plans: (): Promise<Plan[]> => client.get('/billing/plans'),

  subscription: (companyId: string): Promise<Subscription> =>
    client.get(`/billing/${companyId}/subscription`),

  /** Returns a Stripe-hosted URL to send the browser to. */
  checkout: (companyId: string, planCode: string, onPremise = false): Promise<{ url: string }> =>
    client.post(`/billing/${companyId}/checkout`, { planCode, onPremise }),

  /** Payment method, invoices and cancellation — Stripe's own portal. */
  portal: (companyId: string): Promise<{ url: string }> =>
    client.post(`/billing/${companyId}/portal`, {}),

  /** Prorated to the day. Upgrades are invoiced now; downgrades credit forward. */
  changePlan: (companyId: string, planCode: string, onPremise = false): Promise<Subscription> =>
    client.post(`/billing/${companyId}/change-plan`, { planCode, onPremise }),

  /** What the opt-out link in a trial email is about to destroy. */
  describeTrialStop: (companyId: string, token: string): Promise<TrialStop> =>
    client.get('/billing/trial/stop', { params: { company: companyId, token } }),

  stopTrial: (companyId: string, token: string): Promise<void> =>
    client.post('/billing/trial/stop', null, { params: { company: companyId, token } }),
}

export function money(cents: number): string {
  return `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}
