import { useLayoutEffect, useRef } from 'react'
import { prefersReducedMotion } from './motionCore'
import { useMotionStore } from './motion.store'

/** FLIP for the Kanban board.
 *
 *  Measure every lot card before the update, measure again after, and play the
 *  difference backwards so the card appears to travel from the column it was
 *  in to the column it is now in. The board is the one surface where a move is
 *  otherwise invisible: a card silently vanishes from one column and appears
 *  in another, and on a wall display nobody sees which.
 *
 *  Three cases, deliberately distinguished:
 *
 *  - **Moved between columns** — a clone flies across. A plain transform would
 *    be clipped: each column is its own `overflow-y: auto` scroller, so a card
 *    translated toward its old column disappears at the column edge and the
 *    travel — the whole point — is lost.
 *  - **Reordered inside a column** — a plain transform. No clipping to dodge,
 *    and no clone means no chance of a stale copy on screen.
 *  - **Previous position unknown** — the client learned about this lot after
 *    the fact (it just connected, or another tablet created it). There is no
 *    honest path to draw, so it fades in where it is rather than sliding in
 *    from a column it was never in.
 */

const FLIP_MS  = 180
const FADE_MS  = 150
const EASE     = 'cubic-bezier(0.4, 0, 0.2, 1)'

// Merge convergence — the animated sequence stays under 600ms (450 + 120).
const MERGE_TRAVEL_MS = 450
const MERGE_SHRINK_MS = 150     // the tail of the travel, not extra time
const BIRTH_MS        = 120

/** How long to wait before deciding what a newly-appeared card *is*.
 *
 *  A merge arrives as several WebSocket messages — precursors deleted, an
 *  assembly created — and the observer needs a moment to see them as one
 *  event (motion.store BATCH_MS). React, meanwhile, re-renders the board on
 *  the first message. So at layout time "a new card appeared" is genuinely
 *  ambiguous: it could be an assembly whose precursors are still arriving.
 *  Deciding immediately means every merge looks like a plain fade-in.
 *
 *  So a new card is held invisible for slightly longer than the classification
 *  window and then does the right thing. The cost is ~130ms of latency on a
 *  card appearing; the alternative is being wrong about what happened. */
const SETTLE_MS = 130
/** Removed cards keep their last rect this long, so a merge classified after
 *  the fact still knows where its precursors were standing. */
const GRAVE_MS  = 1500

let overlayEl: HTMLElement | null = null
function overlay(): HTMLElement {
  if (overlayEl?.isConnected) return overlayEl
  overlayEl = document.createElement('div')
  overlayEl.setAttribute('data-lot-flight-layer', '')
  Object.assign(overlayEl.style, {
    position: 'fixed', inset: '0', pointerEvents: 'none', zIndex: '9000',
    overflow: 'hidden',
  } as Partial<CSSStyleDeclaration>)
  document.body.appendChild(overlayEl)
  return overlayEl
}

type Snap = { rect: DOMRect; col: string | null }

function cloneAt(el: HTMLElement, rect: DOMRect): HTMLElement {
  const clone = el.cloneNode(true) as HTMLElement
  Object.assign(clone.style, {
    position: 'fixed', left: `${rect.left}px`, top: `${rect.top}px`,
    width: `${rect.width}px`, height: `${rect.height}px`,
    margin: '0', pointerEvents: 'none', boxSizing: 'border-box',
  } as Partial<CSSStyleDeclaration>)
  overlay().appendChild(clone)
  return clone
}

/** @param rootRef the board's root element
 *
 *  Deliberately runs after *every* render rather than on a dependency list.
 *  Card position depends on the cards, the filters, the sort, the split mode
 *  and the column widths; any dep list that tried to capture that would miss a
 *  case and drop the animation. Measuring is cheap — the board already caps
 *  how many cards a column shows — and when nothing moved, nothing animates. */
export function useLotFlip(rootRef: React.RefObject<HTMLElement | null>) {
  const prev  = useRef<Map<string, Snap>>(new Map())
  const first = useRef(true)
  /** Where cards were standing just before they left the DOM. */
  const grave = useRef<Map<string, Snap & { at: number }>>(new Map())
  /** New cards waiting to find out whether they are an assembly or just new. */
  const settling = useRef<Set<string>>(new Set())

  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return

    const els  = Array.from(root.querySelectorAll<HTMLElement>('[data-lot-id]'))
    const next = new Map<string, Snap>()
    for (const el of els) {
      const id = el.dataset.lotId
      if (!id) continue
      next.set(id, {
        rect: el.getBoundingClientRect(),
        col:  el.closest<HTMLElement>('[data-lot-column]')?.dataset.lotColumn ?? null,
      })
    }

    const reduced = prefersReducedMotion()
    // Record on the first pass and then stop: without this every card on the
    // board fades in on mount, which reads as a page that failed to settle.
    if (first.current || reduced) {
      prev.current = next
      first.current = false
      return
    }

    // Cards that left the DOM keep their last position for a moment: a merge
    // is only recognised as one after the classification window, by which
    // point its precursors are long gone from the DOM.
    const now = performance.now()
    for (const id of prev.current.keys()) {
      if (!next.has(id)) grave.current.set(id, { ...prev.current.get(id)!, at: now })
    }
    for (const [id, g] of grave.current) {
      if (now - g.at > GRAVE_MS) grave.current.delete(id)
    }

    for (const [id, snap] of next) {
      const el = root.querySelector<HTMLElement>(`[data-lot-id="${CSS.escape(id)}"]`)
      if (!el || snap.rect.width === 0) continue
      const before = prev.current.get(id)

      if (!before) {
        // Hold it invisible until we know what it is — see SETTLE_MS.
        if (!settling.current.has(id)) {
          settling.current.add(id)
          el.style.opacity = '0'
          setTimeout(() => settle(id, root, grave.current, settling.current), SETTLE_MS)
        }
        continue
      }

      const dx = before.rect.left - snap.rect.left
      const dy = before.rect.top  - snap.rect.top
      if (Math.abs(dx) < 1.5 && Math.abs(dy) < 1.5) continue

      if (before.col !== snap.col) {
        // Across columns: fly a clone over the top of both scrollers.
        const clone = cloneAt(el, before.rect)
        el.style.visibility = 'hidden'
        const anim = clone.animate(
          [{ transform: 'translate(0px, 0px)' },
           { transform: `translate(${snap.rect.left - before.rect.left}px, ${snap.rect.top - before.rect.top}px)` }],
          { duration: FLIP_MS, easing: EASE, fill: 'forwards' },
        )
        anim.finished.catch(() => {}).finally(() => {
          clone.remove()
          el.style.visibility = ''
        })
      } else {
        el.animate(
          [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'translate(0px, 0px)' }],
          { duration: FLIP_MS, easing: EASE },
        )
      }
    }

    prev.current = next
  })
}

/** Decide what a newly-appeared card is, now that the observer has had time
 *  to classify the batch it arrived in. */
function settle(
  id: string,
  root: HTMLElement,
  grave: Map<string, Snap & { at: number }>,
  settling: Set<string>,
) {
  settling.delete(id)
  const el = root.querySelector<HTMLElement>(`[data-lot-id="${CSS.escape(id)}"]`)
  if (!el) return
  el.style.opacity = ''

  const merge = useMotionStore.getState().convergences
    .find((c) => c.kind === 'merge' && c.newCardIds.includes(id))

  if (!merge) {
    // Origin genuinely unknown — no path to draw, so arrive where you are.
    el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FADE_MS, easing: 'ease-out' })
    return
  }

  const to = el.getBoundingClientRect()

  // Precursors converge on the assembly and shrink out of existence. Their
  // elements are already unmounted, so a plain card-shaped clone stands in.
  const shrinkAt = 1 - MERGE_SHRINK_MS / MERGE_TRAVEL_MS
  for (const src of merge.sourceCardIds) {
    const from = grave.get(src)
    if (!from || from.rect.width === 0) continue
    const clone = cloneAt(document.createElement('div'), from.rect)
    clone.style.background   = 'var(--tk-bg-card)'
    clone.style.border       = '1px solid var(--tk-border)'
    clone.style.borderRadius = '6px'
    const dx = to.left - from.rect.left
    const dy = to.top  - from.rect.top
    const anim = clone.animate(
      [
        { transform: 'translate(0px, 0px) scale(1)', opacity: 0.9, offset: 0 },
        { transform: `translate(${dx * shrinkAt}px, ${dy * shrinkAt}px) scale(1)`,
          opacity: 0.9, offset: shrinkAt },
        { transform: `translate(${dx}px, ${dy}px) scale(0)`, opacity: 0, offset: 1 },
      ],
      { duration: MERGE_TRAVEL_MS, easing: EASE, fill: 'forwards' },
    )
    anim.finished.catch(() => {}).finally(() => clone.remove())
  }

  // The assembly grows into place only once they have arrived, so cause
  // visibly precedes effect.
  el.animate(
    [{ opacity: 0, transform: 'scale(0.9)' }, { opacity: 1, transform: 'scale(1)' }],
    { duration: BIRTH_MS, delay: MERGE_TRAVEL_MS, easing: EASE, fill: 'backwards' },
  )
}
