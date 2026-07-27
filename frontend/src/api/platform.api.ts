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

export const platformApi = {
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
}
