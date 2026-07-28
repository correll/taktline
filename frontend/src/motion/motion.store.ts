import { create } from 'zustand'
import type { Card } from '../models'
import { useCardsStore } from '../store/cards.store'
import { prefersReducedMotion } from './motionCore'

/** Derives what *happened* from what changed.
 *
 *  The wire protocol only carries `card_update` and `card_delete` with the
 *  whole card in the payload — there is no "moved" or "merged" message. That
 *  is fine for state but says nothing about the transition, and a transition
 *  is exactly what an animation depicts. So this observer diffs each card's
 *  bins against the previous copy and names the change:
 *
 *    lost at A, gained at B   → a transit A→B
 *    gained, no previous copy → an appearance (origin genuinely unknown)
 *    several consumed at X,
 *      one new card at X      → a merge at X
 *    one consumed at X,
 *      several new elsewhere  → an unmerge
 *
 *  Everything published here is something the data actually says. Where the
 *  origin is unknown it is reported as unknown rather than guessed at, so the
 *  UI can fade in at the destination instead of drawing a path that never
 *  happened.
 */

export interface Transit {
  id:      string
  cardId:  string
  from:    string          // stationId
  to:      string          // stationId
  units:   number
  at:      number          // ms epoch when observed
}

export interface Convergence {
  id:            string
  kind:          'merge' | 'unmerge'
  stationId:     string   // merge: where it assembled. unmerge: where it dissolved.
  sourceCardIds: string[]
  newCardIds:    string[]
  at:            number
}

interface MotionState {
  transits:     Transit[]
  convergences: Convergence[]
  /** cardId → when it was first seen with no known previous position. */
  appearances:  Record<string, number>

  endTransit:     (id: string) => void
  endConvergence: (id: string) => void
  clearAppearance:(cardId: string) => void
  push: (t: { transits?: Transit[]; convergences?: Convergence[]; appearances?: string[] }) => void
}

export const useMotionStore = create<MotionState>()((set) => ({
  transits: [], convergences: [], appearances: {},

  endTransit: (id) => set((s) => ({ transits: s.transits.filter((t) => t.id !== id) })),
  endConvergence: (id) => set((s) => ({ convergences: s.convergences.filter((c) => c.id !== id) })),
  clearAppearance: (cardId) => set((s) => {
    if (!(cardId in s.appearances)) return s
    const next = { ...s.appearances }
    delete next[cardId]
    return { appearances: next }
  }),

  push: ({ transits = [], convergences = [], appearances = [] }) => set((s) => ({
    // Bounded: a burst from eight tablets must not grow an unbounded queue if
    // nothing is on screen to consume it.
    transits:     [...s.transits, ...transits].slice(-40),
    convergences: [...s.convergences, ...convergences].slice(-12),
    appearances:  appearances.length
      ? { ...s.appearances, ...Object.fromEntries(appearances.map((id) => [id, Date.now()])) }
      : s.appearances,
  })),
}))

// ── Observer ────────────────────────────────────────────────────────────────

/** Stations holding units of this card. */
function binsOf(card: Card): Map<string, number> {
  const m = new Map<string, number>()
  for (const [sid, bin] of Object.entries(card.bins ?? {})) {
    const n = (bin as { count?: number })?.count ?? 0
    if (n > 0) m.set(sid, n)
  }
  return m
}

type RawChange =
  | { kind: 'new';      cardId: string; at: Map<string, number> }
  | { kind: 'gone';     cardId: string; from: Map<string, number> }
  | { kind: 'moved';    cardId: string; lost: Map<string, number>; gained: Map<string, number> }

/** One WS flush (a merge, a split) emits several messages back to back. They
 *  have to be classified together or a merge reads as unrelated deletions. */
const BATCH_MS = 90
/** A reconnect refetch replaces every card at once. That is a resync, not
 *  movement, and animating it would fire a token for every lot on the line. */
const BULK_THRESHOLD = 25

let buffer: RawChange[] = []
let timer: ReturnType<typeof setTimeout> | null = null
let seq = 0
const uid = (p: string) => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`

function classify(batch: RawChange[]) {
  const transits: Transit[] = []
  const convergences: Convergence[] = []
  const appearances: string[] = []
  const now = Date.now()

  const fresh = batch.filter((c): c is Extract<RawChange, { kind: 'new' }> => c.kind === 'new')
  const gone  = batch.filter((c): c is Extract<RawChange, { kind: 'gone' }> => c.kind === 'gone')
  const moved = batch.filter((c): c is Extract<RawChange, { kind: 'moved' }> => c.kind === 'moved')

  // Units consumed at a station: a card that vanished there, or one that lost
  // units there without gaining any elsewhere. Both are what a merge looks like.
  const consumedAt = new Map<string, string[]>()
  for (const g of gone) {
    for (const sid of g.from.keys()) {
      consumedAt.set(sid, [...(consumedAt.get(sid) ?? []), g.cardId])
    }
  }
  for (const m of moved) {
    if (m.gained.size === 0) {
      for (const sid of m.lost.keys()) {
        consumedAt.set(sid, [...(consumedAt.get(sid) ?? []), m.cardId])
      }
    }
  }

  const usedFresh = new Set<string>()
  const usedConsumed = new Set<string>()

  // ── Merge: units consumed at X and a brand-new card standing at X.
  for (const [stationId, sourceIds] of consumedAt) {
    const born = fresh.filter((f) => !usedFresh.has(f.cardId) && f.at.has(stationId))
    if (born.length !== 1 || sourceIds.length < 1) continue
    // One consumed card and one new card at the same station is a relabel
    // (a split piece), not a convergence — a merge takes at least two feeds.
    if (sourceIds.length < 2) continue
    usedFresh.add(born[0].cardId)
    sourceIds.forEach((id) => usedConsumed.add(id))
    convergences.push({
      id: uid('mrg'), kind: 'merge', stationId,
      sourceCardIds: sourceIds, newCardIds: [born[0].cardId], at: now,
    })
  }

  // ── Unmerge: one card consumed at X, several new ones standing elsewhere.
  for (const [stationId, sourceIds] of consumedAt) {
    if (sourceIds.length !== 1 || usedConsumed.has(sourceIds[0])) continue
    const born = fresh.filter((f) => !usedFresh.has(f.cardId) && !f.at.has(stationId))
    if (born.length < 2) continue
    born.forEach((b) => usedFresh.add(b.cardId))
    usedConsumed.add(sourceIds[0])
    convergences.push({
      id: uid('unm'), kind: 'unmerge', stationId,
      sourceCardIds: sourceIds, newCardIds: born.map((b) => b.cardId), at: now,
    })
  }

  // ── Plain transits: a card that left one station and arrived at another.
  for (const m of moved) {
    if (m.gained.size === 0 || m.lost.size === 0) continue
    const from = [...m.lost.keys()]
    for (const [to, units] of m.gained) {
      // With one source the pairing is unambiguous. With several (a card
      // spread over stations losing units in more than one place) the nearest
      // honest statement is the single largest contributor.
      const src = from.length === 1
        ? from[0]
        : [...m.lost.entries()].sort((a, b) => b[1] - a[1])[0][0]
      if (src === to) continue
      transits.push({ id: uid('tr'), cardId: m.cardId, from: src, to, units, at: now })
    }
  }

  // ── Appearances: a card we had never seen, not accounted for by a merge.
  for (const f of fresh) {
    if (!usedFresh.has(f.cardId)) appearances.push(f.cardId)
  }

  return { transits, convergences, appearances }
}

function flush() {
  timer = null
  const batch = buffer
  buffer = []
  if (!batch.length) return
  if (batch.length > BULK_THRESHOLD) return          // resync, not movement
  const { transits, convergences, appearances } = classify(batch)
  if (transits.length || convergences.length || appearances.length) {
    useMotionStore.getState().push({ transits, convergences, appearances })
  }
}

/** Subscribe to the card store and publish transitions. Returns unsubscribe.
 *  Called once from the app shell, next to connectWS(). */
export function startMotionObserver(): () => void {
  let prevCards = useCardsStore.getState().cards
  /** Has the store ever held cards? Distinguishes the initial fetch — which
   *  has nothing to compare against — from the board legitimately emptying.
   *
   *  This was previously `prev is empty`, which is not the same thing and got
   *  it wrong exactly when it mattered: unmerging the last assembly on a line
   *  empties the store for one tick, so the first precursor recreated
   *  afterwards was absorbed as an "initial load" and the unmerge was seen as
   *  a single card appearing rather than several. */
  let primed = Object.keys(prevCards).length > 0

  return useCardsStore.subscribe((state) => {
    const next = state.cards
    const prev = prevCards
    prevCards = next
    if (prev === next) return
    if (!primed) {
      primed = Object.keys(next).length > 0
      return
    }
    if (prefersReducedMotion()) return

    for (const [id, card] of Object.entries(next)) {
      const before = prev[id]
      const nowBins = binsOf(card)
      if (!before) {
        buffer.push({ kind: 'new', cardId: id, at: nowBins })
        continue
      }
      const wasBins = binsOf(before)
      const lost = new Map<string, number>()
      const gained = new Map<string, number>()
      for (const [sid, n] of wasBins) {
        const now = nowBins.get(sid) ?? 0
        if (now < n) lost.set(sid, n - now)
      }
      for (const [sid, n] of nowBins) {
        const was = wasBins.get(sid) ?? 0
        if (n > was) gained.set(sid, n - was)
      }
      if (lost.size || gained.size) buffer.push({ kind: 'moved', cardId: id, lost, gained })
    }
    for (const [id, card] of Object.entries(prev)) {
      if (!(id in next)) buffer.push({ kind: 'gone', cardId: id, from: binsOf(card) })
    }

    if (buffer.length && timer === null) timer = setTimeout(flush, BATCH_MS)
  })
}
