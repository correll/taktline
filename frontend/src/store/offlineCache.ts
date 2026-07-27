import { ACTIVE_COMPANY_KEY } from '../api/client'
import { useMachinesStore } from './machines.store'

// Last-known-good snapshots of company-scoped read data, persisted per company.
// A page reload while the server is unreachable (reboot, free-tier cold start)
// then renders the cached state instead of an empty app; the amber banner tells
// the user how old it is. Only READS are cached — mutations are never queued or
// replayed, they fail loudly instead (silent replay after an outage can reorder
// lot movements).

interface Snapshot {
  at: string                      // ISO timestamp of the last successful fetch
  slices: Record<string, unknown> // slice name → data
}

const key = (companyId: string) => `taktline.cache.${companyId}`

function activeCompany(): string | null {
  try { return localStorage.getItem(ACTIVE_COMPANY_KEY) } catch { return null }
}

/** Store a slice after a successful fetch (quota errors are non-fatal). */
export function saveSlice(slice: string, data: unknown): void {
  const companyId = activeCompany()
  if (!companyId) return
  try {
    const raw = localStorage.getItem(key(companyId))
    const snap: Snapshot = raw ? JSON.parse(raw) : { at: '', slices: {} }
    snap.at = new Date().toISOString()
    snap.slices[slice] = data
    localStorage.setItem(key(companyId), JSON.stringify(snap))
  } catch { /* full or unavailable storage never breaks the app */ }
}

/** On fetch failure: return the cached slice (if any) and flag the UI stale. */
export function loadSlice<T>(slice: string): T | null {
  const companyId = activeCompany()
  if (!companyId) return null
  try {
    const raw = localStorage.getItem(key(companyId))
    if (!raw) return null
    const snap: Snapshot = JSON.parse(raw)
    if (!(slice in snap.slices)) return null
    useMachinesStore.getState().setStaleSince(snap.at)
    return snap.slices[slice] as T
  } catch {
    return null
  }
}

// ── Identity snapshot (user-scoped, not company-scoped) ───────────────────────
// Lets a reload during an outage boot straight into the cached board instead of
// bouncing to /login: the session cookie may well still be valid — the server
// is just not there to confirm it right now.

const ME_KEY = 'taktline.cache.me'

export function saveMe(me: unknown): void {
  try { localStorage.setItem(ME_KEY, JSON.stringify(me)) } catch { /* ignore */ }
}

export function loadMe<T>(): T | null {
  try {
    const raw = localStorage.getItem(ME_KEY)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

/** A server-confirmed end of session (logout or 401) wipes every cached
 *  snapshot — nothing about the previous user survives on a shared tablet. */
export function clearAllCaches(): void {
  try {
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith('taktline.cache.')) localStorage.removeItem(k)
    }
  } catch { /* ignore */ }
  // Drop cached floor-plan images from the service-worker cache too (the app
  // shell itself is public and can stay).
  if ('caches' in window) {
    caches.open('taktline-shell-v1').then(async (c) => {
      for (const req of await c.keys()) {
        if (new URL(req.url).pathname.startsWith('/uploads/')) await c.delete(req)
      }
    }).catch(() => {})
  }
}
