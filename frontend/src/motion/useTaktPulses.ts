import { useEffect, useState } from 'react'
import { sessionsApi } from '../api/sessions.api'
import { computeTaktPulses, EMPTY_PULSES, type TaktPulses } from './takt'
import { prefersReducedMotion, onReducedMotionChange } from './motionCore'

/** Measured takt per station, refreshed slowly.
 *
 *  Takt is an average over completed work sessions; it moves on the scale of a
 *  shift, not a second. Polling it faster would cost a query per client per
 *  interval for a number that has not changed — and this runs on wall displays
 *  that stay open for days.
 */
const REFRESH_MS = 90_000

export function useTaktPulses(enabled = true): TaktPulses {
  const [pulses, setPulses] = useState<TaktPulses>(EMPTY_PULSES)
  const [reduced, setReduced] = useState(prefersReducedMotion)

  useEffect(() => onReducedMotionChange(setReduced), [])

  useEffect(() => {
    if (!enabled || reduced) { setPulses(EMPTY_PULSES); return }
    let alive = true
    const load = async () => {
      try {
        const stats = await sessionsApi.allStats()
        if (alive) setPulses(computeTaktPulses(stats))
      } catch {
        // A failed poll leaves the last good rhythm on screen. Dropping to
        // "no data" on one bad request would stop the whole wall display.
      }
    }
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => { alive = false; clearInterval(t) }
  }, [enabled, reduced])

  return reduced ? EMPTY_PULSES : pulses
}
