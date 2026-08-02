import { useAuthStore } from '../store/auth.store'
import { useStationsStore } from '../store/stations.store'

/**
 * What the active company's plan allows, and how close it is to the edge.
 *
 * Shaped like `useRole` and read from the same place: `/auth/me` carries the
 * billing state on every company, so this needs no fetch and is correct from
 * the first render. It is **UX only** — the server refuses independently, and
 * an offline tablet can be looking at a cached `/auth/me` that is a day old.
 * Never let this decide anything that matters; let it decide what to *show*.
 */
export function usePlan() {
  const companies = useAuthStore((s) => s.companies)
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)
  const stations = useStationsStore((s) => s.stations)

  const company = companies.find((c) => c.id === activeCompanyId)
  const limit = company?.stationLimit ?? null
  const used = Object.keys(stations).length
  const remaining = limit === null ? null : Math.max(0, limit - used)

  const trialEndsAt = company?.trialEndsAt ? new Date(company.trialEndsAt) : null
  const daysLeft = trialEndsAt
    ? Math.max(0, Math.ceil((trialEndsAt.getTime() - Date.now()) / 86_400_000))
    : null

  return {
    plan: company?.plan ?? 'trial',
    planLabel: company?.planLabel ?? 'Trial',
    state: company?.planState ?? 'ok',
    locked: company?.planState === 'locked',
    readOnly: company?.planState === 'read_only',
    isTrial: company?.plan === 'trial',
    isSandbox: company?.plan === 'sandbox',
    integrations: company?.integrations ?? false,
    stationLimit: limit,
    stationsUsed: used,
    stationsRemaining: remaining,
    /** At or past the ceiling — creating another will be refused. */
    atStationLimit: limit !== null && used >= limit,
    /** Close enough that saying so is useful rather than nagging. */
    nearStationLimit: limit !== null && used >= limit * 0.8 && used < limit,
    trialEndsAt,
    trialDaysLeft: daysLeft,
  }
}
