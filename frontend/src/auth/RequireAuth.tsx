import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth.store'
import { useRole } from './useRole'

/** Gate for authenticated routes. Redirects anon users to /login and
 *  authenticated users with no company to /create-company. */
export function RequireAuth({ children, allowNoCompany = false }: {
  children: React.ReactNode
  allowNoCompany?: boolean
}) {
  const status = useAuthStore((s) => s.status)
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)

  if (status === 'anon') return <Navigate to="/login" replace />
  if (!allowNoCompany && !activeCompanyId) return <Navigate to="/create-company" replace />
  return <>{children}</>
}

/** Gate for super-admin-only routes (Settings: config + member management).
 *  Everyone below super-admin is bounced to /lots. */
export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { isSuperAdmin } = useRole()
  if (!isSuperAdmin) return <Navigate to="/lots" replace />
  return <>{children}</>
}
