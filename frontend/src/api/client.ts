import axios from 'axios'

export const ACTIVE_COMPANY_KEY = 'taktline.activeCompanyId'

const UNSAFE = new Set(['post', 'put', 'patch', 'delete'])

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return m ? decodeURIComponent(m[1]) : null
}

// Dev: '/api' (proxied by Vite to the backend). Cross-origin prod: set
// VITE_API_URL to the backend origin (e.g. https://api.example.com). Same-origin
// prod: set VITE_API_URL='' so requests hit the current origin's API paths.
const API_BASE = import.meta.env.VITE_API_URL ?? '/api'

export const client = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,   // send/receive the httpOnly session + csrf cookies
})

// Attach the active company and, on state-changing requests, the CSRF token
// (double-submit: header must match the readable taktline_csrf cookie).
client.interceptors.request.use((config) => {
  const companyId = localStorage.getItem(ACTIVE_COMPANY_KEY)
  if (companyId) config.headers['X-Company-Id'] = companyId
  if (UNSAFE.has((config.method ?? 'get').toLowerCase())) {
    const csrf = readCookie('taktline_csrf')
    if (csrf) config.headers['X-CSRF-Token'] = csrf
  }
  return config
})

// Unwrap .data so callers get the payload directly; reject with an ApiError
// whose toString() is just the detail (so existing `String(e)` displays are
// unchanged) and whose .status is undefined for network-level failures — that
// distinction lets the app treat "server unreachable" differently from "denied".
export class ApiError extends Error {
  status?: number
  /** Present on 402/403 refusals that carry a plan reason. */
  refusal?: PlanRefusal
  toString() { return this.message }
}

export function isNetworkError(e: unknown): boolean {
  // No response at all (origin down) or a gateway saying the backend is gone —
  // both mean "server unreachable", not "request denied".
  return e instanceof ApiError && (e.status === undefined || [502, 503, 504].includes(e.status))
}

/** The machine-readable body the backend attaches to a refusal.
 *
 *  402 (subscription) and 403 (plan limit) both carry one. It exists so the
 *  client can offer a way forward — "upgrade to Professional", "remove three
 *  stations" — instead of surfacing a sentence in a toast and leaving the user
 *  to work out what to do.
 */
export interface PlanRefusal {
  message: string
  code: 'subscription_required' | 'read_only' | 'plan_limit' | 'over_limit_for_plan'
  plan?: string
  resource?: string
  limit?: number
  used?: number
  reason?: string
  graceEndsAt?: string | null
}

function refusalOf(data: unknown): PlanRefusal | undefined {
  const detail = (data as { detail?: unknown })?.detail
  if (detail && typeof detail === 'object' && 'code' in (detail as object)) {
    return detail as PlanRefusal
  }
  return undefined
}

// A 401 signals a lost/expired session — broadcast it so the auth provider can
// redirect to /login (it ignores the expected bootstrap 401).
client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      window.dispatchEvent(new CustomEvent('taktline:unauthorized'))
    }
    const refusal = refusalOf(err.response?.data)
    if (refusal && (status === 402 || status === 403)) {
      // Broadcast rather than redirect. A 402 arrives most often from a write
      // the user just attempted, and bouncing them out of the view they were
      // working in loses their place for no gain — the banner and the upgrade
      // dialog can both be raised from here.
      window.dispatchEvent(new CustomEvent('taktline:plan-refusal', { detail: refusal }))
    }
    const detail = err.response?.data?.detail
    const message = refusal?.message
      ?? (typeof detail === 'string' ? detail : err.message)
    const apiErr = new ApiError(String(message))
    apiErr.status = status
    apiErr.refusal = refusal
    return Promise.reject(apiErr)
  }
)
