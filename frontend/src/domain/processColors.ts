/** A colour per process, so two value streams over one floor are tellable apart.
 *
 *  ── Why only three ────────────────────────────────────────────────────────
 *  Most of the spectrum is already spoken for and must not be borrowed: coral
 *  is the brand and every primary action, green/amber/red are andon status, and
 *  the violet ramp is the WIP heatmap. What is left is blue, brown, pink and
 *  the blue-greens — and blue-green sits too close to blue to survive either
 *  colour-vision deficiency or, at these lightnesses, ordinary vision.
 *
 *  Rather than ship four colours where two are a coin-flip, this is three that
 *  pass every check with room to spare, validated all-pairs (a process takes an
 *  arbitrary slot, so any two can end up adjacent on a map) against each
 *  theme's own surface:
 *
 *      day    worst pair ΔE 10.2 deutan · 16.7 normal · all ≥3:1 contrast
 *      night  worst pair ΔE 12.2 deutan · 19.9 normal · all ≥3:1 contrast
 *
 *  Beyond three the palette repeats, which is why the map carries a **legend**
 *  naming each process beside its colour: identity never rests on hue alone,
 *  and a fourth line is told apart by its name and by where its routes run.
 */

export const PROCESS_COLORS: Record<'night' | 'day', readonly string[]> = {
  //        blue       brown      pink
  day:   ['#1D4ED8', '#B45309', '#DB2777'],
  night: ['#3B82F6', '#C97B30', '#EC4899'],
}

/** Stable slot for a process id.
 *
 *  Hashed rather than taken from list order: a process keeps its colour when
 *  another is created or deleted, so the map does not silently re-colour a line
 *  someone has learned to recognise.
 */
export function processColorIndex(processId: string): number {
  let h = 0
  for (let i = 0; i < processId.length; i++) h = (h * 31 + processId.charCodeAt(i)) | 0
  return Math.abs(h) % PROCESS_COLORS.day.length
}

export function processColor(processId: string, mode: 'night' | 'day'): string {
  return PROCESS_COLORS[mode][processColorIndex(processId)]
}

/** Pixi needs numeric colours. */
export function processColorInt(processId: string, mode: 'night' | 'day'): number {
  return parseInt(processColor(processId, mode).slice(1), 16)
}
