import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { immer } from 'zustand/middleware/immer'
import { authApi, type CompanyMembership, type MeResponse, type User } from '../api/auth.api'
import { ACTIVE_COMPANY_KEY, isNetworkError } from '../api/client'
import { clearAllCaches, loadMe, saveMe } from './offlineCache'
import { isLang } from '../i18n/languages'
import { useI18nStore } from '../i18n'
import { useThemeStore } from './theme.store'

type Status = 'loading' | 'authed' | 'anon'

interface AuthState {
  status: Status
  user: User | null
  companies: CompanyMembership[]
  activeCompanyId: string | null

  bootstrap: () => Promise<void>
  applyMe: (me: MeResponse) => void
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  setActiveCompany: (id: string) => void
  /** End the local session. `wipeCache` clears the offline snapshots too —
   *  true whenever the server told us the session is gone (logout, 401), false
   *  only for network-level failures where the cache is the whole point. */
  markAnon: (wipeCache?: boolean) => void
}

function pickActive(companies: CompanyMembership[], preferred: string | null): string | null {
  if (preferred && companies.some((c) => c.id === preferred)) return preferred
  return companies[0]?.id ?? null
}

function syncActive(id: string | null) {
  if (id) localStorage.setItem(ACTIVE_COMPANY_KEY, id)
  else localStorage.removeItem(ACTIVE_COMPANY_KEY)
}

export const useAuthStore = create<AuthState>()(
  devtools(
    immer((set, get) => ({
      status: 'loading',
      user: null,
      companies: [],
      activeCompanyId: null,

      applyMe: (me) => {
        set((s) => {
          s.user = me.user
          s.companies = me.companies
          const stored = localStorage.getItem(ACTIVE_COMPANY_KEY)
          const active = pickActive(me.companies, get().activeCompanyId ?? stored)
          s.activeCompanyId = active
          syncActive(active)
          s.status = 'authed'
        })
        // The account's stored theme follows the user across devices.
        const theme = me.user.preferences?.theme
        if (theme === 'day' || theme === 'night') useThemeStore.getState().syncFromUser(theme)
        // …and so does the language.
        const lang = me.user.preferences?.language
        if (isLang(lang)) useI18nStore.getState().syncFromUser(lang)
        saveMe(me)
      },

      bootstrap: async () => {
        try {
          get().applyMe(await authApi.me())
        } catch (e) {
          // Server unreachable ≠ signed out: the cookie may still be valid, the
          // host is just down/rebooting. Boot from the cached identity so the
          // (also cached) board renders; a real 401 still lands on /login.
          if (isNetworkError(e)) {
            const cached = loadMe<MeResponse>()
            if (cached) { get().applyMe(cached); return }
            get().markAnon(false)   // keep snapshots: the server, not the session, is gone
            return
          }
          get().markAnon()
        }
      },

      refresh: async () => {
        try {
          get().applyMe(await authApi.me())
        } catch (e) {
          if (isNetworkError(e)) { get().markAnon(false); return }
          get().markAnon()
        }
      },

      login: async (email, password) => {
        get().applyMe(await authApi.login(email, password))
      },

      logout: async () => {
        try { await authApi.logout() } catch { /* ignore */ }
        get().markAnon()   // wipes the offline snapshots (shared tablets)
      },

      markAnon: (wipeCache = true) => {
        // A server-confirmed end of session must not leave last-known-good
        // company data (or the cached identity) readable on a shared tablet.
        if (wipeCache) clearAllCaches()
        set((s) => {
          s.status = 'anon'
          s.user = null
          s.companies = []
          s.activeCompanyId = null
          syncActive(null)
        })
      },

      setActiveCompany: (id) =>
        set((s) => {
          if (s.companies.some((c) => c.id === id)) {
            s.activeCompanyId = id
            syncActive(id)
          }
        }),
    })),
    { name: 'taktline/auth' }
  )
)
