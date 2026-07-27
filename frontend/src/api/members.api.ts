import { client } from './client'
import type { Role } from './auth.api'

export interface Member {
  userId: string
  email: string
  name: string | null
  role: Role
  joinedAt: string
}

export interface Invitation {
  id: string
  email: string
  role: Role
  status: 'pending' | 'accepted' | 'revoked' | 'expired'
  createdAt: string
  expiresAt: string
  devLink?: string | null
}

export interface InvitePreview {
  valid: boolean
  companyName?: string | null
  email?: string | null
  role?: Role | null
  reason?: string | null
}

export const membersApi = {
  list: (companyId: string): Promise<Member[]> =>
    client.get(`/companies/${companyId}/members`),
  remove: (companyId: string, userId: string): Promise<void> =>
    client.delete(`/companies/${companyId}/members/${userId}`),
  changeRole: (companyId: string, userId: string, role: Role): Promise<Member> =>
    client.patch(`/companies/${companyId}/members/${userId}`, { role }),

  invite: (companyId: string, email: string, role: Role): Promise<Invitation> =>
    client.post(`/companies/${companyId}/invitations`, { email, role }),
  listInvitations: (companyId: string): Promise<Invitation[]> =>
    client.get(`/companies/${companyId}/invitations`),
  revokeInvitation: (companyId: string, invitationId: string): Promise<void> =>
    client.delete(`/companies/${companyId}/invitations/${invitationId}`),
}

export const invitesApi = {
  preview: (token: string): Promise<InvitePreview> => client.get(`/invitations/${token}`),
  accept: (token: string): Promise<unknown> => client.post(`/invitations/${token}/accept`),
  acceptSignup: (token: string, password: string, name?: string): Promise<unknown> =>
    client.post(`/invitations/${token}/accept-signup`, { password, name }),
}
