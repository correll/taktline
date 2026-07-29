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

/** Preferred slot for a process id — hashed, so it does not depend on how many
 *  processes exist or what order they were made in. */
function preferredSlot(processId: string): number {
  let h = 0
  for (let i = 0; i < processId.length; i++) h = (h * 31 + processId.charCodeAt(i)) | 0
  return Math.abs(h) % PROCESS_COLORS.day.length
}

/** Colours for a whole set of processes, guaranteed distinct while the palette
 *  lasts.
 *
 *  Hashing alone is not enough: with three slots, two processes land on the
 *  same colour one time in three, and two lines drawn in one colour defeats the
 *  entire point. So each process takes its hashed slot when free, and otherwise
 *  the next free one — which keeps colours stable for everyone whose preference
 *  was uncontested, and only moves the process that actually collided.
 *
 *  Past three processes the palette necessarily repeats; the map's legend names
 *  every line, so identity never rests on hue alone.
 */
export function processColorSlots(processIds: string[]): Record<string, number> {
  const n = PROCESS_COLORS.day.length
  const ordered = [...processIds].sort()          // stable regardless of fetch order
  const taken = new Set<number>()
  const slots: Record<string, number> = {}

  for (const id of ordered) {                     // uncontested preferences first
    const pref = preferredSlot(id)
    if (!taken.has(pref)) { taken.add(pref); slots[id] = pref }
  }
  for (const id of ordered) {                     // then the collisions, in order
    if (id in slots) continue
    let s = preferredSlot(id)
    for (let i = 0; i < n && taken.has(s); i++) s = (s + 1) % n
    taken.add(s)
    slots[id] = s
  }
  return slots
}

export function processColorsFor(
  processIds: string[], mode: 'night' | 'day',
): Record<string, string> {
  const slots = processColorSlots(processIds)
  const out: Record<string, string> = {}
  for (const [id, slot] of Object.entries(slots)) out[id] = PROCESS_COLORS[mode][slot]
  return out
}

/** Pixi needs numeric colours. */
export function hexToInt(hex: string): number {
  return parseInt(hex.slice(1), 16)
}
