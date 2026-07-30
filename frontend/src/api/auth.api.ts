import { client } from './client'

// Ordered by privilege: user < admin < super_admin.
//   user        — operator (run sessions, merge, advance, set status)
//   admin       — user + create lots, pull precursors, release/cancel orders
//   super_admin — everything: config, member management, structural lot ops
export type Role = 'super_admin' | 'admin' | 'user'

export const ROLE_LABEL: Record<Role, string> = {
  super_admin: 'Super admin',
  admin:       'Admin',
  user:        'User',
}

export interface UserPreferences {
  theme?: 'day' | 'night'
}

export interface User {
  id: string
  email: string
  emailVerified: boolean
  name: string | null
  preferences?: UserPreferences
  platformRole?: 'owner' | 'support' | null   // customer-service tier
  isSandbox?: boolean                          // anonymous try-it account (restricted)
}

export interface CompanyMembership {
  id: string
  name: string
  slug: string | null
  role: Role
  timezone: string
  impersonated?: boolean               // platform staff acting via a support grant
  impersonationExpiresAt?: string | null
}

export interface MeResponse {
  user: User
  companies: CompanyMembership[]
}

export interface MessageResponse {
  message: string
  devLink?: string | null
}

export const authApi = {
  signup: (email: string, password: string, name?: string,
           opts?: { adoptSandbox?: boolean; companyName?: string
                    acceptedTermsVersion?: string }): Promise<MessageResponse> =>
    client.post('/auth/signup', { email, password, name, ...opts }),
  verifyEmail: (token: string): Promise<MessageResponse> =>
    client.post('/auth/verify-email', { token }),
  resendVerification: (email: string): Promise<MessageResponse> =>
    client.post('/auth/resend-verification', { email }),
  login: (email: string, password: string): Promise<MeResponse> =>
    client.post('/auth/login', { email, password }),
  logout: (): Promise<void> => client.post('/auth/logout'),
  me: (): Promise<MeResponse> => client.get('/auth/me'),
  sandbox: (): Promise<{ companyId: string; csrfToken: string }> => client.post('/auth/sandbox'),
  updatePreferences: (prefs: UserPreferences): Promise<User> =>
    client.patch('/auth/me/preferences', prefs),
  forgotPassword: (email: string): Promise<MessageResponse> =>
    client.post('/auth/forgot-password', { email }),
  resetPassword: (token: string, newPassword: string): Promise<MessageResponse> =>
    client.post('/auth/reset-password', { token, newPassword }),
}
