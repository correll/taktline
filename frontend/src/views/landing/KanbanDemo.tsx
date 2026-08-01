import { useEffect, useState } from 'react'
import { color, font, shadow, size } from '../../theme/tokens'

/**
 * The lots board, doing the thing a task board cannot.
 *
 * Every kanban tool on the market moves a card from one column to the next, so
 * showing that alone says nothing. What distinguishes a manufacturing board is
 * that a card is attached to *material*: it carries a count, several cards get
 * consumed to make one, and one card becomes several. So the loop here is
 * deliberately not "card moves right" — it is a **merge**: two precursor lots
 * are consumed at the bench and a finished pack is minted in their place, with
 * the counts on the column headers changing to match.
 *
 * Positions come from (column, row) held in state, and every card is absolutely
 * placed, so React only ever changes the numbers and CSS does the travel. That
 * is much less machinery than the board's real FLIP animation needs, because
 * here there is no scroller to escape from.
 */

type Card = { id: string; code: string; units: number; tint: string; col: number; row: number }

const COLUMNS = ['Teardown', 'Module Test', 'Busbar Clean', 'Reassembly', 'Pack Test']

// The LFP recipe, matching the hero animation on the same page: a pack tears
// down into 4 modules and 16 busbars. Two figures on one page disagreeing about
// the same line is the kind of detail a manufacturing buyer notices first.

// Where each step leaves the board. Written out rather than computed so the
// sequence reads as what a shift actually does.
const START: Card[] = [
  { id: 'a', code: 'LFP-0042', units: 1, tint: '#F59E0B', col: 0, row: 0 },
  { id: 'b', code: 'LFP-0041', units: 4, tint: '#3B82F6', col: 1, row: 0 },
  { id: 'c', code: 'LFP-0041', units: 16, tint: '#10B981', col: 2, row: 0 },
  { id: 'd', code: 'NMC-0088', units: 1, tint: '#8B5CF6', col: 0, row: 1 },
]

type Step = { cards: Card[]; note: string; dwell: number }

const SEQUENCE: Step[] = [
  { cards: START, note: 'A pack waiting to be torn down', dwell: 1600 },
  {
    // The teardown fans out: one pack becomes modules and busbars at once.
    cards: [
      { id: 'b', code: 'LFP-0041', units: 4, tint: '#3B82F6', col: 1, row: 0 },
      { id: 'c', code: 'LFP-0041', units: 16, tint: '#10B981', col: 2, row: 0 },
      { id: 'a1', code: 'LFP-0042', units: 4, tint: '#3B82F6', col: 1, row: 1 },
      { id: 'a2', code: 'LFP-0042', units: 16, tint: '#10B981', col: 2, row: 1 },
      { id: 'd', code: 'NMC-0088', units: 1, tint: '#8B5CF6', col: 0, row: 0 },
    ],
    note: 'The pack’s card is retired; a new card lands on each branch',
    dwell: 2400,
  },
  {
    // Both precursors arrive at the bench that consumes them.
    cards: [
      { id: 'b', code: 'LFP-0041', units: 4, tint: '#3B82F6', col: 3, row: 0 },
      { id: 'c', code: 'LFP-0041', units: 16, tint: '#10B981', col: 3, row: 1 },
      { id: 'a1', code: 'LFP-0042', units: 4, tint: '#3B82F6', col: 1, row: 0 },
      { id: 'a2', code: 'LFP-0042', units: 16, tint: '#10B981', col: 2, row: 0 },
      { id: 'd', code: 'NMC-0088', units: 1, tint: '#8B5CF6', col: 0, row: 0 },
    ],
    note: 'Modules and busbars carried to the bench that assembles them',
    dwell: 2200,
  },
  {
    // The merge: both precursors are gone, one assembly exists.
    cards: [
      { id: 'pack', code: 'LFP-0041', units: 1, tint: '#D85A30', col: 3, row: 0 },
      { id: 'a1', code: 'LFP-0042', units: 4, tint: '#3B82F6', col: 1, row: 0 },
      { id: 'a2', code: 'LFP-0042', units: 16, tint: '#10B981', col: 2, row: 0 },
      { id: 'd', code: 'NMC-0088', units: 1, tint: '#8B5CF6', col: 0, row: 0 },
    ],
    note: 'Both cards consumed, one pack card born — the board knows the recipe',
    dwell: 2600,
  },
  {
    cards: [
      { id: 'pack', code: 'LFP-0041', units: 1, tint: '#D85A30', col: 4, row: 0 },
      { id: 'a1', code: 'LFP-0042', units: 4, tint: '#3B82F6', col: 3, row: 0 },
      { id: 'a2', code: 'LFP-0042', units: 16, tint: '#10B981', col: 3, row: 1 },
      { id: 'd', code: 'NMC-0088', units: 1, tint: '#8B5CF6', col: 1, row: 0 },
    ],
    note: 'Finished pack to test; the next one is already moving',
    dwell: 2400,
  },
]

const COL_W = 128
const COL_GAP = 8
const HEAD_H = 30
const CARD_H = 44
const CARD_GAP = 6

export default function KanbanDemo() {
  const [i, setI] = useState(0)
  const [still, setStill] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const apply = () => setStill(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    if (still) return
    const t = setTimeout(() => setI((n) => (n + 1) % SEQUENCE.length), SEQUENCE[i].dwell)
    return () => clearTimeout(t)
  }, [i, still])

  // At rest, show the merge: it is the frame that carries the argument.
  const step = SEQUENCE[still ? 3 : i]
  const counts = COLUMNS.map((_, c) => step.cards.filter((k) => k.col === c).length)

  return (
    <div>
      <div style={{
        border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
        background: color.bgPanel, boxShadow: shadow.lg, overflow: 'hidden',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px',
          borderBottom: `1px solid ${color.border}`,
        }}>
          {[0, 1, 2].map((n) => (
            <span key={n} style={{ width: 10, height: 10, borderRadius: '50%', background: color.border }} />
          ))}
          <span style={{ marginLeft: 'auto', fontSize: 11, fontFamily: font.mono, color: color.textDim }}>
            lots board · battery remanufacturing
          </span>
        </div>

        {/* Wide content scrolls inside its own box rather than the page. */}
        <div style={{ overflowX: 'auto', padding: size.sp5, background: color.bgDeep }}>
          <div aria-hidden="true" style={{
            position: 'relative',
            width: COLUMNS.length * COL_W + (COLUMNS.length - 1) * COL_GAP,
            height: HEAD_H + 3 * (CARD_H + CARD_GAP) + 8,
            margin: '0 auto',
          }}>
            {COLUMNS.map((name, c) => (
              <div key={name} style={{
                position: 'absolute', left: c * (COL_W + COL_GAP), top: 0,
                width: COL_W, height: '100%',
                background: color.bgPanel, borderRadius: size.radius,
                border: `1px solid ${color.border}`,
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '7px 8px', borderBottom: `1px solid ${color.border}`,
                }}>
                  <span style={{
                    fontSize: 10, fontFamily: font.mono, color: color.textSecondary,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>
                    {name}
                  </span>
                  <span style={{
                    fontSize: 10, fontFamily: font.mono, minWidth: 14, textAlign: 'right',
                    color: counts[c] ? color.textPrimary : color.textDisabled,
                    transition: 'color 260ms ease',
                  }}>
                    {counts[c]}
                  </span>
                </div>
              </div>
            ))}

            {step.cards.map((k) => (
              <div key={k.id} style={{
                position: 'absolute',
                left: k.col * (COL_W + COL_GAP) + 6,
                top: HEAD_H + 8 + k.row * (CARD_H + CARD_GAP),
                width: COL_W - 12, height: CARD_H,
                background: color.bgCard, borderRadius: size.radius,
                border: `1px solid ${color.border}`, borderLeft: `3px solid ${k.tint}`,
                padding: '6px 8px', boxSizing: 'border-box',
                // Position is a transition, so a card that changes column
                // travels there. A card that appears (the merge's output) or
                // disappears (its inputs) simply is or is not — which is also
                // what happens to the physical card on the bench.
                transition: 'left 620ms cubic-bezier(.2,.7,.3,1), top 380ms ease',
                animation: 'tk-kanban-in 300ms ease',
              }}>
                <div style={{ fontSize: 10, fontFamily: font.mono, color: color.textPrimary }}>
                  {k.code}
                </div>
                <div style={{ fontSize: 9, color: color.textDim, marginTop: 3 }}>
                  {k.units} {k.units === 1 ? 'unit' : 'units'}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{
          padding: '10px 14px', borderTop: `1px solid ${color.border}`,
          fontSize: 12, color: color.textSecondary, textAlign: 'center', minHeight: 20,
        }}>
          {step.note}
        </div>
      </div>

      <style>{`
        @keyframes tk-kanban-in {
          from { opacity: 0; transform: scale(0.94); }
          to   { opacity: 1; transform: scale(1); }
        }
        @media (prefers-reduced-motion: reduce) {
          @keyframes tk-kanban-in { from { opacity: 1 } to { opacity: 1 } }
        }
      `}</style>
    </div>
  )
}
