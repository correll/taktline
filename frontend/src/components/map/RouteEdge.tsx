import React, { useRef, useEffect, useCallback } from 'react'
import { Graphics, useTick } from '@pixi/react'
import * as PIXI from 'pixi.js'
import type { Route, Station } from '../../models'

const DASH = 10
const GAP  = 6
const FLOW_SPEED = 0.6   // px per frame
const ARROW_LEN  = 14
const ARROW_HALF = 7
const LINE_COLOR = 0x2563EB
const LINE_ALPHA  = 0.55

interface Props {
  route: Route
  fromStation: Station | undefined
  toStation:   Station | undefined
}

function drawDashedLine(
  g: PIXI.Graphics,
  x1: number, y1: number,
  x2: number, y2: number,
  offset: number
): void {
  const dx  = x2 - x1
  const dy  = y2 - y1
  const len = Math.sqrt(dx * dx + dy * dy)
  if (len < 1) return
  const ux = dx / len
  const uy = dy / len
  const period = DASH + GAP
  let t = -(offset % period)
  while (t < len) {
    const s = Math.max(0, t)
    const e = Math.min(len, t + DASH)
    if (e > s) {
      g.moveTo(x1 + ux * s, y1 + uy * s)
      g.lineTo(x1 + ux * e, y1 + uy * e)
    }
    t += period
  }
}

export default function RouteEdge({ route, fromStation, toStation }: Props) {
  const gRef    = useRef<PIXI.Graphics>(null)
  const offset  = useRef(0)

  const redraw = useCallback(() => {
    const g = gRef.current
    if (!g || !fromStation || !toStation) return
    g.clear()

    const fw = fromStation.position.width  ?? 150
    const fh = fromStation.position.height ?? 64
    const tw = toStation.position.width    ?? 150
    const th = toStation.position.height   ?? 64

    const x1 = fromStation.position.x + fw / 2
    const y1 = fromStation.position.y + fh / 2
    const x2 = toStation.position.x   + tw / 2
    const y2 = toStation.position.y   + th / 2

    const angle = Math.atan2(y2 - y1, x2 - x1)

    // Pull the line end back by arrowhead length so it doesn't overlap
    const ax = x2 - Math.cos(angle) * ARROW_LEN
    const ay = y2 - Math.sin(angle) * ARROW_LEN

    // Dashed animated line
    g.lineStyle(1.5, LINE_COLOR, LINE_ALPHA)
    drawDashedLine(g, x1, y1, ax, ay, offset.current)

    // Arrowhead
    const cos = Math.cos(angle)
    const sin = Math.sin(angle)
    g.lineStyle(0)
    g.beginFill(LINE_COLOR, LINE_ALPHA + 0.2)
    g.moveTo(x2, y2)
    g.lineTo(x2 - ARROW_LEN * cos + ARROW_HALF * sin, y2 - ARROW_LEN * sin - ARROW_HALF * cos)
    g.lineTo(x2 - ARROW_LEN * cos - ARROW_HALF * sin, y2 - ARROW_LEN * sin + ARROW_HALF * cos)
    g.closePath()
    g.endFill()
  }, [fromStation, toStation])

  // Initial draw
  useEffect(() => { redraw() }, [redraw])

  useTick((delta) => {
    offset.current = (offset.current + delta * FLOW_SPEED) % (DASH + GAP)
    redraw()
  })

  return <Graphics ref={gRef} />
}
