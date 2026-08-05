import { describe, expect, it } from 'vitest'
import { LATEST, RELEASES, unseen } from './changelog'

/**
 * The show-once rule.
 *
 * This codebase has already shipped one bug of exactly this shape — the daily
 * tip reappeared on every page load because it only counted as seen once the
 * user clicked a dismiss control. A modal over the board has the same failure
 * mode and a worse feel, so the rule gets pinned rather than assumed.
 */
describe('what to show', () => {
  it('shows nothing to a browser that has seen the latest', () => {
    expect(unseen(LATEST)).toEqual([])
  })

  it('shows nothing on a first visit', () => {
    // A new account should meet the product, not a list of things that changed
    // before they arrived.
    expect(unseen(null)).toEqual([])
  })

  it('shows everything since the release they last saw', () => {
    const older = RELEASES[RELEASES.length - 1].id
    const shown = unseen(older)
    expect(shown.map((r) => r.id)).toEqual(
      RELEASES.slice(0, RELEASES.length - 1).map((r) => r.id))
    expect(shown).not.toContainEqual(RELEASES[RELEASES.length - 1])
  })

  it('shows only the newest for an unrecognised marker', () => {
    // An older build, or a hand-edited key. Replaying the entire history at
    // somebody is worse than showing them the one thing that is current.
    expect(unseen('not-a-release').map((r) => r.id)).toEqual([LATEST])
  })
})

describe('the changelog itself', () => {
  it('is newest first', () => {
    const ids = RELEASES.map((r) => r.id)
    expect([...ids].sort().reverse()).toEqual(ids)
  })

  it('has unique ids', () => {
    // An id is stored as "seen"; reusing one silently hides a release.
    expect(new Set(RELEASES.map((r) => r.id)).size).toBe(RELEASES.length)
  })

  it('says something in every entry', () => {
    for (const r of RELEASES) {
      expect(r.headline.length, r.id).toBeGreaterThan(10)
      expect((r.added?.length ?? 0) + (r.fixed?.length ?? 0), r.id).toBeGreaterThan(0)
    }
  })
})
