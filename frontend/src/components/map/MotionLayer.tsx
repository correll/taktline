import React, { useEffect, useRef } from 'react'
import { Graphics, useTick } from '@pixi/react'
import * as PIXI from 'pixi.js'
import type { Route, Station } from '../../models'
import { useCardsStore, useProcessesStore } from '../../store'
import { useMotionStore } from '../../motion/motion.store'
import { easeInOut, travelDurationMs, toMetres } from '../../motion/motionCore'

/** Lots in transit, drawn on the map.
 *
 *  A token runs the actual route edge from the station a lot left to the one
 *  it reached, over a duration set by how far that is on the real floor plan.
 *  That is the point: a 40 m haul visibly takes longer than a 4 m one, so the
 *  transport-metres figure in Statistics stops being an abstract number and
 *  becomes something anyone watching the board has already seen happen. It is
 *  also the cheapest way to make the case for moving two stations closer
 *  together, or for an AMR.
 *
 *  The token wears the lot's own colour, not the brand colour. Coral is the
 *  primary-action colour everywhere else in the product; a coral dot crossing
 *  the map would read as the app doing something rather than as *this lot*
 *  going somewhere.
 */

const TOKEN_R      = 6          // world px at scale 1
const MERGE_MS     = 450        // convergence travel — keeps the sequence under 600ms
const SHRINK_MS    = 150        // ...of which this much is the token shrinking away
const FALLBACK_COL = 0x3b82f6   // theme lotBlue, for a lot with no template colour

function hexToInt(hex: string | null | undefined): number {
  if (!hex) return FALLBACK_COL
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  return m ? parseInt(m[1], 16) : FALLBACK_COL
}

interface Token {
  id:        string          // owning transit/convergence id
  key:       string
  x0: number; y0: number
  x1: number; y1: number
  start:     number
  duration:  number
  color:     number
  /** ms at the tail over which the token shrinks to nothing (merge). */
  shrinkTail: number
  /** ms at the head over which it grows from nothing (unmerge). */
  growHead:   number
}

interface Props {
  stations:      Record<string, Station>
  routes:        Record<string, Route>
  nodeSize:      number
  pixelsPerUnit: number
  unit:          'm' | 'ft'
}

export default function MotionLayer({ stations, routes, nodeSize, pixelsPerUnit, unit }: Props) {
  const gRef = useRef<PIXI.Graphics>(null)
  const live = useRef<Token[]>([])

  const transits       = useMotionStore((s) => s.transits)
  const convergences   = useMotionStore((s) => s.convergences)
  const endTransit     = useMotionStore((s) => s.endTransit)
  const endConvergence = useMotionStore((s) => s.endConvergence)
  const cards      = useCardsStore((s) => s.cards)
  const templates  = useProcessesStore((s) => s.lotTemplates)

  const half = nodeSize / 2
  const centre = (s: Station) => ({ x: s.position.x + half, y: s.position.y + half })
  const lotColour = (cardId: string) =>
    hexToInt(templates[cards[cardId]?.lotTemplateId ?? '']?.color)

  // ── Register transits ─────────────────────────────────────────────────────
  useEffect(() => {
    for (const t of transits) {
      if (live.current.some((k) => k.id === t.id)) continue
      const a = stations[t.from], b = stations[t.to]
      if (!a || !b) { endTransit(t.id); continue }          // station not on this map
      const p0 = centre(a), p1 = centre(b)
      const px = Math.hypot(p1.x - p0.x, p1.y - p0.y)
      const metres = toMetres(px / (pixelsPerUnit || 1), unit)
      live.current.push({
        id: t.id, key: `${t.id}`,
        x0: p0.x, y0: p0.y, x1: p1.x, y1: p1.y,
        start: performance.now(), duration: travelDurationMs(metres),
        color: lotColour(t.cardId), shrinkTail: 0, growHead: 0,
      })
    }
  }, [transits])                                            // eslint-disable-line react-hooks/exhaustive-deps

  // ── Register merge / unmerge convergences ─────────────────────────────────
  useEffect(() => {
    for (const c of convergences) {
      if (live.current.some((k) => k.id === c.id)) continue
      const hub = stations[c.stationId]
      if (!hub) { endConvergence(c.id); continue }
      const O = centre(hub)

      // Directions come from the real graph: each token sits on the bearing of
      // an actual feed. A merge consumes lots that are already standing at the
      // station, so this is a convergence into the node — not a claim that
      // they crossed the map at this moment, which would be a fabricated path.
      const feeds = c.kind === 'merge'
        ? Object.values(routes).filter((r) => r.unload === c.stationId)
            .map((r) => stations[r.load]).filter(Boolean) as Station[]
        : c.newCardIds
            .map((id) => Object.keys(cards[id]?.bins ?? {})[0])
            .map((sid) => stations[sid ?? '']).filter(Boolean) as Station[]

      const n = Math.max(1, Math.min(6, c.kind === 'merge' ? c.sourceCardIds.length : c.newCardIds.length))
      const reach = half * 1.9
      const now = performance.now()

      for (let i = 0; i < n; i++) {
        const f = feeds[i % Math.max(1, feeds.length)]
        let ux: number, uy: number
        if (f) {
          const p = centre(f)
          const d = Math.hypot(p.x - O.x, p.y - O.y) || 1
          ux = (p.x - O.x) / d; uy = (p.y - O.y) / d
        } else {                                            // no edge to follow
          const a = (i / n) * Math.PI * 2
          ux = Math.cos(a); uy = Math.sin(a)
        }
        const rim = { x: O.x + ux * reach, y: O.y + uy * reach }
        const cardId = c.kind === 'merge' ? c.sourceCardIds[i] : c.newCardIds[i]
        live.current.push({
          id: c.id, key: `${c.id}-${i}`,
          // Unmerge is the same motion reversed: out of the node, not into it.
          x0: c.kind === 'merge' ? rim.x : O.x, y0: c.kind === 'merge' ? rim.y : O.y,
          x1: c.kind === 'merge' ? O.x   : rim.x, y1: c.kind === 'merge' ? O.y   : rim.y,
          start: now, duration: MERGE_MS,
          color: lotColour(cardId ?? ''),
          shrinkTail: c.kind === 'merge'   ? SHRINK_MS : 0,
          growHead:   c.kind === 'unmerge' ? SHRINK_MS : 0,
        })
      }
    }
  }, [convergences])                                        // eslint-disable-line react-hooks/exhaustive-deps

  useTick(() => {
    const g = gRef.current
    if (!g) return
    g.clear()
    if (live.current.length === 0) return

    const now = performance.now()
    const done = new Set<string>()

    for (const tk of live.current) {
      const t = (now - tk.start) / tk.duration
      if (t >= 1) { done.add(tk.id); continue }
      const e = easeInOut(t)
      const x = tk.x0 + (tk.x1 - tk.x0) * e
      const y = tk.y0 + (tk.y1 - tk.y0) * e

      let scale = 1
      if (tk.shrinkTail > 0) {
        const tail = tk.shrinkTail / tk.duration
        if (t > 1 - tail) scale = Math.max(0, (1 - t) / tail)
      }
      if (tk.growHead > 0) {
        const head = tk.growHead / tk.duration
        if (t < head) scale = Math.max(0, t / head)
      }
      if (scale <= 0.01) continue

      const r = TOKEN_R * scale
      // A soft halo so the token stays visible over a dark floor plan and over
      // the heat blobs, the same casing trick the route edges use.
      g.beginFill(tk.color, 0.22)
      g.drawCircle(x, y, r * 2.1)
      g.endFill()
      g.lineStyle(1.5, 0xffffff, 0.55)
      g.beginFill(tk.color, 1)
      g.drawCircle(x, y, r)
      g.endFill()
      g.lineStyle(0)
    }

    if (done.size) {
      live.current = live.current.filter((tk) => !done.has(tk.id))
      for (const id of done) {
        if (id.startsWith('tr-')) endTransit(id)
        else endConvergence(id)
      }
    }
  })

  return <Graphics ref={gRef} />
}
