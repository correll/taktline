import React, { useRef, useEffect, useCallback } from 'react'
import { Graphics, Text, useTick } from '@pixi/react'
import * as PIXI from 'pixi.js'
import type { Route, Station } from '../../models'
import { useThemeStore } from '../../store'

const DASH = 10
const GAP  = 6
const FLOW_SPEED = 0.6   // px per frame
const ARROW_LEN  = 4
const ARROW_HALF = 2
const LINE_ALPHA  = 0.9
const HALO_ALPHA  = 0.75
const HALO_EXTRA  = 2.6   // casing width beyond the dash stroke

// Pixi needs numeric colors — mirror the day/night surface + ink variables.
// Each dash is drawn twice: a wider stroke in the page background color (a
// cartographic "casing"), then the ink stroke on top. That keeps routes
// readable over anything underneath — heat blobs included.
const EDGE_COLORS: Record<'night' | 'day', { line: number; halo: number; badgeFill: number; badgeText: number }> = {
  night: { line: 0xB4B1A9, halo: 0x121110, badgeFill: 0x1D1C1A, badgeText: 0xEFEDE7 },
  day:   { line: 0x3D3B37, halo: 0xF7F6F2, badgeFill: 0xFFFFFF, badgeText: 0x1A1917 },
}

interface Props {
  route:       Route
  fromStation: Station | undefined
  toStation:   Station | undefined
  nodeSize:    number
  /** Set when one end is an integration partner. Such an edge carries no
   *  material — it is demand going out or a handoff going in — so it is drawn
   *  in the partner's colour with a longer, sparser dash to read as a
   *  different kind of connection, not another step in the flow. */
  boundaryTint?: number
  /** The colour of the process this route belongs to. */
  tint?: number
  /** Perpendicular shift in world px. Two processes routing between the same
   *  pair of stations would otherwise be drawn one exactly on top of the
   *  other, so the second line — and the fact that there are two — would be
   *  invisible. Shifting them apart is the only cue that survives, since a
   *  colour you cannot see tells you nothing. */
  offsetPx?: number
  /** Longitudinal shift of the weight badge along the run, in world px,
   *  measured in the canonical (lower-id → higher-id) frame. The lane gap is a
   *  few px but a badge is 9+ px of radius, so when two lanes both carry a
   *  weight their badges land on top of each other; staggering them along the
   *  line is what keeps both numbers readable. */
  badgeShiftPx?: number
}

function drawDashedLine(
  g: PIXI.Graphics,
  x1: number, y1: number,
  x2: number, y2: number,
  offset: number,
  dashLen: number = DASH,
): void {
  const dx  = x2 - x1
  const dy  = y2 - y1
  const len = Math.sqrt(dx * dx + dy * dy)
  if (len < 1) return
  const ux = dx / len
  const uy = dy / len
  const period = dashLen + GAP
  let t = (offset % period) - period
  while (t < len) {
    const s = Math.max(0, t)
    const e = Math.min(len, t + dashLen)
    if (e > s) {
      g.moveTo(x1 + ux * s, y1 + uy * s)
      g.lineTo(x1 + ux * e, y1 + uy * e)
    }
    t += period
  }
}

export default function RouteEdge({ route, fromStation, toStation, nodeSize,
                                   boundaryTint, tint, offsetPx = 0, badgeShiftPx = 0 }: Props) {
  const gRef     = useRef<PIXI.Graphics>(null)
  const badgeRef = useRef<PIXI.Graphics>(null)
  const offset   = useRef(0)
  const themeMode = useThemeStore((s) => s.mode)

  // Edge-weight badge: how many precursor units one assembly consumes. Only
  // drawn when it differs from the default of 1.
  const quantity   = Math.max(1, route.quantity ?? 1)
  const showBadge  = quantity !== 1
  const badgeR     = Math.max(9, nodeSize * 0.13)
  const half       = nodeSize / 2
  let midX = fromStation && toStation ? (fromStation.position.x + toStation.position.x) / 2 + half : 0
  let midY = fromStation && toStation ? (fromStation.position.y + toStation.position.y) / 2 + half : 0
  if ((offsetPx || badgeShiftPx) && fromStation && toStation) {
    const dx = toStation.position.x - fromStation.position.x
    const dy = toStation.position.y - fromStation.position.y
    const len = Math.hypot(dx, dy) || 1
    const flip = String(route.load) > String(route.unload) ? -1 : 1   // same frame as the line
    midX += (-dy / len) * offsetPx * flip
    midY += (dx / len) * offsetPx * flip
    // The stagger runs along the line, clamped so a badge never slides under
    // a station tile on a short edge. Applied in the canonical frame so two
    // opposite-direction routes agree on which end is "first".
    const maxShift = Math.max(0, len / 2 - half - badgeR)
    const shift = Math.max(-maxShift, Math.min(maxShift, badgeShiftPx))
    midX += (dx / len) * shift * flip
    midY += (dy / len) * shift * flip
  }

  const redraw = useCallback(() => {
    const g = gRef.current
    if (!g || !fromStation || !toStation) return
    g.clear()
    const dash = boundaryTint != null ? DASH * 0.45 : DASH

    let x1 = fromStation.position.x + half
    let y1 = fromStation.position.y + half
    let x2 = toStation.position.x   + half
    let y2 = toStation.position.y   + half
    if (offsetPx) {
      const dx = x2 - x1, dy = y2 - y1
      const len = Math.hypot(dx, dy) || 1
      // The normal is taken in a canonical frame — always as if running from
      // the lower station id to the higher — so a route and its reverse shift
      // to *opposite* sides rather than each to its own left, which would put
      // them back on top of each other.
      const flip = String(route.load) > String(route.unload) ? -1 : 1
      const nx = (-dy / len) * flip, ny = (dx / len) * flip
      x1 += nx * offsetPx; y1 += ny * offsetPx
      x2 += nx * offsetPx; y2 += ny * offsetPx
    }

    const angle = Math.atan2(y2 - y1, x2 - x1)
    const base = EDGE_COLORS[themeMode]
    const line = boundaryTint ?? tint
    const colors = line != null ? { ...base, line } : base

    // Pull the line end back by arrowhead length so it doesn't overlap
    const ax = x2 - Math.cos(angle) * ARROW_LEN
    const ay = y2 - Math.sin(angle) * ARROW_LEN

    // Dashed animated line — halo casing first, ink stroke on top
    g.lineStyle(1.5 + HALO_EXTRA, colors.halo, HALO_ALPHA)
    drawDashedLine(g, x1, y1, ax, ay, offset.current, dash)
    g.lineStyle(1.5, colors.line, LINE_ALPHA)
    drawDashedLine(g, x1, y1, ax, ay, offset.current, dash)

    // Arrowhead — halo outline around the ink fill
    const cos = Math.cos(angle)
    const sin = Math.sin(angle)
    g.lineStyle(HALO_EXTRA, colors.halo, HALO_ALPHA)
    g.beginFill(colors.line, 1)
    g.moveTo(x2, y2)
    g.lineTo(x2 - ARROW_LEN * cos + ARROW_HALF * sin, y2 - ARROW_LEN * sin - ARROW_HALF * cos)
    g.lineTo(x2 - ARROW_LEN * cos - ARROW_HALF * sin, y2 - ARROW_LEN * sin + ARROW_HALF * cos)
    g.closePath()
    g.endFill()

  }, [fromStation, toStation, nodeSize, half, themeMode,
      boundaryTint, tint, offsetPx])

  // Initial draw
  useEffect(() => { redraw() }, [redraw])

  // The badge lives in its own Graphics, sorted above every edge line (the
  // parent container sorts children): drawn in tree order it sits under
  // whichever sibling edge renders later, which crosses the number out with a
  // dashed line. It doesn't animate, so it redraws only when it moves.
  useEffect(() => {
    const g = badgeRef.current
    if (!g) return
    g.clear()
    if (!showBadge || !fromStation || !toStation) return
    const base = EDGE_COLORS[themeMode]
    const lineColor = boundaryTint ?? tint ?? base.line
    g.lineStyle(1.2, lineColor, 0.9)
    g.beginFill(base.badgeFill, 1)
    g.drawCircle(midX, midY, badgeR)
    g.endFill()
  }, [showBadge, midX, midY, badgeR, themeMode, boundaryTint, tint, fromStation, toStation])

  useTick((delta) => {
    offset.current = (offset.current + delta * FLOW_SPEED) % (DASH + GAP)
    redraw()
  })

  return (
    <>
      <Graphics ref={gRef} />
      {showBadge && fromStation && toStation && (
        <>
          <Graphics ref={badgeRef} zIndex={20} />
          <Text
            text={String(quantity)}
            x={midX}
            y={midY}
            anchor={0.5}
            resolution={4}
            zIndex={21}
            style={new PIXI.TextStyle({
              fontFamily: 'Inter, system-ui, sans-serif',
              fontSize:   badgeR * 1.05,
              fontWeight: '600',
              fill:       EDGE_COLORS[themeMode].badgeText,
            })}
          />
        </>
      )}
    </>
  )
}
