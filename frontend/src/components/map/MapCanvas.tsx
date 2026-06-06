import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Stage, Container } from '@pixi/react'
import type { Station, Route, MachineState } from '../../models'
import { color } from '../../theme/tokens'
import StationNode from './StationNode'
import RouteEdge from './RouteEdge'

const MIN_ZOOM = 0.12
const MAX_ZOOM = 4.0

interface Viewport { x: number; y: number; scale: number }

interface Props {
  stations:        Record<string, Station>
  routes:          Record<string, Route>
  machineStates:   Record<string, MachineState>
  selectedStationId: string | null
  onSelectStation: (id: string) => void
}

export default function MapCanvas({
  stations, routes, machineStates, selectedStationId, onSelectStation,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [canvasSize, setCanvasSize] = useState({ w: 800, h: 600 })
  const [viewport, setViewport]     = useState<Viewport>({ x: 60, y: 60, scale: 1 })
  const panRef    = useRef<{ startX: number; startY: number; vpX: number; vpY: number } | null>(null)
  const nodeHit   = useRef(false)   // set by StationNode before this div's handler fires

  // Track container size
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(([entry]) => {
      setCanvasSize({ w: entry.contentRect.width, h: entry.contentRect.height })
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // Fit all stations into view on first load
  useEffect(() => {
    const list = Object.values(stations)
    if (list.length === 0) return
    const xs = list.map((s) => s.position.x)
    const ys = list.map((s) => s.position.y)
    const minX = Math.min(...xs) - 60
    const minY = Math.min(...ys) - 60
    const maxX = Math.max(...xs) + 210
    const maxY = Math.max(...ys) + 120
    const sw = canvasSize.w || 800
    const sh = canvasSize.h || 600
    const scale = Math.min(1, sw / (maxX - minX), sh / (maxY - minY)) * 0.9
    setViewport({ x: -minX * scale + (sw - (maxX - minX) * scale) / 2, y: -minY * scale + (sh - (maxY - minY) * scale) / 2, scale })
  // Run once when stations first load (length goes from 0 to N)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Object.keys(stations).length === 0 ? 0 : 1])

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12
    setViewport((v) => {
      const newScale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.scale * factor))
      // Zoom toward the mouse cursor
      const rect  = containerRef.current?.getBoundingClientRect()
      const mx    = rect ? e.clientX - rect.left : e.clientX
      const my    = rect ? e.clientY - rect.top  : e.clientY
      const dx    = (mx - v.x) * (newScale / v.scale - 1)
      const dy    = (my - v.y) * (newScale / v.scale - 1)
      return { x: v.x - dx, y: v.y - dy, scale: newScale }
    })
  }, [])

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0 || nodeHit.current) { nodeHit.current = false; return }
    nodeHit.current = false
    panRef.current = { startX: e.clientX, startY: e.clientY, vpX: viewport.x, vpY: viewport.y }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }, [viewport])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!panRef.current) return
    setViewport((v) => ({
      ...v,
      x: panRef.current!.vpX + (e.clientX - panRef.current!.startX),
      y: panRef.current!.vpY + (e.clientY - panRef.current!.startY),
    }))
  }, [])

  const handlePointerUp = useCallback(() => { panRef.current = null }, [])

  const stationList = Object.values(stations)
  const routeList   = Object.values(routes)
  const isEmpty     = stationList.length === 0

  return (
    <div
      ref={containerRef}
      style={{ flex: 1, overflow: 'hidden', cursor: panRef.current ? 'grabbing' : 'default', position: 'relative' }}
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
    >
      {canvasSize.w > 0 && (
        <Stage
          width={canvasSize.w}
          height={canvasSize.h}
          options={{ background: 0x060E1E, antialias: true, resolution: window.devicePixelRatio || 1, autoDensity: true }}
        >
          <Container x={viewport.x} y={viewport.y} scale={viewport.scale}>
            {routeList.map((route) => (
              <RouteEdge
                key={route._id}
                route={route}
                fromStation={stations[route.load]}
                toStation={stations[route.unload]}
              />
            ))}
            {stationList.map((station) => (
              <StationNode
                key={station._id}
                station={station}
                machineState={machineStates[station._id]}
                selected={selectedStationId === station._id}
                onSelect={() => onSelectStation(station._id)}
                onNodePointerDown={() => { nodeHit.current = true }}
              />
            ))}
          </Container>
        </Stage>
      )}

      {isEmpty && (
        <div style={{
          position:       'absolute',
          inset:          0,
          display:        'flex',
          flexDirection:  'column',
          alignItems:     'center',
          justifyContent: 'center',
          gap:            12,
          pointerEvents:  'none',
        }}>
          <div style={{ fontSize: 40, opacity: 0.15 }}>⬡</div>
          <div style={{ color: color.textDim, fontSize: 13 }}>
            No stations yet — add them in Settings
          </div>
        </div>
      )}
    </div>
  )
}
