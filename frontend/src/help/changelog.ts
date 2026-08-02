/**
 * What changed, in the words of somebody who has to use it.
 *
 * Deliberately hand-written and checked in, rather than derived from a build
 * hash or a git log. Two reasons:
 *
 * **A deploy is not news.** Most deploys change nothing a user would notice — a
 * dependency bump, a test, a refactor. A popup that fires on every one teaches
 * people to dismiss it without reading, which costs exactly the attention it
 * exists to spend on the deploy that *does* matter.
 *
 * **Commit messages are written for the next engineer.** "Derive entitlement
 * rather than storing it" is the right message and the wrong sentence to show a
 * foreman. Every line here says what someone can now do, or what stopped being
 * broken.
 *
 * Newest first. `id` is what gets stored as "seen", so it must never be reused;
 * a date is fine and reads better than a version number nobody increments.
 */

export interface Release {
  id: string
  date: string
  headline: string
  added?: string[]
  fixed?: string[]
}

export const RELEASES: Release[] = [
  {
    id: '2026-08-03',
    date: '3 August 2026',
    headline: 'See your suppliers, and let your customers see you',
    added: [
      'Paste a supplier’s tracking link onto a lot or a goods-in station and ' +
      'their progress shows up on your board — no phone call, no “any update?” ' +
      'email. Settings → Integrations invites a supplier to send you one.',
      'Every lot now carries a printable QR code beside its customer link. One ' +
      'sticker on the bin: a customer scanning it sees that job’s progress, and ' +
      'an operator signed in to Taktline lands straight on the bench.',
    ],
  },
  {
    id: '2026-08-02',
    date: '2 August 2026',
    headline: 'Customer order tracking, plans, and a place for orders',
    added: [
      'Send a customer a link that shows their own job moving down your line — ' +
      'no login, and they see nothing but that one job. Switch it on in ' +
      'Settings → Global; copy a link from any lot or order.',
      'Orders and the completion outbox moved out of Settings and onto the Lots ' +
      'board, beside the work they released.',
      'Plans and billing: Settings → Billing shows what you are on, what you are ' +
      'using, and what else there is. Changes are pro-rated to the day.',
      'The manual’s improvement toolkit — 5S, SMED, poka-yoke and the rest — ' +
      'now has a share button on every section, like the flow-science chapters.',
      'Platform staff: type-to-filter on companies and users, and MRR beside ' +
      'each account.',
    ],
    fixed: [
      'A line file could import more stations than a plan allowed.',
      'The floor plan of a deleted account stayed readable on disk.',
      'A paused account was told its connection had been lost, rather than that ' +
      'it was paused.',
      'Creating a station on the map could fail silently, doing nothing at all.',
    ],
  },
]

export const LATEST = RELEASES[0]?.id ?? ''

export const SEEN_KEY = 'taktline.lastSeenRelease'

/**
 * Which releases to show, given what this browser has already seen.
 *
 * A browser with nothing stored gets **nothing** and is marked up to date: the
 * first thing a new account should meet is the product, not a list of things
 * that changed before they arrived.
 */
export function unseen(stored: string | null): Release[] {
  if (!stored) return []
  if (stored === LATEST) return []
  const index = RELEASES.findIndex((r) => r.id === stored)
  // An unrecognised value (an older build, a hand-edited key) shows only the
  // newest entry rather than the entire history.
  return index === -1 ? RELEASES.slice(0, 1) : RELEASES.slice(0, index)
}
