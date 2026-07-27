// Conversion instrumentation.
//
// Vendor-agnostic on purpose: events go to Plausible when VITE_PLAUSIBLE_DOMAIN
// is set at build time (its script is injected below), and are otherwise a
// no-op — so the app never depends on an analytics provider being present, and
// nothing is sent from a self-hosted instance that didn't ask for it.
//
// The funnel we care about:
//   cta_click      — someone pressed a call to action (which one, and where)
//   sandbox_start  — a live line was actually opened (the low-friction path)
//   signup_started / signup_completed — the account path

type Props = Record<string, string | number | boolean>

declare global {
  interface Window {
    plausible?: (event: string, opts?: { props?: Props }) => void
  }
}

const DOMAIN = import.meta.env.VITE_PLAUSIBLE_DOMAIN as string | undefined

/** Load the analytics script once, if a domain was configured. */
export function initAnalytics(): void {
  if (!DOMAIN || typeof document === 'undefined') return
  if (document.querySelector('script[data-analytics]')) return
  const el = document.createElement('script')
  el.defer = true
  el.dataset.analytics = 'plausible'
  el.dataset.domain = DOMAIN
  el.src = 'https://plausible.io/js/script.js'
  document.head.appendChild(el)
}

export function track(event: string, props?: Props): void {
  try {
    window.plausible?.(event, props ? { props } : undefined)
    if (import.meta.env.DEV) console.debug('[analytics]', event, props ?? '')
  } catch {
    /* analytics must never break the app */
  }
}
