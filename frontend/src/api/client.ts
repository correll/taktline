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
  toString() { return this.message }
}

export function isNetworkError(e: unknown): boolean {
  // No response at all (origin down) or a gateway saying the backend is gone —
  // both mean "server unreachable", not "request denied".
  return e instanceof ApiError && (e.status === undefined || [502, 503, 504].includes(e.status))
}

// A 401 signals a lost/expired session — broadcast it so the auth provider can
// redirect to /login (it ignores the expected bootstrap 401).
client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    if (err.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('taktline:unauthorized'))
    }
    const apiErr = new ApiError(String(err.response?.data?.detail ?? err.message))
    apiErr.status = err.response?.status
    return Promise.reject(apiErr)
  }
)
