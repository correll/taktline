import { client } from './client'

// Customer-service ("platform staff") API. Server returns 404 on every route
// for non-staff — the UI additionally hides the entry points.

export interface PlatformStatus {
  uptimeSeconds: number
  requestsTotal: number
  requestsPerMinute: { minute: number; requests: number }[]
  wsConnections: number
  authSessionsActive: number
  workSessionsOpen: number
  cardEvents24h: number
  supportGrantsActive: number
  usersTotal: number
  companiesTotal: number
  stationsTotal: number
  cardsTotal: number
  mrrCents: number
  arrCents: number
  payingCompanies: number
  trialingCompanies: number
  atRiskCompanies: number
}

export interface PlatformUser {
  id: string
  email: string
  name: string | null
  emailVerified: boolean
  platformRole: 'owner' | 'support' | null
  createdAt: string
  lastSeenAt: string | null
  companies: { companyId: string; companyName: string; role: string }[]
}

export interface PlatformCompany {
  id: string
  name: string
  createdAt: string
  members: number
  activeUsers: number
  stations: number
  cards: number
  devicesConnected: number
  apiRequestsMonth: number
  wsMessagesMonth: number
  lastActivityAt: string | null
  plan: string | null
  planState: 'ok' | 'read_only' | 'locked' | null
  mrrCents: number
  renewsAt: string | null
  trialEndsAt: string | null
}

export interface AuditEntry {
  id: string
  actorEmail: string
  action: string
  targetType: string | null
  targetId: string | null
  detail: Record<string, unknown>
  createdAt: string
}

export interface ClientErrorReport {
  id: string
  companyId: string | null
  userEmail: string | null
  message: string
  stack: string
  componentStack: string
  url: string
  userAgent: string
  appVersion: string
  createdAt: string
}

export const platformApi = {
  /** Crash reports from the frontend error boundary. The bare
   *  /platform/client-errors path belongs to the SPA page, so the data lives
   *  one level down. */
  clientErrors: (companyId?: string): Promise<ClientErrorReport[]> =>
    client.get('/platform/client-errors/list', { params: { companyId } }),
  status:    (): Promise<PlatformStatus>    => client.get('/platform/status'),
  users:     (): Promise<PlatformUser[]>    => client.get('/platform/users'),
  companies: (): Promise<PlatformCompany[]> => client.get('/platform/companies'),
  audit:     (): Promise<AuditEntry[]>      => client.get('/platform/audit'),

  impersonate: (companyId: string, minutes = 60): Promise<{ companyId: string; expiresAt: string }> =>
    client.post('/platform/impersonate', { companyId, minutes }),
  endImpersonation: (companyId: string): Promise<void> =>
    client.delete(`/platform/impersonate/${companyId}`),

  deleteCompany: (id: string, confirmName: string): Promise<void> =>
    client.request({ method: 'DELETE', url: `/platform/companies/${id}`, data: { confirmName } }),
  deleteUser: (id: string): Promise<void> => client.delete(`/platform/users/${id}`),
  setPlatformRole: (id: string, role: 'support' | null): Promise<void> =>
    client.put(`/platform/users/${id}/platform-role`, { role }),

  /** Dismiss one crash report once it has been read, reported or fixed. */
  deleteClientError: (id: string): Promise<void> =>
    client.delete(`/platform/client-errors/${id}`),
  /** Clear every report, or every copy of one message — the same crash from
   *  twenty browsers is twenty rows saying one thing. */
  clearClientErrors: (message?: string): Promise<{ removed: number }> =>
    client.delete('/platform/client-errors', { params: { message } }),
}
