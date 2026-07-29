import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Stage, Container, Graphics, Sprite, useApp } from '@pixi/react'
import * as PIXI from 'pixi.js'
import type { Station, Route } from '../../models'
import { color, shadow } from '../../theme/tokens'
import { useCardsStore, useMapSettingsStore, useStationsStore, useProcessesStore, useThemeStore } from '../../store'
import StationNode, { type MapTool } from './StationNode'
import MapStationEditModal from './MapStationEditModal'
import RouteEdge from './RouteEdge'
import MotionLayer from './MotionLayer'
import { useCyclePulses } from '../../motion/useCyclePulses'
import type { CyclePulses } from '../../motion/cycle'
import { findAccumulations, type Accumulation } from '../../domain/graph'
import { integrationProvider, isIntegrationStation } from '../../domain/integrations'
import { hasWebGL } from '../demo/webgl'

/** Pixi needs numeric colours; the partner registry stores CSS hex. */
function hexToPixi(hex: string | undefined): number | undefined {
  const m = hex && /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  return m ? parseInt(m[1], 16) : undefined
}

export const DEFAULT_NODE_SIZE = 100
// Largest a location may be drawn when the camera auto-fits a floor-plan-less
// map. Only binds on a sparse map (one or two locations); once there are
// enough to fill the view the ordinary fit is smaller than this anyway.
const MAX_FIT_NODE_PX = 100

// Pixi needs numeric colors, so the canvas background can't read the CSS
// variables — mirror --tk-bg-deep for both themes here.
const CANVAS_BG: Record<'night' | 'day', number> = { night: 0x121110, day: 0xF7F6F2 }

export interface Viewport { x: number; y: number; scale: number }

const MIN_ZOOM = 0.002
const MAX_ZOOM = 8.0

// Finds processes whose route-graph is split into ≥2 disconnected pieces
// ("isolated subgraphs"). Returns the affected process ids plus every station in
// them (so they can be flashed). Empty when every process is one connected flow.
function isolatedProcessStations(routes: Record<string, Route>): { flash: Set<string>; procIds: string[] } {
  const byProc = new Map<string, Route[]>()
  for (const r of Object.values(routes)) {
    const arr = byProc.get(r.processId) ?? []
    arr.push(r)
    byProc.set(r.processId, arr)
  }
  const flash = new Set<string>()
  const procIds: string[] = []
  for (const [procId, rs] of byProc.entries()) {
    const adj = new Map<string, Set<string>>()
    const nodes = new Set<string>()
    const link = (a: string, b: string) => {
      if (!adj.has(a)) adj.set(a, new Set())
      adj.get(a)!.add(b)
    }
    for (const r of rs) { nodes.add(r.load); nodes.add(r.unload); link(r.load, r.unload); link(r.unload, r.load) }
    const seen = new Set<string>()
    let components = 0
    for (const n of nodes) {
      if (seen.has(n)) continue
      components++
      const queue = [n]; seen.add(n)
      while (queue.length) {
        const x = queue.shift()!
        for (const y of adj.get(x) ?? []) if (!seen.has(y)) { seen.add(y); queue.push(y) }
      }
    }
    if (components > 1) { procIds.push(procId); for (const n of nodes) flash.add(n) }
  }
  return { flash, procIds }
}

// Distance-from-point-to-segment (screen px) — for clicking a route to delete it.
function distToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax, dy = by - ay
  const len2 = dx * dx + dy * dy
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2))
  const cx = ax + t * dx, cy = ay + t * dy
  return Math.hypot(px - cx, py - cy)
}

interface Props {
  stations:          Record<string, Station>
  routes:            Record<string, Route>
  lotCounts:         Record<string, number>
  selectedStationId: string | null
  onSelectStation:   (id: string) => void
  tool:              MapTool
  routeProcessId:    string
}

export default function MapCanvas({
  stations, routes, lotCounts, selectedStationId, onSelectStation, tool, routeProcessId,
}: Props) {
  const createStation = useStationsStore((s) => s.create)
  const removeStation = useStationsStore((s) => s.remove)
  const createRoute   = useProcessesStore((s) => s.createRoute)
  const deleteRoute   = useProcessesStore((s) => s.deleteRoute)
  const refreshProc   = useProcessesStore((s) => s.fetchAll)
  const processes     = useProcessesStore((s) => s.processes)

  // ── Map-editing tool state ──
  const [routeFrom,  setRouteFrom]  = useState<string | null>(null)
  const [mouse,      setMouse]      = useState<{ x: number; y: number } | null>(null)   // container-relative
  const [ctxMenu,    setCtxMenu]    = useState<{ stationId: string; x: number; y: number } | null>(null)
  const [routeDelete, setRouteDelete] = useState<string | null>(null)
  const [editStation, setEditStation] = useState<string | null>(null)
  const [warnHover,   setWarnHover]   = useState(false)
  const [accHover,    setAccHover]    = useState(false)
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
  const toolRef     = useRef(tool);      toolRef.current = tool
  const vpRef       = useRef(viewport);  vpRef.current = viewport
  const routeFromRef = useRef(routeFrom); routeFromRef.current = routeFrom
  const nodeSizeRef  = useRef(0)         // set once nodeSize is known (below)
  const stationsRef  = useRef(stations); stationsRef.current = stations
  const routesRef    = useRef(routes);   routesRef.current = routes
  const didMoveRef   = useRef(false)

  const cards     = useCardsStore((s) => s.cards)
  const mapConfig = useMapSettingsStore((s) => s.settings)
  const themeMode = useThemeStore((s) => s.mode)

  const nodeSize = mapConfig
    ? (mapConfig.stationSizeUnits ?? 1) * mapConfig.pixelsPerUnit
    : DEFAULT_NODE_SIZE
  nodeSizeRef.current = nodeSize

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
    // Without a floor plan the content bounds are just the locations, so the
    // first one placed would fill ~42% of the viewport — the fit zooms until
    // that single node *is* the content. Note this is not a station-size
    // problem: nodeSize appears in both the bounds and the divisor and cancels
    // out, so drawing the station smaller would only make the camera zoom
    // further in. Cap the zoom instead. With a floor plan the rect governs and
    // no cap applies.
    let maxScale = Infinity
    if (rect) {
      minX = rect.x; minY = rect.y; maxX = rect.x + rect.w; maxY = rect.y + rect.h
    } else if (list.length > 0) {
      const pad = nodeSize * 0.6
      const xs  = list.map((s) => s.position.x)
      const ys  = list.map((s) => s.position.y)
      minX = Math.min(...xs) - pad; minY = Math.min(...ys) - pad
      maxX = Math.max(...xs) + nodeSize + pad; maxY = Math.max(...ys) + nodeSize + pad
      maxScale = MAX_FIT_NODE_PX / nodeSize
    } else {
      return
    }
    const scale = Math.min(Math.min(sw / (maxX - minX), sh / (maxY - minY)) * 0.92, maxScale)
    setViewport({
      x: -minX * scale + (sw - (maxX - minX) * scale) / 2,
      y: -minY * scale + (sh - (maxY - minY) * scale) / 2,
      scale,
    })
  }, [canvasSize, stations, floorPlanRect, nodeSize])

  // Pinch zoom. The wheel handler below covers mice and trackpads; on a phone
  // there is no wheel event at all, so without this the map simply cannot be
  // zoomed — which is most of what you do on a 6-inch screen.
  //
  // Registered imperatively for the same reason as wheel: React's touch
  // listeners are passive, and preventDefault is what stops iOS from
  // page-zooming the whole app instead of the map. Touch-only, so mouse and
  // trackpad behaviour is untouched.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    let startDist = 0
    let startScale = 1

    const dist = (t: TouchList) => Math.hypot(
      t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)
    const mid = (t: TouchList) => ({
      x: (t[0].clientX + t[1].clientX) / 2, y: (t[0].clientY + t[1].clientY) / 2 })

    const onStart = (e: TouchEvent) => {
      if (e.touches.length !== 2) return
      e.preventDefault()
      startDist = dist(e.touches)
      startScale = vpRef.current.scale
      // A second finger ends any pan in progress, so the map does not lurch
      // when the pinch finishes and one finger is still down.
      panRef.current = null
    }

    const onMove = (e: TouchEvent) => {
      if (e.touches.length !== 2 || !startDist) return
      e.preventDefault()
      const m = mid(e.touches)
      const rect = el.getBoundingClientRect()
      const mx = m.x - rect.left
      const my = m.y - rect.top
      setViewport((v) => {
        const target = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM,
          startScale * (dist(e.touches) / startDist)))
        // Keep the point between the fingers stationary — the same anchoring
        // the wheel handler does around the cursor.
        const dx = (mx - v.x) * (target / v.scale - 1)
        const dy = (my - v.y) * (target / v.scale - 1)
        return clampVP({ x: v.x - dx, y: v.y - dy, scale: target })
      })
    }

    const onEnd = (e: TouchEvent) => { if (e.touches.length < 2) startDist = 0 }

    el.addEventListener('touchstart', onStart, { passive: false })
    el.addEventListener('touchmove',  onMove,  { passive: false })
    el.addEventListener('touchend',   onEnd)
    el.addEventListener('touchcancel', onEnd)
    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchmove', onMove)
      el.removeEventListener('touchend', onEnd)
      el.removeEventListener('touchcancel', onEnd)
    }
  }, [])

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

  // Screen (container-relative) → world coordinates
  const toWorld = (sx: number, sy: number) => {
    const vp = vpRef.current
    return { x: (sx - vp.x) / vp.scale, y: (sy - vp.y) / vp.scale }
  }

  // A left-click (no drag) on the empty canvas runs the active tool.
  const handleCanvasClick = useCallback((sx: number, sy: number) => {
    const t = toolRef.current
    setCtxMenu(null)
    if (t === 'location') {
      const w = toWorld(sx, sy)
      const half = nodeSizeRef.current / 2
      const n = Object.keys(stationsRef.current).length + 1
      createStation({
        name: `Location ${n}`, description: '', adapterType: null, adapterConfig: {},
        color: null, icon: null,
        position: { x: Math.round(w.x - half), y: Math.round(w.y - half), width: 60, height: 60 },
      } as Omit<Station, '_id' | 'createdAt' | 'updatedAt'>)
        .then((s) => setEditStation(s._id))   // open the edit modal to name it right away
        .catch(() => {})
      return
    }
    if (t === 'route') {
      // Clicked empty space: hit-test routes (delete) else abort the in-progress route.
      const half = nodeSizeRef.current / 2
      const vp = vpRef.current
      let hit: string | null = null
      let best = 9
      for (const [id, r] of Object.entries(routesRef.current)) {
        const a = stationsRef.current[r.load], b = stationsRef.current[r.unload]
        if (!a || !b) continue
        const ax = (a.position.x + half) * vp.scale + vp.x
        const ay = (a.position.y + half) * vp.scale + vp.y
        const bx = (b.position.x + half) * vp.scale + vp.x
        const by = (b.position.y + half) * vp.scale + vp.y
        const d = distToSegment(sx, sy, ax, ay, bx, by)
        if (d < best) { best = d; hit = id }
      }
      // Only a route hit does something; empty clicks leave the in-progress
      // route attached to the cursor (Esc or clicking the source aborts it).
      if (hit) setRouteDelete(hit)
    }
  }, [createStation])

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return
    setCtxMenu(null)
    didMoveRef.current = false
    panRef.current = { startX: e.clientX, startY: e.clientY, vpX: vpRef.current.x, vpY: vpRef.current.y }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }, [])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    // A pinch cancels panRef, so this returns early for the rest of the
    // gesture instead of dragging the map along with the zoom.
    if (!panRef.current) return
    const dx = e.clientX - panRef.current.startX
    const dy = e.clientY - panRef.current.startY
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) didMoveRef.current = true
    setViewport((v) => clampVP({ ...v, x: panRef.current!.vpX + dx, y: panRef.current!.vpY + dy }))
  }, [])

  // While drawing a route, follow the cursor at the window level — the PixiJS
  // canvas swallows hover moves, so a container-only listener drops the line.
  useEffect(() => {
    if (tool !== 'route' || !routeFrom) { setMouse(null); return }
    const onMove = (e: PointerEvent) => {
      const el = containerRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      setMouse({ x: e.clientX - r.left, y: e.clientY - r.top })
    }
    window.addEventListener('pointermove', onMove)
    return () => window.removeEventListener('pointermove', onMove)
  }, [tool, routeFrom])

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    const wasClick = !!panRef.current && !didMoveRef.current
    panRef.current = null
    if (wasClick && toolRef.current !== 'select') {
      const el = containerRef.current
      if (el) { const r = el.getBoundingClientRect(); handleCanvasClick(e.clientX - r.left, e.clientY - r.top) }
    }
  }, [handleCanvasClick])

  // Route tool: click a station to lock it as source, then a second to connect.
  const handleRouteAnchor = useCallback((stationId: string) => {
    const from = routeFromRef.current
    if (!from) { setRouteFrom(stationId); return }       // lock source
    if (from === stationId) { setRouteFrom(null); return } // click same → abort
    if (routeProcessId) {
      createRoute({ processId: routeProcessId, load: from, unload: stationId, quantity: 1 }).catch(() => {})
    }
    setRouteFrom(null)                                     // done → ready for the next
  }, [routeProcessId, createRoute])

  // Escape aborts an in-progress route / closes menus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setRouteFrom(null); setCtxMenu(null); setRouteDelete(null); setEditStation(null) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Reset transient tool state when the tool changes.
  useEffect(() => { setRouteFrom(null); setCtxMenu(null) }, [tool])

  const confirmDeleteStation = useCallback(async (id: string) => {
    setCtxMenu(null)
    await removeStation(id)
    await refreshProc()   // drop cascade-deleted routes from the board/map
  }, [removeStation, refreshProc])

  const confirmDeleteRoute = useCallback(async () => {
    if (routeDelete) await deleteRoute(routeDelete)
    setRouteDelete(null)
  }, [routeDelete, deleteRoute])

  // Kept out of the heat ramp: storage (meant to fill up) and integration
  // locations (the boundary of the business). Both would otherwise flatten the
  // scale for the stations that matter.
  //
  // Storage is the location's own property, not its shape in the graph. It was
  // inferred as "receives routes, sends none", which swallowed every leaf that
  // does real work — a final test bench, the last cell on a line — and hid a
  // queue building up exactly where it matters most.
  const warehouses = React.useMemo(() => {
    const set = new Set<string>()
    for (const s of Object.values(stations)) {
      if (s.isStorage || isIntegrationStation(s)) set.add(s._id)
    }
    return set
  }, [stations])

  const wipRatios = React.useMemo(() => {
    const wipMap: Record<string, number> = {}
    for (const card of Object.values(cards)) {
      for (const [sid, bin] of Object.entries(card.bins)) {
        // Finished goods pile up in a warehouse by design — heat is about work
        // piling up where it shouldn't, so warehouses are left out of the ramp
        // (and out of the max, which would otherwise flatten every other station).
        if (bin.count > 0 && !warehouses.has(sid)) wipMap[sid] = (wipMap[sid] ?? 0) + bin.count
      }
    }
    const maxWip = Math.max(1, ...Object.values(wipMap))
    const result: Record<string, number> = {}
    for (const sid of Object.keys(wipMap)) result[sid] = wipMap[sid] / maxWip
    return result
  }, [cards, warehouses])

  const stationList = Object.values(stations)
  const routeList   = Object.values(routes)
  const isEmpty     = stationList.length === 0
  const isolated = React.useMemo(() => isolatedProcessStations(routes), [routes])
  // Stations where the weights deliver more per cycle than the next step takes:
  // work piles up structurally, and the surplus usually wants a warehouse.
  const accumulations = React.useMemo(
    () => findAccumulations(
      Object.values(routes).map((r) => ({
        load: r.load, unload: r.unload, quantity: r.quantity, processId: r.processId,
      })),
      Object.keys(stations)),
    [routes, stations])
  // Storage and boundary locations are *meant* to fill up — a dock or a shelf
  // accumulating finished goods is the system working, not a problem to route
  // around.
  const accumulationIds = React.useMemo(
    () => new Set(accumulations
      .map((a) => a.stationId)
      .filter((id) => !(stations[id] && (stations[id].isStorage || isIntegrationStation(stations[id]))))),
    [accumulations, stations])
  const isolatedNames = isolated.procIds.map((id) => processes[id]?.name).filter(Boolean) as string[]

  // Raw pixelsPerUnit is correct when floor plan is rendered at mapWidthPx canvas pixels
  // (which equals the settings-preview CSS display width, the frame ppu was calibrated in).
  const ppu = mapConfig?.pixelsPerUnit ?? DEFAULT_NODE_SIZE

  // Which way work crosses each integration boundary, read from the drawn
  // links: an outgoing route places orders that pull work through (↓), an incoming one
  // receives finished goods (↑). Drives the arrows on the partner's mark.
  const boundaryFlows = React.useMemo(() => {
    const flows: Record<string, 'pull' | 'out' | 'both'> = {}
    for (const s of Object.values(stations)) {
      if (!isIntegrationStation(s)) continue
      const pull = Object.values(routes).some((r) => r.load === s._id)
      const out  = Object.values(routes).some((r) => r.unload === s._id)
      if (pull || out) flows[s._id] = pull && out ? 'both' : pull ? 'pull' : 'out'
    }
    return flows
  }, [stations, routes])

  // Each station's measured cycle time, compressed by one shared factor so the
  // ratios between them survive — that is what makes a bottleneck visible as
  // a slow heartbeat instead of a number in a table.
  const cyclePulses = useCyclePulses(!isEmpty)

  return (
    <div
      ref={containerRef}
      style={{
        flex:     1,
        overflow: 'hidden',
        cursor:   tool !== 'select' ? 'crosshair' : 'default',
        position: 'relative',
        // The map owns every touch gesture on this surface. Without it the
        // browser claims one-finger drags for scrolling and two-finger ones
        // for page zoom, and neither ever reaches the handlers above. Governs
        // touch only — mouse and trackpad are unaffected.
        touchAction: 'none',
      }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
      onContextMenu={(e) => { if (tool !== 'select') e.preventDefault() }}
    >
      {/* Same exposure as the landing demo: without WebGL, Pixi throws and the
          whole map view is replaced by an error. The station tiles are an HTML
          overlay, so the map stays usable — you lose the floor plan, the routes
          and the heat, which is worth saying out loud rather than silently. */}
      {!hasWebGL() && (
        <div style={{
          position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
          zIndex: 40, maxWidth: 520, background: color.glass,
          border: `1px solid ${color.glassBorder}`, borderRadius: 4,
          padding: '8px 14px', fontSize: 12, color: color.glassText,
          lineHeight: 1.5, textAlign: 'center',
        }}>
          This browser has no WebGL, so the floor plan, routes and heatmap can&rsquo;t be drawn.
          Locations and lot counts still work. Enabling hardware acceleration — or allowing WebGL
          if a privacy extension blocks it — restores the full map.
        </div>
      )}

      {/* ── PixiJS: floor plan + heatmap + edges ── */}
      {hasWebGL() && canvasSize.w > 0 && (
        <Stage
          width={canvasSize.w}
          height={canvasSize.h}
          options={{
            background:  CANVAS_BG[themeMode],
            antialias:   true,
            resolution:  window.devicePixelRatio || 1,
            autoDensity: true,
          }}
        >
          <StageBackground color={CANVAS_BG[themeMode]} />
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

            {routeList.map((route) => {
              // Either end bound to a partner → a boundary link, not flow.
              const bound = [stations[route.load], stations[route.unload]]
                .find((s) => s && isIntegrationStation(s))
              const tint = bound
                ? hexToPixi(integrationProvider(bound.integrationProvider)?.color)
                : undefined
              return (
                <RouteEdge
                  key={route._id}
                  route={route}
                  fromStation={stations[route.load]}
                  toStation={stations[route.unload]}
                  nodeSize={nodeSize}
                  boundaryTint={tint}
                />
              )
            })}

            {/* Lots in transit — drawn over the edges they run along, and
                inside this Container so they pan and zoom with the floor plan. */}
            <MotionLayer
              stations={stations}
              routes={routes}
              nodeSize={nodeSize}
              pixelsPerUnit={ppu}
              unit={mapConfig?.unit ?? 'm'}
            />
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
            tool={tool}
            routeArmed={routeFrom === station._id}
            flashing={(warnHover && isolated.flash.has(station._id))
                      || (accHover && accumulationIds.has(station._id))}
            cyclePeriodMs={cyclePulses.periodMs[station._id]}
            boundaryFlow={boundaryFlows[station._id]}
            onSelect={() => onSelectStation(station._id)}
            onRouteAnchor={() => handleRouteAnchor(station._id)}
            onContextMenu={(cx, cy) => setCtxMenu({ stationId: station._id, x: cx, y: cy })}
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

      {/* Cycle legend — without the factor, "3 seconds" is meaningless, and
          without the in-step verdict the rhythm is decoration. */}
      {cyclePulses.measured > 0 && <CycleLegend pulses={cyclePulses} />}

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
            background:   color.glass,
            border:       `1px solid ${color.glassBorder}`,
            borderRadius: 4,
            color:        color.glassText,
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
            No locations yet — add one with the location tool, or in Settings
          </div>
        </div>
      )}

      {/* Warnings — hover one to flash the stations it is about */}
      {(isolated.procIds.length > 0 || accumulations.length > 0) && (
        <div style={{ position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)',
                      display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center',
                      maxWidth: '72%' }}>
          {accumulations.length > 0 && (
            <div onMouseEnter={() => setAccHover(true)} onMouseLeave={() => setAccHover(false)}
                 style={warnBarStyle}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                   strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <path d="M3 3v16a2 2 0 0 0 2 2h16" /><path d="M7 15v-4M12 15V8M17 15v-6" />
              </svg>
              {accumulations.length === 1
                ? `${stations[accumulations[0].stationId]?.name ?? '—'} accumulates ${accumulations[0].surplus} unit${accumulations[0].surplus !== 1 ? 's' : ''} per cycle — ${accumulations[0].produced} arrive, ${accumulations[0].consumed} move on.`
                : `${accumulations.length} locations accumulate work every cycle: ${accumulations.map((a) => `${stations[a.stationId]?.name ?? '—'} +${a.surplus}`).join(', ')}.`}
              <span style={{ color: color.textSecondary }}>Route the surplus to a warehouse.</span>
            </div>
          )}
          {isolated.procIds.length > 0 && (
            <div onMouseEnter={() => setWarnHover(true)} onMouseLeave={() => setWarnHover(false)}
                 style={warnBarStyle}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                   strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
                <path d="M12 9v4" /><path d="M12 17h.01" />
              </svg>
              {isolatedNames.length <= 1
                ? `Warning — the process “${isolatedNames[0] ?? '—'}” contains isolated subgraphs.`
                : `Warning — the processes ${isolatedNames.map((n) => `“${n}”`).join(', ')} contain isolated subgraphs.`}
              <span style={{ color: color.textSecondary }}>Hover to highlight.</span>
            </div>
          )}
        </div>
      )}

      {/* Tool hint bar */}
      {tool !== 'select' && (
        <div style={{
          position: 'absolute', top: 14, left: '50%', transform: 'translateX(-50%)',
          background: color.glass, borderRadius: 6, padding: '6px 12px', fontSize: 12,
          pointerEvents: 'none', fontFamily: 'Inter, system-ui, sans-serif',
          border: `1px solid ${tool === 'route' ? '#7C3AED66' : '#D85A3066'}`,
          color: tool === 'route' ? 'var(--tk-hint-route)' : 'var(--tk-hint-location)',
        }}>
          {tool === 'location'
            ? 'Click to add a location · drag one to move · right-click to edit or delete'
            : routeFrom
              ? 'Click a target location to connect · Esc or click the source to cancel'
              : 'Click a source location to start a route · click a route to delete it'}
        </div>
      )}

      {/* Route rubber-band from the locked source to the cursor */}
      {tool === 'route' && routeFrom && mouse && stations[routeFrom] && (() => {
        const src = stations[routeFrom]
        const sx = (src.position.x + nodeSize / 2) * viewport.scale + viewport.x
        const sy = (src.position.y + nodeSize / 2) * viewport.scale + viewport.y
        const ang = (Math.atan2(mouse.y - sy, mouse.x - sx) * 180) / Math.PI
        return (
          <svg width={canvasSize.w} height={canvasSize.h}
               style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            <line x1={sx} y1={sy} x2={mouse.x} y2={mouse.y} stroke="#A78BFA" strokeWidth={2} strokeDasharray="6 5" />
            <polygon points="0,-5 10,0 0,5" fill="#A78BFA"
                     transform={`translate(${mouse.x},${mouse.y}) rotate(${ang})`} />
          </svg>
        )
      })()}

      {/* Right-click station context menu */}
      {ctxMenu && stations[ctxMenu.stationId] && (() => {
        const rect = containerRef.current?.getBoundingClientRect()
        const mx = ctxMenu.x - (rect?.left ?? 0)
        const my = ctxMenu.y - (rect?.top ?? 0)
        return (
          <>
            <div style={{ position: 'fixed', inset: 0, zIndex: 60 }} onPointerDown={() => setCtxMenu(null)} />
            <div onPointerDown={(e) => e.stopPropagation()}
                 style={{ position: 'absolute', left: mx, top: my, zIndex: 61, minWidth: 140,
                          background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: 6,
                          boxShadow: shadow.md, padding: 4 }}>
              <div style={{ padding: '5px 10px', fontSize: 11, color: color.textDim,
                            fontFamily: 'JetBrains Mono, monospace', borderBottom: `1px solid ${color.border}`, marginBottom: 2 }}>
                {stations[ctxMenu.stationId].name}
              </div>
              <button style={CTX_ITEM} onClick={() => { setEditStation(ctxMenu.stationId); setCtxMenu(null) }}>Edit…</button>
              <button style={{ ...CTX_ITEM, color: '#E24B4A' }} onClick={() => confirmDeleteStation(ctxMenu.stationId)}>Delete</button>
            </div>
          </>
        )
      })()}

      {/* Delete-route confirm */}
      {routeDelete && (() => {
        const r = routes[routeDelete]
        const a = r ? stations[r.load] : undefined
        const b = r ? stations[r.unload] : undefined
        return (
          <div onPointerDown={() => setRouteDelete(null)} style={MODAL_BG}>
            <div onPointerDown={(e) => e.stopPropagation()} style={MODAL_CARD}>
              <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>Delete route?</div>
              <div style={{ fontSize: 13, color: color.textSecondary, fontFamily: 'JetBrains Mono, monospace' }}>
                {a?.name ?? '?'} → {b?.name ?? '?'}
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button style={BTN_SEC} onClick={() => setRouteDelete(null)}>Cancel</button>
                <button style={BTN_DANGER} onClick={confirmDeleteRoute}>Delete</button>
              </div>
            </div>
          </div>
        )
      })()}

      {/* Station edit modal */}
      {editStation && stations[editStation] && (
        <MapStationEditModal stationId={editStation} onClose={() => setEditStation(null)} />
      )}
    </div>
  )
}

const warnBarStyle: React.CSSProperties = {
  background: color.glass, border: '1px solid #EF9F2766', borderRadius: 6,
  padding: '7px 14px', display: 'flex', alignItems: 'center', gap: 8, cursor: 'default',
  fontSize: 12.5, color: color.warnText, fontFamily: 'Inter, system-ui, sans-serif',
}

const CTX_ITEM: React.CSSProperties = {
  display: 'block', width: '100%', textAlign: 'left', background: 'transparent', border: 'none',
  color: color.textPrimary, padding: '7px 10px', fontSize: 13, cursor: 'pointer', borderRadius: 4,
  fontFamily: 'Inter, system-ui, sans-serif',
}
const MODAL_BG: React.CSSProperties = {
  position: 'absolute', inset: 0, zIndex: 70, background: color.backdrop,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
}
const MODAL_CARD: React.CSSProperties = {
  background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: 8, padding: 20,
  width: 300, display: 'flex', flexDirection: 'column', gap: 12, boxShadow: shadow.lg,
}
const BTN_SEC: React.CSSProperties = {
  padding: '6px 14px', background: 'transparent', border: `1px solid ${color.border}`, borderRadius: 4,
  color: color.textSecondary, cursor: 'pointer', fontSize: 12,
}
const BTN_DANGER: React.CSSProperties = {
  padding: '6px 14px', background: '#E24B4A', border: 'none', borderRadius: 4,
  color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 600,
}

// ─── Stage background ─────────────────────────────────────────────────────────

// Stage `options` only apply at construction; this updates the renderer when
// the day/night theme flips without recreating the canvas.
function StageBackground({ color: bg }: { color: number }) {
  const app = useApp()
  useEffect(() => { app.renderer.background.color = bg }, [app, bg])
  return null
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

// Station busyness gets its own violet ramp (BRANDING.md §3): warm hues are
// reserved for andon status, so heat must never read as an alarm.
const HEAT_RAMP = [0xEEEDFE, 0xCECBF6, 0xAFA9EC, 0x7F77DD, 0x534AB7, 0x26215C] as const

function heatTint(load: number): number {
  const i = Math.min(HEAT_RAMP.length - 1, Math.max(0, Math.floor(load * HEAT_RAMP.length)))
  return HEAT_RAMP[i]
}

function HeatBlob({
  x, y, ratio, nodeSize,
}: { x: number; y: number; ratio: number; nodeSize: number }) {
  const radius = nodeSize * 0.6 + ratio * nodeSize * 0.8
  const alpha  = 0.16 + ratio * 0.26

  const draw = useCallback((g: PIXI.Graphics) => {
    g.clear()
    g.beginFill(heatTint(ratio * 0.7), alpha * 0.5)   // outer glow, one step cooler
    g.drawCircle(0, 0, radius * 1.4)
    g.endFill()
    g.beginFill(heatTint(ratio), alpha)
    g.drawCircle(0, 0, radius)
    g.endFill()
  }, [radius, alpha, ratio])

  return <Graphics x={x} y={y} draw={draw} />
}

// ─── Scale bar ────────────────────────────────────────────────────────────────

/** What the pulsing means, in two lines.
 *
 *  The compression factor is not decoration: a station pulsing every 3 s is
 *  really running a 300 s cycle time, and without the ×100 on screen someone will
 *  eventually read the rhythm as the literal cycle time. The in-step verdict
 *  is judged on the true cycle times, never the clamped display periods. */
function CycleLegend({ pulses }: { pulses: CyclePulses }) {
  const slowest = pulses.slowestSec
  const human = slowest == null ? null
    : slowest >= 60 ? `${(slowest / 60).toFixed(1)} min` : `${slowest.toFixed(0)} s`
  return (
    <div style={{
      // Clear of the fit-view button, which owns the bottom-right corner.
      position: 'absolute', bottom: 16, right: 56,
      background: color.glass, border: `1px solid ${color.glassBorder}`,
      borderRadius: 4, padding: '5px 9px 6px', pointerEvents: 'none', userSelect: 'none',
      fontFamily: '"JetBrains Mono", monospace', fontSize: 10,
      color: color.glassText, letterSpacing: '0.05em', lineHeight: 1.7, textAlign: 'right',
    }}>
      <div>CYCLE PULSE ×{pulses.compression}</div>
      <div style={{ opacity: 0.85 }}>
        {pulses.measured} measured · {pulses.synchronous ? 'IN STEP' : 'OUT OF STEP'}
        {human ? ` · slowest ${human}` : ''}
      </div>
    </div>
  )
}

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
      left:          60,   /* clear of the fixed day/night toggle in the corner */
      background:    color.glass,
      border:        `1px solid ${color.glassBorder}`,
      borderRadius:  4,
      padding:       '5px 8px 6px',
      pointerEvents: 'none',
      userSelect:    'none',
    }}>
      <div style={{
        fontSize:      10,
        color:         color.glassText,
        textAlign:     'center',
        marginBottom:  3,
        fontFamily:    '"JetBrains Mono", monospace',
        letterSpacing: '0.05em',
      }}>
        {count} {unit}
      </div>
      <svg width={barLength + 2} height={AH * 2 + 4} style={{ display: 'block', overflow: 'visible' }}>
        <g transform={`translate(0,${AH + 2})`} stroke={color.textPrimary} fill={color.textPrimary}>
          <polygon points={`0,0 ${AL},${-AH} ${AL},${AH}`} />
          <line x1={AL} y1={0} x2={barLength - AL} y2={0} strokeWidth={1.5} />
          <polygon points={`${barLength},0 ${barLength - AL},${-AH} ${barLength - AL},${AH}`} />
        </g>
      </svg>
    </div>
  )
}
