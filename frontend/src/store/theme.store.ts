import { create } from 'zustand'
import { authApi } from '../api/auth.api'
import { useAuthStore } from './auth.store'

// Day / night theme (BRANDING.md §2). Day is the default. The choice lives in
// the signed-in user's preferences (cross-device); localStorage only mirrors
// it so index.html can apply the right theme before first paint. Applied as
// `data-theme` on <html>, which swaps the CSS variable blocks in
// theme/global.css.

export type ThemeMode = 'night' | 'day'

const STORAGE_KEY = 'taktline.theme'

function storedMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === 'day' || raw === 'night') return raw
  } catch {
    /* ignore */
  }
  return 'day'
}

function applyMode(mode: ThemeMode) {
  document.documentElement.dataset.theme = mode
  try {
    localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    /* ignore */
  }
}

interface ThemeState {
  mode:   ThemeMode
  toggle: () => void
  set:    (mode: ThemeMode) => void
  /** Apply the theme from the user's stored preferences (no server write). */
  syncFromUser: (mode: ThemeMode) => void
}

export const useThemeStore = create<ThemeState>()((set, get) => ({
  mode: storedMode(),

  toggle: () => get().set(get().mode === 'night' ? 'day' : 'night'),

  set: (mode) => {
    applyMode(mode)
    set({ mode })
    // Persist with the account so every device follows; fire-and-forget (a
    // pre-login toggle simply stays local until the next signed-in change).
    if (useAuthStore.getState().status === 'authed') {
      authApi.updatePreferences({ theme: mode }).catch(() => {})
    }
  },

  syncFromUser: (mode) => {
    if (mode === get().mode) return
    applyMode(mode)
    set({ mode })
  },
}))

// Sync the DOM on load (covers the case where index.html's inline script ran
// before localStorage was written, or the module is hot-reloaded).
applyMode(useThemeStore.getState().mode)
