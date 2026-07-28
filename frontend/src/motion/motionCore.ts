/** Shared motion primitives: easing, timing, and the accessibility opt-out.
 *
 *  Everything animated in Taktline reports real state — a token on an edge
 *  means a lot actually moved that far, a pulse means a station has measured
 *  timing. Nothing here invents motion to look busy, and every effect has a
 *  still equivalent for anyone who has asked the OS for less of it.
 */

/** Cubic ease-in-out. Slow at both ends, quick through the middle — the shape
 *  physical objects move in, and the reason a linear tween reads as mechanical. */
export function easeInOut(t: number): number {
  const c = Math.min(1, Math.max(0, t))
  return c < 0.5 ? 4 * c * c * c : 1 - Math.pow(-2 * c + 2, 3) / 2
}

export function clamp(min: number, v: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

/** Travel time for a lot moving `metres` between two stations.
 *
 *  Logarithmic, not linear: a 40 m haul is meaningfully further than a 4 m one
 *  and should look it, but a 400 m one must not take ten seconds. The floor
 *  keeps short hops perceptible; the ceiling keeps a long one from feeling
 *  broken. This is the animation that makes transport distance legible, which
 *  is the evidence behind the transport-metres metric.
 */
export function travelDurationMs(metres: number): number {
  return clamp(400, 120 * Math.log2(1 + Math.max(0, metres)), 900)
}

/** Map units are metres or feet; the duration curve above is in metres. */
export function toMetres(value: number, unit: 'm' | 'ft'): number {
  return unit === 'ft' ? value * 0.3048 : value
}

// ── Reduced motion ──────────────────────────────────────────────────────────
// Read live rather than cached at import: the setting can change mid-session,
// and a wall display left running for a week should pick it up.

const REDUCED = '(prefers-reduced-motion: reduce)'

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia(REDUCED).matches
}

/** Subscribe to changes; returns an unsubscribe. */
export function onReducedMotionChange(fn: (reduced: boolean) => void): () => void {
  if (typeof window === 'undefined') return () => {}
  const mq = window.matchMedia(REDUCED)
  const h = (e: MediaQueryListEvent) => fn(e.matches)
  mq.addEventListener('change', h)
  return () => mq.removeEventListener('change', h)
}
