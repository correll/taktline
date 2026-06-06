import React, { useRef, useCallback, useState, useMemo } from 'react'
import { Container, Graphics, Text } from '@pixi/react'
import * as PIXI from 'pixi.js'
import type { Station } from '../../models'
import { useStationsStore } from '../../store'

export const NODE_W = 100
export const NODE_H = 32
const RADIUS = 4

// Accent bar color: green when lots are present, muted blue otherwise
const COLOR_ACTIVE  = 0x10B981
const COLOR_EMPTY   = 0x2D5B8E
const COLOR_SELECTED= 0x3B82F6
const BG_NORMAL     = 0x0D1B2E
const BG_SELECTED   = 0x162845

interface Props {
  station:      Station
  lotCount:     number       // distinct lot cards currently at this station
  selected:     boolean
  onSelect:     () => void
  onNodePointerDown: () => void
}

export default function StationNode({ station, lotCount, selected, onSelect, onNodePointerDown }: Props) {
  const updateStation = useStationsStore((s) => s.update)

  const accentColor = selected ? COLOR_SELECTED : lotCount > 0 ? COLOR_ACTIVE : COLOR_EMPTY

  const dragRef = useRef<{ px: number; py: number; sx: number; sy: number } | null>(null)
  const [localPos, setLocalPos] = useState<{ x: number; y: number } | null>(null)
  const pos = localPos ?? { x: station.position.x, y: station.position.y }

  const drawNode = useCallback((g: PIXI.Graphics) => {
    g.clear()
    // Body
    g.lineStyle(selected ? 1.5 : 1, accentColor, selected ? 1 : 0.6)
    g.beginFill(selected ? BG_SELECTED : BG_NORMAL)
    g.drawRoundedRect(0, 0, NODE_W, NODE_H, RADIUS)
    g.endFill()
    // Left accent bar
    g.lineStyle(0)
    g.beginFill(accentColor)
    g.drawRoundedRect(0, 0, 3, NODE_H, RADIUS)
    g.endFill()
  }, [accentColor, selected])

  const nameStyle = useMemo(() => new PIXI.TextStyle({
    fill: 0xC5D3E2,
    fontSize: 10,
    fontWeight: '500',
    fontFamily: 'Inter, system-ui, sans-serif',
    wordWrap: false,
  }), [])

  const countStyle = useMemo(() => new PIXI.TextStyle({
    fill: lotCount > 0 ? 0x10B981 : 0x4A6080,
    fontSize: 10,
    fontWeight: '600',
    fontFamily: '"JetBrains Mono", monospace',
  }), [lotCount])

  // Truncate name to fit in the node width
  const displayName = station.name.length > 11 ? station.name.slice(0, 10) + '…' : station.name

  const handlePointerDown = useCallback((e: PIXI.FederatedPointerEvent) => {
    e.stopPropagation()
    onNodePointerDown()
    dragRef.current = { px: e.globalX, py: e.globalY, sx: pos.x, sy: pos.y }
  }, [pos, onNodePointerDown])

  const handlePointerMove = useCallback((e: PIXI.FederatedPointerEvent) => {
    if (!dragRef.current) return
    setLocalPos({
      x: dragRef.current.sx + (e.globalX - dragRef.current.px),
      y: dragRef.current.sy + (e.globalY - dragRef.current.py),
    })
  }, [])

  const handlePointerUp = useCallback(() => {
    if (!dragRef.current) return
    if (localPos) {
      updateStation(station._id, {
        position: { ...station.position, x: Math.round(localPos.x), y: Math.round(localPos.y) },
      })
    }
    dragRef.current = null
    setLocalPos(null)
  }, [station, localPos, updateStation])

  const handleTap = useCallback((e: PIXI.FederatedPointerEvent) => {
    e.stopPropagation()
    if (!dragRef.current) onSelect()
  }, [onSelect])

  return (
    <Container
      x={pos.x}
      y={pos.y}
      eventMode="static"
      cursor="pointer"
      pointerdown={handlePointerDown}
      pointermove={handlePointerMove}
      pointerup={handlePointerUp}
      pointerupoutside={handlePointerUp}
      pointertap={handleTap}
    >
      <Graphics draw={drawNode} />
      {/* Name: padded past the accent bar */}
      <Text text={displayName} style={nameStyle} x={8} y={11} />
      {/* Lot count badge: right-aligned */}
      <Text text={String(lotCount)} style={countStyle} x={NODE_W - 14} y={11} />
    </Container>
  )
}
