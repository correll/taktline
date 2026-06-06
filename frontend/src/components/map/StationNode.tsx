import React, { useRef, useCallback, useState, useMemo } from 'react'
import { Container, Graphics, Text } from '@pixi/react'
import * as PIXI from 'pixi.js'
import type { Station, MachineState } from '../../models'
import { STATUS_HEX } from './mapColors'
import { useStationsStore } from '../../store'

export const NODE_W = 150
export const NODE_H = 64
const RADIUS = 6

interface Props {
  station:      Station
  machineState: MachineState | undefined
  selected:     boolean
  onSelect:     () => void
  onNodePointerDown: () => void   // tells MapCanvas a node drag started
}

export default function StationNode({ station, machineState, selected, onSelect, onNodePointerDown }: Props) {
  const updateStation = useStationsStore((s) => s.update)

  const status     = (machineState?.status ?? 'none') as keyof typeof STATUS_HEX
  const statusHex  = STATUS_HEX[status]
  const isAnimated = status === 'running' || status === 'fault'

  const dragRef = useRef<{ px: number; py: number; sx: number; sy: number } | null>(null)
  const [localPos, setLocalPos] = useState<{ x: number; y: number } | null>(null)
  const pos = localPos ?? { x: station.position.x, y: station.position.y }

  const drawNode = useCallback((g: PIXI.Graphics) => {
    g.clear()
    if (isAnimated) {
      g.lineStyle(10, statusHex, 0.15)
      g.drawRoundedRect(-5, -5, NODE_W + 10, NODE_H + 10, RADIUS + 4)
    }
    g.lineStyle(selected ? 2 : 1.5, selected ? 0x3B82F6 : statusHex)
    g.beginFill(selected ? 0x162845 : 0x101E35)
    g.drawRoundedRect(0, 0, NODE_W, NODE_H, RADIUS)
    g.endFill()
    // Status accent bar on left edge
    g.lineStyle(0)
    g.beginFill(statusHex)
    g.drawRoundedRect(0, 0, 4, NODE_H, RADIUS)
    g.endFill()
  }, [statusHex, selected, isAnimated])

  const nameStyle = useMemo(() => new PIXI.TextStyle({
    fill: 0xEBF1F8, fontSize: 12, fontWeight: '600',
    fontFamily: 'Inter, system-ui, sans-serif',
    wordWrap: true, wordWrapWidth: NODE_W - 20,
  }), [])

  const statusStyle = useMemo(() => new PIXI.TextStyle({
    fill: statusHex, fontSize: 9,
    fontFamily: '"JetBrains Mono", monospace',
    letterSpacing: 1,
  }), [statusHex])

  const metricStyle = useMemo(() => new PIXI.TextStyle({
    fill: 0x8FA3BC, fontSize: 10,
    fontFamily: '"JetBrains Mono", monospace',
  }), [])

  const statusLabel  = machineState ? machineState.status.toUpperCase() : 'NO ADAPTER'
  const firstMetric  = machineState ? Object.values(machineState.metrics)[0] : null
  const metricText   = firstMetric ? `${firstMetric.label}: ${firstMetric.value} ${firstMetric.unit}` : ''

  const handlePointerDown = useCallback((e: PIXI.FederatedPointerEvent) => {
    e.stopPropagation()
    onNodePointerDown()
    dragRef.current = {
      px: e.globalX, py: e.globalY,
      sx: pos.x,     sy: pos.y,
    }
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
      cursor={dragRef.current ? 'grabbing' : 'pointer'}
      pointerdown={handlePointerDown}
      pointermove={handlePointerMove}
      pointerup={handlePointerUp}
      pointerupoutside={handlePointerUp}
      pointertap={handleTap}
    >
      <Graphics draw={drawNode} />
      <Text text={station.name} style={nameStyle} x={12} y={9} />
      <Text text={statusLabel} style={statusStyle} x={12} y={28} />
      {metricText ? <Text text={metricText} style={metricStyle} x={12} y={42} /> : null}
    </Container>
  )
}
