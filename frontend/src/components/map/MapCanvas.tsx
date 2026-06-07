import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Stage, Container, Graphics, Sprite } from '@pixi/react'
import * as PIXI from 'pixi.js'
import type { Station, Route } from '../../models'
import { color } from '../../theme/tokens'
import { useCardsStore, useMapSettingsStore } from '../../store'
import StationNode from './StationNode'
import RouteEdge from './RouteEdge'

export const DEFAULT_NODE_SIZE = 100

export interface Viewport { x: number; y: number; scale: number }

const MIN_ZOOM = 0.002
const MAX_ZOOM = 8.0

interface Props {
  stations:          Record<string, Station>
  routes:            Record<string, Route>
  lotCounts:         Record<string, number>
  selectedStationId: string | null
  onSelectStation:   (id: string) => void
}

export default function MapCanvas({
  stations, routes, lotCounts, selectedStationId, onSelectStation,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [canvasSize, setCanvasSize]       = useState({ w: 800, h: 600 })
  const [viewport, setViewport]           = useState<Viewport>({ x: 60, y: 60, scale: 1 })
  const [floorPlanRect, setFloorPlanRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null)
  const panRef = useRef<{ startX: number; startY: number; vpX: number; vpY: number } | null>(null)

  // Always-fresh refs so event-handler closures never go stale
  const fpRectRef  = useRef(floorPlanRect)
  const csSizeRef  = useRef(canvasSize)
  fpRectRef.current = floorPlanRect
  csSizeRef.current = canvasSize

  const cards     = useCardsStore((s) => s.cards)
  const mapConfig = useMapSettingsStore((s) => s.settings)

  const nodeSize = mapConfig
    ? (mapConfig.stationSizeUnits ?? 1) * mapConfig.pixelsPerUnit
    : DEFAULT_NODE_SIZE

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

  // Fit view on first load (once stations become non-empty)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fitView() }, [Object.keys(stations).length === 0 ? 0 : 1])

  // Floor plan display rect.
  // If mapWidthPx is saved (from the settings preview), use it directly — this makes
  // raw pixelsPerUnit correct for the scale bar since both use the same CSS-pixel frame.
  // Otherwise fall back to the station bounding box.
  useEffect(() => {
    if (!mapConfig?.floorPlanUrl) {
      setFloorPlanRect(null)
      return
    }
    if (mapConfig.mapWidthPx && mapConfig.mapHeightPx) {
      setFloorPlanRect({ x: 0, y: 0, w: mapConfig.mapWidthPx, h: mapConfig.mapHeightPx })
      return
    }
    // Fallback: station bounding box
    const list = Object.values(stations)
    if (list.length === 0) { setFloorPlanRect(null); return }
    const ppu = mapConfig.pixelsPerUnit ?? 100
    const sz  = (mapConfig.stationSizeUnits ?? 1) * ppu
    const pad = sz * 1.5
    const xs  = list.map((s) => s.position.x)
    const ys  = list.map((s) => s.position.y)
    setFloorPlanRect({
      x: Math.min(...xs) - pad,
      y: Math.min(...ys) - pad,
      w: Math.max(...xs) - Math.min(...xs) + sz + pad * 2,
      h: Math.max(...ys) - Math.min(...ys) + sz + pad * 2,
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapConfig?.floorPlanUrl, mapConfig?.pixelsPerUnit, mapConfig?.stationSizeUnits,
      mapConfig?.mapWidthPx, mapConfig?.mapHeightPx,
      Object.keys(stations).length === 0 ? 0 : 1])

  // Clamp viewport: keep content >= 50 screen px and always partially on-screen.
  // Uses refs so it can be called from inside setViewport() without stale closures.
  const clampVP = (vp: Viewport): Viewport => {
    const fp = fpRectRef.current
    if (!fp) return vp
    const { w: cw, h: ch } = csSizeRef.current
    const pad  = 50
    // Dynamic min zoom: floor plan is always at least `pad` px in its largest dim
    const minZ = Math.max(MIN_ZOOM, pad / Math.max(fp.w, fp.h))
    const s    = Math.min(MAX_ZOOM, Math.max(minZ, vp.scale))
    let { x, y } = vp
    const l = fp.x       * s + x
    const r = (fp.x + fp.w) * s + x
    const t = fp.y       * s + y
    const b = (fp.y + fp.h) * s + y
    if (r < pad)       x += pad - r
    if (l > cw - pad)  x -= l - (cw - pad)
    if (b < pad)       y += pad - b
    if (t > ch - pad)  y -= t - (ch - pad)
    return { x, y, scale: s }
  }

  // Fit viewport to content (floor plan rect if present, else station bounding box)
  const fitView = useCallback(() => {
    const sw   = canvasSize.w || 800
    const sh   = canvasSize.h || 600
    const list = Object.values(stations)
    const rect = floorPlanRect

    let minX: number, minY: number, maxX: number, maxY: number
    if (rect) {
      minX = rect.x; minY = rect.y; maxX = rect.x + rect.w; maxY = rect.y + rect.h
    } else if (list.length > 0) {
      const pad = nodeSize * 0.6
      const xs  = list.map((s) => s.position.x)
      const ys  = list.map((s) => s.position.y)
      minX = Math.min(...xs) - pad; minY = Math.min(...ys) - pad
      maxX = Math.max(...xs) + nodeSize + pad; maxY = Math.max(...ys) + nodeSize + pad
    } else {
      return
    }
    const scale = Math.min(sw / (maxX - minX), sh / (maxY - minY)) * 0.92
    setViewport({
      x: -minX * scale + (sw - (maxX - minX) * scale) / 2,
      y: -minY * scale + (sh - (maxY - minY) * scale) / 2,
      scale,
    })
  }, [canvasSize, stations, floorPlanRect, nodeSize])

  // Wheel zoom — must be imperative so we can pass { passive: false } and
  // actually call preventDefault (React registers wheel events as passive).
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const handler = (e: WheelEvent) => {
      e.preventDefault()
      const factor = e.deltaY < 0 ? 1.06 : 1 / 1.06
      setViewport((v) => {
        const newScale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.scale * factor))
        const rect = el.getBoundingClientRect()
        const mx = e.clientX - rect.left
        const my = e.clientY - rect.top
        const dx = (mx - v.x) * (newScale / v.scale - 1)
        const dy = (my - v.y) * (newScale / v.scale - 1)
        return clampVP({ x: v.x - dx, y: v.y - dy, scale: newScale })
      })
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, []) // setViewport is stable; clampVP reads refs so never stale

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return
    panRef.current = { startX: e.clientX, startY: e.clientY, vpX: viewport.x, vpY: viewport.y }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }, [viewport])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!panRef.current) return
    setViewport((v) => clampVP({
      ...v,
      x: panRef.current!.vpX + (e.clientX - panRef.current!.startX),
      y: panRef.current!.vpY + (e.clientY - panRef.current!.startY),
    }))
  }, [])

  const handlePointerUp = useCallback(() => { panRef.current = null }, [])

  // WIP ratios for heatmap
  const wipRatios = React.useMemo(() => {
    const wipMap: Record<string, number> = {}
    for (const card of Object.values(cards)) {
      for (const [sid, bin] of Object.entries(card.bins)) {
        if (bin.count > 0) wipMap[sid] = (wipMap[sid] ?? 0) + bin.count
      }
    }
    const maxWip = Math.max(1, ...Object.values(wipMap))
    const result: Record<string, number> = {}
    for (const sid of Object.keys(wipMap)) result[sid] = wipMap[sid] / maxWip
    return result
  }, [cards])

  const stationList = Object.values(stations)
  const routeList   = Object.values(routes)
  const isEmpty     = stationList.length === 0

  // Raw pixelsPerUnit is correct when floor plan is rendered at mapWidthPx canvas pixels
  // (which equals the settings-preview CSS display width, the frame ppu was calibrated in).
  const ppu = mapConfig?.pixelsPerUnit ?? DEFAULT_NODE_SIZE

  return (
    <div
      ref={containerRef}
      style={{
        flex:     1,
        overflow: 'hidden',
        cursor:   panRef.current ? 'grabbing' : 'default',
        position: 'relative',
      }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
    >
      {/* ── PixiJS: floor plan + heatmap + edges ── */}
      {canvasSize.w > 0 && (
        <Stage
          width={canvasSize.w}
          height={canvasSize.h}
          options={{
            background:  0x060E1E,
            antialias:   true,
            resolution:  window.devicePixelRatio || 1,
            autoDensity: true,
          }}
        >
          <Container x={viewport.x} y={viewport.y} scale={viewport.scale}>
            {mapConfig?.floorPlanUrl && floorPlanRect && (
              <FloorPlanSprite url={mapConfig.floorPlanUrl} rect={floorPlanRect} />
            )}

            {stationList.map((s) => {
              const ratio = wipRatios[s._id] ?? 0
              if (ratio === 0) return null
              return (
                <HeatBlob
                  key={`heat-${s._id}`}
                  x={s.position.x + nodeSize / 2}
                  y={s.position.y + nodeSize / 2}
                  ratio={ratio}
                  nodeSize={nodeSize}
                />
              )
            })}

            {routeList.map((route) => (
              <RouteEdge
                key={route._id}
                route={route}
                fromStation={stations[route.load]}
                toStation={stations[route.unload]}
                nodeSize={nodeSize}
              />
            ))}
          </Container>
        </Stage>
      )}

      {/* ── HTML overlay: station nodes ── */}
      <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden' }}>
        {stationList.map((station) => (
          <StationNode
            key={station._id}
            station={station}
            lotCount={lotCounts[station._id] ?? 0}
            selected={selectedStationId === station._id}
            nodeSize={nodeSize}
            viewport={viewport}
            onSelect={() => onSelectStation(station._id)}
          />
        ))}
      </div>

      {/* Scale bar */}
      {mapConfig && ppu > 0 && !isEmpty && (
        <ScaleBar
          viewportScale={viewport.scale}
          pixelsPerUnit={ppu}
          unit={mapConfig.unit}
        />
      )}

      {/* Fit / reset view button */}
      {!isEmpty && (
        <button
          onClick={fitView}
          title="Fit view"
          style={{
            position:     'absolute',
            bottom:       16,
            right:        16,
            width:        32,
            height:       32,
            background:   'rgba(6,14,30,0.72)',
            border:       '1px solid rgba(255,255,255,0.15)',
            borderRadius: 4,
            color:        'rgba(235,241,248,0.8)',
            cursor:       'pointer',
            fontSize:     16,
            display:      'flex',
            alignItems:   'center',
            justifyContent: 'center',
            pointerEvents:  'all',
          }}
        >
          ⌖
        </button>
      )}

      {isEmpty && (
        <div style={{
          position:  'absolute', inset: 0,
          display:   'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          gap: 12, pointerEvents: 'none',
        }}>
          <div style={{ fontSize: 40, opacity: 0.15 }}>⬡</div>
          <div style={{ color: color.textDim, fontSize: 13 }}>
            No locations yet — add them in Settings
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Floor plan sprite ────────────────────────────────────────────────────────

function FloorPlanSprite({
  url, rect,
}: { url: string; rect: { x: number; y: number; w: number; h: number } }) {
  const [texture, setTexture] = useState<PIXI.Texture | null>(null)

  useEffect(() => {
    let cancelled = false
    PIXI.Assets.load(url).then((t: PIXI.Texture) => {
      if (!cancelled) setTexture(t)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [url])

  if (!texture) return null

  return (
    <Sprite
      texture={texture}
      x={rect.x}
      y={rect.y}
      width={rect.w}
      height={rect.h}
      alpha={1}
    />
  )
}

// ─── Heatmap blob ─────────────────────────────────────────────────────────────

function HeatBlob({
  x, y, ratio, nodeSize,
}: { x: number; y: number; ratio: number; nodeSize: number }) {
  const radius = nodeSize * 0.6 + ratio * nodeSize * 0.8
  const alpha  = 0.12 + ratio * 0.22

  const draw = useCallback((g: PIXI.Graphics) => {
    g.clear()
    g.beginFill(0xFF6600, alpha * 0.5)
    g.drawCircle(0, 0, radius * 1.4)
    g.endFill()
    g.beginFill(0xFF3300, alpha)
    g.drawCircle(0, 0, radius)
    g.endFill()
  }, [radius, alpha])

  return <Graphics x={x} y={y} draw={draw} />
}

// ─── Scale bar ────────────────────────────────────────────────────────────────

function ScaleBar({
  viewportScale, pixelsPerUnit, unit,
}: { viewportScale: number; pixelsPerUnit: number; unit: 'ft' | 'm' }) {
  const pxPerUnit = pixelsPerUnit * viewportScale
  if (pxPerUnit <= 0) return null

  const niceNumbers = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 50000]
  let count = niceNumbers[niceNumbers.length - 1]
  for (const n of niceNumbers) {
    if (n * pxPerUnit >= 60) { count = n; break }
  }
  const barLength = count * pxPerUnit
  if (barLength > 600 || barLength < 1) return null

  const AL = 8
  const AH = 5

  return (
    <div style={{
      position:      'absolute',
      bottom:        16,
      left:          16,
      background:    'rgba(6,14,30,0.72)',
      border:        '1px solid rgba(255,255,255,0.15)',
      borderRadius:  4,
      padding:       '5px 8px 6px',
      pointerEvents: 'none',
      userSelect:    'none',
    }}>
      <div style={{
        fontSize:      10,
        color:         'rgba(235,241,248,0.7)',
        textAlign:     'center',
        marginBottom:  3,
        fontFamily:    '"JetBrains Mono", monospace',
        letterSpacing: '0.05em',
      }}>
        {count} {unit}
      </div>
      <svg width={barLength + 2} height={AH * 2 + 4} style={{ display: 'block', overflow: 'visible' }}>
        <g transform={`translate(0,${AH + 2})`} stroke="#EBF1F8" fill="#EBF1F8">
          <polygon points={`0,0 ${AL},${-AH} ${AL},${AH}`} />
          <line x1={AL} y1={0} x2={barLength - AL} y2={0} strokeWidth={1.5} />
          <polygon points={`${barLength},0 ${barLength - AL},${-AH} ${barLength - AL},${AH}`} />
        </g>
      </svg>
    </div>
  )
}
