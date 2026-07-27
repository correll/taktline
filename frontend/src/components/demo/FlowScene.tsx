import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Stage, Container, Graphics } from '@pixi/react'
import * as PIXI from 'pixi.js'
import type { Route, Station } from '../../models'
import RouteEdge from '../map/RouteEdge'
import { getStationIcon } from '../map/StationNode'
import { useThemeStore } from '../../store/theme.store'

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
}

export interface SceneEdge {
  from: string
  to: string
  qty: number
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
}

const CANVAS_BG: Record<'night' | 'day', number> = { night: 0x121110, day: 0xF7F6F2 }

const stationOf = (s: SceneStation, node: number): Station => ({
  _id: s.id, name: s.name, position: { x: s.x, y: s.y, width: node, height: node },
  adapterType: null, adapterConfig: {}, description: '', color: s.color, icon: s.icon,
  createdAt: '', updatedAt: '',
} as unknown as Station)

const routeOf = (e: SceneEdge, i: number): Route => ({
  _id: `scene-${i}`, processId: 'scene', load: e.from, unload: e.to, quantity: e.qty,
  createdAt: '', updatedAt: '',
} as unknown as Route)

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
  const sz = node * scale
  return (
    <div style={{
      position: 'absolute', left: s.x * scale, top: s.y * scale, width: sz, height: sz,
      borderRadius: Math.max(4, sz * 0.08),
      border: `1.5px solid ${s.color}`,
      background: `rgba(var(--tk-map-node-bg-rgb), 0.9)`,
      boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      gap: Math.max(1, sz * 0.04), overflow: 'hidden', pointerEvents: 'none',
    }}>
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: Math.max(3, sz * 0.05),
        background: s.color, opacity: 0.85,
      }} />
      <Icon size={Math.max(12, sz * 0.4)} color={s.color} strokeWidth={1.5} />
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

export default function FlowScene({
  stations, edges, wip, worldW, worldH, node = 92, showHeat = true, maxWip = 6,
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

  const scale = width > 0 ? width / worldW : 0
  const height = worldH * scale

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%', height: height || worldH / 2 }}>
      {scale > 0 && (
        <>
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
              {routeModels.map((r) => (
                <RouteEdge
                  key={r._id}
                  route={r}
                  fromStation={stationModels[r.load]}
                  toStation={stationModels[r.unload]}
                  nodeSize={node}
                />
              ))}
            </Container>
          </Stage>
          <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }}>
            {stations.map((s) => (
              <Tile key={s.id} s={s} count={wip[s.id] ?? 0} scale={scale} node={node} />
            ))}
          </div>
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
