/** The languages the product speaks — mirrors `backend/app/core/languages.py`,
 *  and `i18n.test.ts` fails if the two drift. Codes are BCP 47; names are
 *  endonyms, because a picker that says "Burmese" to someone looking for
 *  မြန်မာ has failed at its one job. */

export type Lang = 'en' | 'es' | 'fr-CA' | 'my' | 'ht'

export const LANGUAGES: Record<Lang, string> = {
  en: 'English',
  es: 'Español',
  'fr-CA': 'Français (Canada)',
  my: 'မြန်မာ',
  ht: 'Kreyòl ayisyen',
}

export const DEFAULT_LANGUAGE: Lang = 'en'

export const LANGUAGE_CODES = Object.keys(LANGUAGES) as Lang[]

export function isLang(v: unknown): v is Lang {
  return typeof v === 'string' && v in LANGUAGES
}

/** Best match for the browser's language, for the signup form's default. */
export function browserLanguage(): Lang {
  const wanted = (typeof navigator !== 'undefined' ? navigator.languages ?? [] : [])
  for (const raw of wanted) {
    if (isLang(raw)) return raw
    const base = raw.split('-')[0]
    if (base === 'fr') return 'fr-CA'
    if (isLang(base)) return base
  }
  return DEFAULT_LANGUAGE
}
