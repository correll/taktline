import { describe, expect, it } from 'vitest'
import { LEAN_TIPS, tipOfTheDay } from './leanTips'
import { disableTips, recordTipShown, shouldShowTip, type TipStore } from './tipSchedule'

/**
 * Tip of the day, reported broken twice.
 *
 * The first report ("the same tip two days ago") was a rotation that clustered
 * categories. The second ("I keep seeing the poka-yoke tip") looked like the
 * same bug and was not: the rotation was fine, and the tip was reappearing on
 * every page load because it only counted as *shown* once the user clicked a
 * dismiss control.
 *
 * Two failures wearing one symptom, so both layers are pinned separately —
 * otherwise the next report sends someone back to the rotation again.
 */

function memory(seed: Record<string, string> = {}): TipStore {
  const data = { ...seed }
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = v },
  }
}

describe('showing it once a day', () => {
  it('shows on a fresh browser', () => {
    expect(shouldShowTip(memory(), '2026-08-01')).toBe(true)
  })

  it('does NOT come back on the next page load once it has been shown', () => {
    // The regression. Nothing here dismisses anything — the user simply
    // reloads, which is what they do all day.
    const store = memory()
    expect(shouldShowTip(store, '2026-08-01')).toBe(true)
    recordTipShown(store, '2026-08-01')
    expect(shouldShowTip(store, '2026-08-01')).toBe(false)
    expect(shouldShowTip(store, '2026-08-01')).toBe(false)
  })

  it('comes back tomorrow', () => {
    const store = memory()
    recordTipShown(store, '2026-08-01')
    expect(shouldShowTip(store, '2026-08-02')).toBe(true)
  })

  it('stays away for good once switched off', () => {
    const store = memory()
    disableTips(store)
    expect(shouldShowTip(store, '2026-08-01')).toBe(false)
    expect(shouldShowTip(store, '2099-01-01')).toBe(false)
  })

  it('survives a browser that refuses storage', () => {
    // Private mode throws on access. A crashing help widget must not take the
    // app down with it.
    const hostile: TipStore = {
      getItem() { throw new Error('denied') },
      setItem() { throw new Error('denied') },
    }
    expect(() => shouldShowTip(hostile, '2026-08-01')).not.toThrow()
    expect(shouldShowTip(hostile, '2026-08-01')).toBe(false)
    expect(() => recordTipShown(hostile, '2026-08-01')).not.toThrow()
  })
})

describe('the rotation', () => {
  const day = (n: number) => new Date(Date.UTC(2026, 0, 1 + n))

  it('gives every tip exactly once before repeating', () => {
    const cycle = LEAN_TIPS.length
    const seen = new Set(Array.from({ length: cycle }, (_, d) => tipOfTheDay(day(d)).text))
    expect(seen.size).toBe(cycle)
  })

  it('repeats only after a full cycle', () => {
    expect(tipOfTheDay(day(0)).text).toBe(tipOfTheDay(day(LEAN_TIPS.length)).text)
  })

  it('never shows the same tip on consecutive days', () => {
    for (let d = 0; d < LEAN_TIPS.length * 2; d++) {
      expect(tipOfTheDay(day(d)).text).not.toBe(tipOfTheDay(day(d + 1)).text)
    }
  })

  it('keeps a category with two tips far apart', () => {
    // The original complaint: poka-yoke twice in a week. With 94 tips and two
    // in a category they belong roughly half a cycle apart, never in the same
    // fortnight.
    const positions = new Map<string, number[]>()
    for (let d = 0; d < LEAN_TIPS.length; d++) {
      const cat = tipOfTheDay(day(d)).category
      positions.set(cat, [...(positions.get(cat) ?? []), d])
    }
    const tight: string[] = []
    for (const [cat, days] of positions) {
      const count = LEAN_TIPS.filter((t) => t.category === cat).length
      if (count !== 2) continue
      const gap = days[1] - days[0]
      if (gap < 14) tight.push(`${cat}: ${gap} days apart`)
    }
    expect(tight).toEqual([])
  })

  it('is the same tip for everyone on a given day', () => {
    // The rotation is anchored to a fixed UTC epoch on purpose, so two people
    // in different offices are looking at the same thing.
    const a = tipOfTheDay(new Date('2026-08-01T00:30:00Z'))
    const b = tipOfTheDay(new Date('2026-08-01T23:30:00Z'))
    expect(a.text).toBe(b.text)
  })
})
