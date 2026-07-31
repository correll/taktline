import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Stage, Container, Graphics } from '@pixi/react'
import * as PIXI from 'pixi.js'
import type { Route, Station } from '../../models'
import RouteEdge from '../map/RouteEdge'
import { getStationIcon } from '../map/StationNode'
import { processColorsFor, hexToInt } from '../../domain/processColors'
import { integrationProvider } from '../../domain/integrations'
import { useThemeStore } from '../../store/theme.store'
import { hasWebGL } from './webgl'
import PixiBoundary from './PixiBoundary'

// Generic animated flow scene, built from the SAME primitives the app's map
// uses: RouteEdge (animated dashes, halo, weight badges), the station-tile
// look, and the violet WIP heat blobs. Purely presentational — the parent
// drives `wip` from whatever simulation it likes. Used by the landing hero
// and the user-manual figures.

export interface SceneStation {
  id: string
  name: string
  icon: string
  color: string
  x: number
  y: number
  /** An integration partner: drawn as its letter mark in the partner's colour
   *  rather than an icon, because on a map of a shop floor it should read as a
   *  foreign object — which is exactly what it is. */
  provider?: string
  /** Measured beat, time-compressed, in ms. The station pulses at it, the way
   *  the real map shows whether a line is in step. */
  pulseMs?: number
}

export interface SceneEdge {
  from: string
  to: string
  qty: number
  /** Which value stream this route belongs to. Two lines over one floor is the
   *  case the map exists for, so the demo draws it: each process takes its own
   *  colour, and where both connect the same pair the lines are shifted apart
   *  — drawn on top of each other the second one is invisible, and so is the
   *  fact that there are two. */
  process?: string
}

export type Wip = Record<string, number>

interface Props {
  stations: SceneStation[]
  edges: SceneEdge[]
  wip: Wip
  worldW: number
  worldH: number
  node?: number
  showHeat?: boolean
  maxWip?: number
  /** Names for the value streams, keyed by the ids used on the edges. With
   *  more than one, a legend is drawn: identity must never rest on hue alone,
   *  and two unexplained colours read as decoration rather than as two lines. */
  processNames?: Record<string, string>
}

const CANVAS_BG: Record<'night' | 'day', number> = { night: 0x121110, day: 0xF7F6F2 }

const stationOf = (s: SceneStation, node: number): Station => ({
  _id: s.id, name: s.name, position: { x: s.x, y: s.y, width: node, height: node },
  adapterType: null, adapterConfig: {}, description: '', color: s.color, icon: s.icon,
  createdAt: '', updatedAt: '',
} as unknown as Station)

const routeOf = (e: SceneEdge, i: number): Route => ({
  _id: `scene-${i}`, processId: e.process ?? 'scene', load: e.from, unload: e.to,
  quantity: e.qty, createdAt: '', updatedAt: '',
} as unknown as Route)

/** Lane offsets and badge stagger for routes sharing a pair of stations — the
 *  same treatment MapCanvas gives them, so the demo and the product agree. */
function laneLayout(edges: SceneEdge[], node: number) {
  const byPair = new Map<string, number[]>()
  edges.forEach((e, i) => {
    const key = [e.from, e.to].sort().join('|')
    byPair.set(key, [...(byPair.get(key) ?? []), i])
  })
  const gap = Math.max(3, node * 0.055)
  const spacing = Math.max(9, node * 0.13) * 2.4
  const lane: Record<number, number> = {}
  const badge: Record<number, number> = {}
  for (const idxs of byPair.values()) {
    idxs.forEach((i, k) => { lane[i] = (k - (idxs.length - 1) / 2) * gap })
    const weighted = idxs.filter((i) => edges[i].qty > 1)
    if (weighted.length > 1) {
      weighted.forEach((i, k) => { badge[i] = (k - (weighted.length - 1) / 2) * spacing })
    }
  }
  return { lane, badge }
}

// Same violet ramp as the map (BRANDING.md §3).
const HEAT_RAMP = [0xEEEDFE, 0xCECBF6, 0xAFA9EC, 0x7F77DD, 0x534AB7, 0x26215C] as const
const heatTint = (load: number) =>
  HEAT_RAMP[Math.min(HEAT_RAMP.length - 1, Math.max(0, Math.floor(load * HEAT_RAMP.length)))]

function HeatBlob({ x, y, ratio, node }: { x: number; y: number; ratio: number; node: number }) {
  const radius = node * 0.6 + ratio * node * 0.9
  const alpha = 0.15 + ratio * 0.3
  const draw = useCallback((g: PIXI.Graphics) => {
    g.clear()
    g.beginFill(heatTint(ratio * 0.7), alpha * 0.5)
    g.drawCircle(0, 0, radius * 1.4)
    g.endFill()
    g.beginFill(heatTint(ratio), alpha)
    g.drawCircle(0, 0, radius)
    g.endFill()
  }, [radius, alpha, ratio])
  return <Graphics x={x} y={y} draw={draw} />
}

function Tile({ s, count, scale, node }: { s: SceneStation; count: number; scale: number; node: number }) {
  const Icon = getStationIcon(s.icon)
  const partner = integrationProvider(s.provider)
  const tint = partner?.color ?? s.color
  const sz = node * scale
  return (
    <div style={{
      position: 'absolute', left: s.x * scale, top: s.y * scale, width: sz, height: sz,
      borderRadius: Math.max(4, sz * 0.08),
      border: `1.5px solid ${tint}`,
      background: `rgba(var(--tk-map-node-bg-rgb), 0.9)`,
      boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      gap: Math.max(1, sz * 0.04), overflow: 'hidden', pointerEvents: 'none',
    }}>
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: Math.max(3, sz * 0.05),
        background: tint, opacity: 0.85,
      }} />
      {/* The station's measured beat, time-compressed. Low contrast on purpose:
          this runs on a wall display for a whole shift, so it has to be
          readable at a glance and invisible to someone working next to it. */}
      {s.pulseMs != null && (
        <div aria-hidden className="tk-cycle-pulse" style={{
          position: 'absolute', inset: 0, borderRadius: 'inherit',
          boxShadow: `inset 0 0 0 ${Math.max(1.5, sz * 0.028)}px ${tint}`,
          animationDuration: `${s.pulseMs}ms`, pointerEvents: 'none',
        }} />
      )}
      {partner ? (
        // Letters, not logos: partner artwork is trademarked, unreadable at
        // this size, and would need re-licensing at every rebrand.
        <div style={{
          flexShrink: 0, width: sz * 0.44, height: sz * 0.44,
          borderRadius: Math.max(3, sz * 0.09), background: partner.color,
          color: partner.ink, display: 'flex', alignItems: 'center',
          justifyContent: 'center', fontFamily: 'Inter, system-ui, sans-serif',
          fontWeight: 700, lineHeight: 1,
          fontSize: sz * (partner.mark.length > 1 ? 0.18 : 0.24),
        }}>{partner.mark}</div>
      ) : (
        <Icon size={Math.max(12, sz * 0.4)} color={s.color} strokeWidth={1.5} />
      )}
      <span style={{
        fontSize: Math.max(8, Math.min(12, sz * 0.12)), fontWeight: 600,
        color: 'var(--tk-map-node-text)', fontFamily: 'Inter, system-ui, sans-serif',
        textAlign: 'center', lineHeight: 1.15, maxWidth: sz - 8, padding: '0 3px',
      }}>
        {s.name}
      </span>
      {count > 0 && (
        <div style={{
          position: 'absolute', top: Math.max(3, sz * 0.05) + 3, right: 3,
          background: '#639922', color: '#fff',
          fontSize: Math.max(8, Math.min(10, sz * 0.11)), fontWeight: 700,
          fontFamily: '"JetBrains Mono", monospace', borderRadius: 999,
          padding: '1px 5px', minWidth: 16, textAlign: 'center', lineHeight: 1.4,
        }}>
          {count}
        </div>
      )}
    </div>
  )
}

/** A route touching a partner is a boundary link, not flow: it wears the
 *  partner's colour rather than its process's. */
function boundaryTint(e: SceneEdge, stations: SceneStation[]): number | undefined {
  const end = stations.find((s) => (s.id === e.from || s.id === e.to) && s.provider)
  const p = integrationProvider(end?.provider)
  if (!p) return undefined
  const m = /^#?([0-9a-f]{6})$/i.exec(p.color.trim())
  return m ? parseInt(m[1], 16) : undefined
}

const hex = (n: number) => `#${n.toString(16).padStart(6, '0')}`

/** The same scene, drawn without a GPU.
 *
 *  Pixi throws outright when WebGL is unavailable, and there is no canvas
 *  renderer to fall back to, so this is not a graceful degradation of the
 *  Stage — it is a second drawing of the same picture in SVG. It keeps the
 *  landing page meaningful for crawlers and for anyone whose browser blocks
 *  WebGL, instead of replacing the front door with an error.
 *
 *  Deliberately still: the animation was never the message. The shape of the
 *  line and where work piles up is.
 */
function StaticScene({ stations, edges, wip, worldW, worldH, node, showHeat, maxWip, mode }: {
  stations: SceneStation[]; edges: SceneEdge[]; wip: Wip
  worldW: number; worldH: number; node: number
  showHeat: boolean; maxWip: number; mode: 'night' | 'day'
}) {
  const palette = processColorsFor(
    [...new Set(edges.map((e) => e.process ?? 'scene'))], mode)
  const lanes = laneLayout(edges, node)
  const at = (id: string) => {
    const s = stations.find((x) => x.id === id)
    return s ? { x: s.x + node / 2, y: s.y + node / 2 } : null
  }
  return (
    <svg
      viewBox={`0 0 ${worldW} ${worldH}`}
      width="100%" height="100%" role="img"
      aria-label="A production line: stations connected by routes, shaded where work is piling up."
      style={{ position: 'absolute', inset: 0, background: hex(CANVAS_BG[mode]) }}
    >
      {showHeat && stations.map((s) => {
        const ratio = Math.min(1, (wip[s.id] ?? 0) / maxWip)
        if (ratio === 0) return null
        return (
          <g key={s.id}>
            <circle cx={s.x + node / 2} cy={s.y + node / 2} r={node * 1.15}
                    fill={hex(heatTint(ratio * 0.7))} opacity={0.28} />
            <circle cx={s.x + node / 2} cy={s.y + node / 2} r={node * 0.78}
                    fill={hex(heatTint(ratio))} opacity={0.5} />
          </g>
        )
      })}
      {edges.map((e, i) => {
        const a0 = at(e.from), b0 = at(e.to)
        if (!a0 || !b0) return null
        // Shift routes that share a pair apart, in a canonical frame so a route
        // and its reverse move to opposite sides rather than each to its left.
        const off = lanes.lane[i] ?? 0
        const dx = b0.x - a0.x, dy = b0.y - a0.y
        const len = Math.hypot(dx, dy) || 1
        const flip = e.from > e.to ? -1 : 1
        const nx = (-dy / len) * off * flip, ny = (dx / len) * off * flip
        const a = { x: a0.x + nx, y: a0.y + ny }, b = { x: b0.x + nx, y: b0.y + ny }
        const partnerEnd = boundaryTint(e, stations)
        const ink = partnerEnd != null
          ? hex(partnerEnd)
          : (palette[e.process ?? 'scene'] ?? (mode === 'night' ? '#B4B1A9' : '#3D3B37'))
        const ang = Math.atan2(b.y - a.y, b.x - a.x)
        const tipX = b.x - Math.cos(ang) * 6, tipY = b.y - Math.sin(ang) * 6
        return (
          <g key={i}>
            <line x1={a.x} y1={a.y} x2={tipX} y2={tipY}
                  stroke={ink} strokeWidth={2} strokeDasharray="10 6" opacity={0.9} />
            <polygon
              points={`${b.x},${b.y} ${b.x - 10 * Math.cos(ang) + 5 * Math.sin(ang)},${b.y - 10 * Math.sin(ang) - 5 * Math.cos(ang)} ${b.x - 10 * Math.cos(ang) - 5 * Math.sin(ang)},${b.y - 10 * Math.sin(ang) + 5 * Math.cos(ang)}`}
              fill={ink} />
            {e.qty !== 1 && (
              <>
                <circle cx={(a.x + b.x) / 2 + (lanes.badge[i] ?? 0) * (dx / len)}
                        cy={(a.y + b.y) / 2 + (lanes.badge[i] ?? 0) * (dy / len)} r={node * 0.14}
                        fill={mode === 'night' ? '#1D1C1A' : '#FFFFFF'} stroke={ink} strokeWidth={1.2} />
                <text x={(a.x + b.x) / 2 + (lanes.badge[i] ?? 0) * (dx / len)}
                      y={(a.y + b.y) / 2 + (lanes.badge[i] ?? 0) * (dy / len)} textAnchor="middle"
                      dominantBaseline="central" fontSize={node * 0.15} fontWeight={600}
                      fill={mode === 'night' ? '#EFEDE7' : '#1A1917'}
                      fontFamily="Inter, system-ui, sans-serif">{e.qty}</text>
              </>
            )}
          </g>
        )
      })}
    </svg>
  )
}


export default function FlowScene({
  stations, edges, wip, worldW, worldH, node = 92, showHeat = true, maxWip = 6,
  processNames,
}: Props) {
  const mode = useThemeStore((s) => s.mode)
  const [width, setWidth] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const stationModels = React.useMemo(
    () => Object.fromEntries(stations.map((s) => [s.id, stationOf(s, node)])), [stations, node])
  const routeModels = React.useMemo(() => edges.map(routeOf), [edges])
  // One colour per value stream, de-collided the same way the map does it.
  const palette = React.useMemo(
    () => processColorsFor([...new Set(edges.map((e) => e.process ?? 'scene'))], mode),
    [edges, mode])
  const lanes = React.useMemo(() => laneLayout(edges, node), [edges, node])

  const scale = width > 0 ? width / worldW : 0
  const height = worldH * scale

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%', height: height || worldH / 2 }}>
      {scale > 0 && (
        <>
          {/* Pixi throws when it cannot get a WebGL context, and that exception
              takes the whole page down — which is how the public landing page
              broke for a crawler. Ask first. */}
          {!hasWebGL() ? (
            <StaticScene
              stations={stations} edges={edges} wip={wip}
              worldW={worldW} worldH={worldH} node={node}
              showHeat={showHeat} maxWip={maxWip} mode={mode}
            />
          ) : (
          <PixiBoundary fallback={
            <StaticScene
              stations={stations} edges={edges} wip={wip}
              worldW={worldW} worldH={worldH} node={node}
              showHeat={showHeat} maxWip={maxWip} mode={mode}
            />
          }>
          <Stage
            key={mode}   /* theme flip recreates the canvas with the right background */
            width={width}
            height={height}
            options={{ background: CANVAS_BG[mode], antialias: true,
                       resolution: window.devicePixelRatio || 1, autoDensity: true }}
          >
            <Container scale={scale}>
              {showHeat && stations.map((s) => {
                const ratio = Math.min(1, (wip[s.id] ?? 0) / maxWip)
                if (ratio === 0) return null
                return <HeatBlob key={s.id} x={s.x + node / 2} y={s.y + node / 2} ratio={ratio} node={node} />
              })}
              {routeModels.map((r, i) => (
                <RouteEdge
                  key={r._id}
                  route={r}
                  fromStation={stationModels[r.load]}
                  toStation={stationModels[r.unload]}
                  nodeSize={node}
                  tint={hexToInt(palette[r.processId] ?? '#888888')}
                  boundaryTint={boundaryTint(edges[i], stations)}
                  offsetPx={lanes.lane[i] ?? 0}
                  badgeShiftPx={lanes.badge[i] ?? 0}
                />
              ))}
            </Container>
          </Stage>
          </PixiBoundary>
          )}
          <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }}>
            {stations.map((s) => (
              <Tile key={s.id} s={s} count={wip[s.id] ?? 0} scale={scale} node={node} />
            ))}
          </div>
          {processNames && Object.keys(processNames).length > 1 && (
            <div style={{
              position: 'absolute', top: 10, right: 10, display: 'flex',
              flexDirection: 'column', gap: 3, padding: '6px 9px',
              background: 'var(--tk-glass)', border: '1px solid var(--tk-glass-border)',
              borderRadius: 4, pointerEvents: 'none',
            }}>
              {Object.entries(processNames).map(([id, name]) => (
                <span key={id} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  fontSize: 10.5, fontFamily: '"JetBrains Mono", monospace',
                  color: 'var(--tk-glass-text)', whiteSpace: 'nowrap',
                }}>
                  <span style={{ width: 12, height: 2.5, borderRadius: 2,
                                 background: palette[id] ?? '#888' }} />
                  {name}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

/** Drive a wip record with a step function on an interval — shared by every
 *  animated figure. */
export function useFlowSimulation(
  initial: Wip, step: (prev: Wip, tick: number) => Wip, ms = 700,
): Wip {
  const [wip, setWip] = useState<Wip>(initial)
  const tickRef = useRef(0)
  useEffect(() => {
    const t = setInterval(() => {
      tickRef.current += 1
      setWip((prev) => step(prev, tickRef.current))
    }, ms)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return wip
}
