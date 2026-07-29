import React from 'react'
import FlowScene, { useFlowSimulation, type SceneEdge, type SceneStation, type Wip }
  from '../components/demo/FlowScene'
import { color, size } from '../theme/tokens'

// Animated figures for the user manual — the same living primitives as the
// app's map (and the landing hero), each one a tiny simulation that makes a
// section's idea visible: flow, bottleneck heat, pull, and weighted merges.

function Figure({ caption, children }: { caption: React.ReactNode; children: React.ReactNode }) {
  return (
    <figure style={{ margin: `${size.sp5} 0` }}>
      <div style={{ border: `1px solid ${color.border}`, borderRadius: size.radiusMd, overflow: 'hidden' }}>
        {children}
      </div>
      <figcaption style={{ fontSize: 12, color: color.textDim, marginTop: size.sp2, lineHeight: 1.5 }}>
        {caption}
      </figcaption>
    </figure>
  )
}

// ── 1 · The flow graph ────────────────────────────────────────────────────────

const FLOW_STATIONS: SceneStation[] = [
  { id: 'src',  name: 'Steel inventory', icon: 'Box',      color: '#6B7280', x: 14,  y: 40 },
  { id: 'cut',  name: 'Tube cutting',    icon: 'Scissors', color: '#F59E0B', x: 232, y: 40 },
  { id: 'weld', name: 'Frame welding',   icon: 'Hammer',   color: '#EF4444', x: 450, y: 40 },
  { id: 'ware', name: 'Warehouse',       icon: 'Warehouse',color: '#6B7280', x: 668, y: 40 },
]
const FLOW_EDGES: SceneEdge[] = [
  { from: 'src', to: 'cut', qty: 1 }, { from: 'cut', to: 'weld', qty: 1 }, { from: 'weld', to: 'ware', qty: 1 },
]

export function FigureFlow() {
  const wip = useFlowSimulation({ src: 4, cut: 1, weld: 1, ware: 0 }, (prev, tick) => {
    const w = { ...prev }
    const move = (a: string, b: string, p: number) => {
      if (w[a] > 0 && Math.random() < p) { w[a] -= 1; w[b] += 1 }
    }
    move('weld', 'ware', 0.6)
    move('cut', 'weld', 0.6)
    move('src', 'cut', 0.6)
    if (w.src < 4 && tick % 2 === 0) w.src += 1
    if (w.ware > 3) w.ware = 0
    return w
  })
  return (
    <Figure caption={<>The flow as a graph: stations are nodes, routes are directed edges, and lot
      cards (the green counts) travel along them from source to warehouse.</>}>
      <FlowScene stations={FLOW_STATIONS} edges={FLOW_EDGES} wip={wip}
                 worldW={774} worldH={172} node={92} showHeat={false} />
    </Figure>
  )
}

// ── 2 · Bottleneck heat ───────────────────────────────────────────────────────

export function FigureBottleneck() {
  const wip = useFlowSimulation({ src: 4, cut: 1, weld: 0, ware: 0 }, (prev, tick) => {
    const w = { ...prev }
    // Welding is the slow station: it works in bursts, so WIP piles up in
    // front of it and the heat swells, then drains.
    const phase = (tick % 22) / 22
    if (phase > 0.5 && w.weld > 0 && Math.random() < 0.85) { w.weld -= 1; w.ware += 1 }
    if (w.cut > 0 && w.weld < 6 && Math.random() < 0.75) { w.cut -= 1; w.weld += 1 }
    if (w.src > 0 && w.cut < 2 && Math.random() < 0.8) { w.src -= 1; w.cut += 1 }
    if (w.src < 4 && tick % 2 === 0) w.src += 1
    if (w.ware > 4) w.ware = 0
    return w
  })
  return (
    <Figure caption={<>The heatmap finds the bottleneck for you: welding is the slowest station here,
      so WIP piles up in front of it and the violet heat swells — then drains as it catches up.
      Heat has its own hue so it never reads as an andon alarm.</>}>
      <FlowScene stations={FLOW_STATIONS} edges={FLOW_EDGES} wip={wip}
                 worldW={774} worldH={172} node={92} maxWip={6} />
    </Figure>
  )
}

// ── 3 · Pull ──────────────────────────────────────────────────────────────────

export function FigurePull() {
  // WIP is capped at 2 per station; only a shipment from the warehouse opens a
  // slot, and the hole travels upstream — downstream demand pulls work.
  const wip = useFlowSimulation({ src: 4, cut: 2, weld: 2, ware: 2 }, (prev, tick) => {
    const w = { ...prev }
    if (tick % 4 === 0 && w.ware > 0) w.ware -= 1              // a customer order ships
    const pull = (a: string, b: string) => {
      if (w[a] > 0 && w[b] < 2) { w[a] -= 1; w[b] += 1 }
    }
    pull('weld', 'ware')
    pull('cut', 'weld')
    pull('src', 'cut')
    if (w.src < 4 && tick % 3 === 0) w.src += 1
    return w
  }, 900)
  return (
    <Figure caption={<>Pull in action: every station is capped at two cards. Nothing moves until a
      finished good ships from the warehouse — the free slot then travels upstream, and each station
      only ever replaces what the next one consumed. Demand sets the pace, not a forecast.</>}>
      <FlowScene stations={FLOW_STATIONS} edges={FLOW_EDGES} wip={wip}
                 worldW={774} worldH={172} node={92} showHeat={false} />
    </Figure>
  )
}

// ── 4 · Weighted merge ────────────────────────────────────────────────────────

const MERGE_STATIONS: SceneStation[] = [
  { id: 'frame',    name: 'Frame line',  icon: 'Hammer',  color: '#EF4444', x: 14,  y: 20 },
  { id: 'motors',   name: 'Motor line',  icon: 'Cog',     color: '#3B82F6', x: 14,  y: 216 },
  { id: 'assembly', name: 'Assembly',    icon: 'Factory', color: '#8B5CF6', x: 330, y: 118 },
  { id: 'ware',     name: 'Warehouse',   icon: 'Warehouse', color: '#6B7280', x: 646, y: 118 },
]
const MERGE_EDGES: SceneEdge[] = [
  { from: 'frame',  to: 'assembly', qty: 1 },
  { from: 'motors', to: 'assembly', qty: 3 },   // the edge weight: 3 motors per e-bike
  { from: 'assembly', to: 'ware',   qty: 1 },
]

export function FigureMerge() {
  const wip = useFlowSimulation({ frame: 1, motors: 3, assembly: 0, ware: 0 }, (prev, tick) => {
    const w = { ...prev }
    // The merge consumes precursors in the ratio of the edge weights:
    // 1 frame + 3 motors → 1 assembly.
    if (w.frame >= 1 && w.motors >= 3 && Math.random() < 0.75) {
      w.frame -= 1; w.motors -= 3; w.assembly += 1
    }
    if (w.assembly > 0 && Math.random() < 0.6) { w.assembly -= 1; w.ware += 1 }
    if (w.frame < 2) w.frame += 1
    w.motors += tick % 2 === 0 ? 2 : 1
    if (w.motors > 7) w.motors = 7
    if (w.ware > 3) w.ware = 0
    return w
  }, 900)
  return (
    <Figure caption={<>A merge station encodes the bill of materials as edge weights: each assembly
      consumes one frame and <b>three</b> motors (the ③ badge on the route). The precursor cards are
      consumed together and a new assembly card is born — always in ratio, never “a few extra”.</>}>
      <FlowScene stations={MERGE_STATIONS} edges={MERGE_EDGES} wip={wip}
                 worldW={752} worldH={330} node={92} showHeat={false} maxWip={7} />
    </Figure>
  )
}
