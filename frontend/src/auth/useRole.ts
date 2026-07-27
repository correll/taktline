import { useAuthStore } from '../store/auth.store'
import type { Role } from '../api/auth.api'

const RANK: Record<Role, number> = { user: 0, admin: 1, super_admin: 2 }

/** The current user's role in the active company, plus convenience flags.
 *
 *   canManageLots — admin or super-admin: create lots, pull precursors, orders.
 *   canEdit       — super-admin only: process/floor config, member management,
 *                   and structural lot ops (board drag, move, unmerge, delete).
 *   isAdmin       — kept as an alias of canManageLots (admin tier and above).
 */
export function useRole(): {
  role: Role | null
  isSuperAdmin: boolean
  isAdmin: boolean
  canManageLots: boolean
  canEdit: boolean
} {
  const companies = useAuthStore((s) => s.companies)
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)
  const role = (companies.find((c) => c.id === activeCompanyId)?.role ?? null) as Role | null
  const rank = role ? RANK[role] : -1
  const isSuperAdmin = rank >= RANK.super_admin
  const canManageLots = rank >= RANK.admin
  return { role, isSuperAdmin, isAdmin: canManageLots, canManageLots, canEdit: isSuperAdmin }
}
