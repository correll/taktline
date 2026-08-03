import { create } from 'zustand'
import { authApi } from '../api/auth.api'
import { DEFAULT_LANGUAGE, isLang, type Lang } from './languages'
import { STRINGS } from './strings'

// The language, shaped exactly like the theme (store/theme.store.ts): the
// signed-in choice lives in `preferences.language` (cross-device), and
// localStorage mirrors it so the signup and login pages — which render before
// /auth/me answers — speak the right language from first paint.
//
// No i18n library on purpose. The need is a dictionary lookup with a
// fallback; react-i18next is ~40 KB plus a provider, a suspense mode and a
// plural DSL, all to do what forty lines do here — and the KaTeX precedent
// applies (help/Equation.tsx): weigh the dependency against the four formulas.

const STORAGE_KEY = 'taktline.lang'

function storedLang(): Lang {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (isLang(raw)) return raw
  } catch { /* ignore */ }
  return DEFAULT_LANGUAGE
}

interface I18nState {
  lang: Lang
  /** Local + persisted to the account (fire-and-forget). */
  set: (lang: Lang) => void
  /** Apply the language from the user's stored preferences (no server write). */
  syncFromUser: (lang: Lang) => void
}

export const useI18nStore = create<I18nState>((set) => ({
  lang: storedLang(),
  set: (lang) => {
    set({ lang })
    try { localStorage.setItem(STORAGE_KEY, lang) } catch { /* ignore */ }
    // Signed-out (signup page) this 401s harmlessly; signed in it makes the
    // choice follow the account to every device.
    authApi.updatePreferences({ language: lang }).catch(() => {})
  },
  syncFromUser: (lang) => {
    set({ lang })
    try { localStorage.setItem(STORAGE_KEY, lang) } catch { /* ignore */ }
  },
}))

/** Translate a key for the current language, with `{name}` substitution.
 *  Unknown key → the key itself, loudly greppable rather than silently blank. */
export function translate(lang: Lang, key: string,
                          vars?: Record<string, string | number>): string {
  let out = STRINGS[key]?.[lang] ?? STRINGS[key]?.en ?? key
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      out = out.replaceAll(`{${name}}`, String(value))
    }
  }
  return out
}

/** The hook components use: `const t = useT()` … `t('op.start')`. */
export function useT() {
  const lang = useI18nStore((s) => s.lang)
  return (key: string, vars?: Record<string, string | number>) =>
    translate(lang, key, vars)
}
