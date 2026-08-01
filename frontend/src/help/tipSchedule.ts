/**
 * When the daily tip should appear, and when it has been seen.
 *
 * A module of its own, with no React and no store, for two reasons. It is the
 * part that was wrong twice and therefore the part worth testing directly; and
 * importing the component to test it drags in the help store, which reads
 * `localStorage` at module load and so cannot be imported outside a browser at
 * all.
 */

export const LAST_KEY = 'taktline.tip.lastShown'   // YYYY-MM-DD of the last shown tip
export const OFF_KEY = 'taktline.tip.disabled'     // '1' → user opted out of daily tips

/** The rotation rolls over at UTC midnight, so this key must too — otherwise
 *  "already shown today" and "today's tip" would disagree for part of the day
 *  and the tip would either repeat or be skipped. */
export const todayKey = (now: Date = new Date()) => now.toISOString().slice(0, 10)

/** Just enough of localStorage to be substitutable in a test. */
export interface TipStore {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function shouldShowTip(store: TipStore, today: string): boolean {
  try {
    if (store.getItem(OFF_KEY) === '1') return false
    return store.getItem(LAST_KEY) !== today
  } catch { return false }          // private mode: no tip beats a crash
}

/**
 * Remember that today's tip has been seen.
 *
 * Called when the tip is *shown*, not when it is dismissed. It used to be
 * written only inside `dismiss()`, so a tip counted as seen only if the user
 * clicked one of the three dismiss controls — reload the page, navigate away,
 * or close the tab without clicking, and the very same tip came back, all day
 * long. That is what "I keep seeing the poka-yoke tip" was: not a rotation
 * fault (the rotation runs 94 distinct tips before repeating), but a tip of
 * the *day* behaving like a tip of the *page load*.
 */
export function recordTipShown(store: TipStore, today: string): void {
  try { store.setItem(LAST_KEY, today) } catch { /* private mode */ }
}

export function disableTips(store: TipStore): void {
  try { store.setItem(OFF_KEY, '1') } catch { /* private mode */ }
}
