import React, { useEffect, useState } from 'react'
import FlowScene, { useFlowSimulation, type SceneEdge, type SceneStation, type Wip }
  from '../../components/demo/FlowScene'

// The landing hero: a small e-bike line drawn with the app's own map
// primitives, driven by a toy flow simulation. The assembly station cycles
// between starved and productive, so material piles up at the merge feeds and
// drains again — the heatmap breathes like a real line.

const STATIONS: SceneStation[] = [
  { id: 'steel',    name: 'Steel inventory',   icon: 'Box',        color: '#6B7280', x: 10,   y: 30 },
  { id: 'cut',      name: 'Tube cutting',      icon: 'Scissors',   color: '#F59E0B', x: 250,  y: 30 },
  { id: 'weld',     name: 'Frame welding',     icon: 'Hammer',     color: '#EF4444', x: 490,  y: 30 },
  { id: 'parts',    name: 'Parts inventory',   icon: 'Box',        color: '#6B7280', x: 10,   y: 278 },
  { id: 'drive',    name: 'Drivetrain',        icon: 'Cog',        color: '#3B82F6', x: 250,  y: 278 },
  { id: 'qc',       name: 'Drivetrain QC',     icon: 'ScanSearch', color: '#10B981', x: 490,  y: 278 },
  { id: 'assembly', name: 'Frame integration', icon: 'Factory',    color: '#8B5CF6', x: 750,  y: 154 },
  { id: 'ship',     name: 'Finished goods',    icon: 'Warehouse',  color: '#6B7280', x: 1005, y: 154 },
]

const EDGES: SceneEdge[] = [
  { from: 'steel', to: 'cut',      qty: 1 },
  { from: 'cut',   to: 'weld',     qty: 1 },
  { from: 'weld',  to: 'assembly', qty: 1 },
  { from: 'parts', to: 'drive',    qty: 2 },   // weight badge: 2 parts per drivetrain
  { from: 'drive', to: 'qc',       qty: 1 },
  { from: 'qc',    to: 'assembly', qty: 1 },
  { from: 'assembly', to: 'ship',  qty: 1 },
]

const MAX_WIP = 6
const CYCLE = 26   // ticks per starve/drain cycle at the assembly

const INITIAL: Wip = { steel: 5, cut: 0, weld: 0, parts: 6, drive: 0, qc: 0, assembly: 0, ship: 0 }

function step(prev: Wip, tick: number): Wip {
  const w = { ...prev }
  const move = (from: string, to: string, take = 1, p = 1) => {
    if (w[from] >= take && Math.random() < p) { w[from] -= take; w[to] += 1 }
  }
  // The assembly works only in the second half of the cycle → upstream WIP
  // builds at the merge feeds (heat grows), then drains.
  const phase = (tick % CYCLE) / CYCLE
  const assemblyActive = phase > 0.45

  if (assemblyActive && w.weld >= 1 && w.qc >= 1 && Math.random() < 0.9) {
    w.weld -= 1; w.qc -= 1; w.assembly += 1
  }
  move('assembly', 'ship', 1, 0.7)
  move('cut', 'weld', 1, w.weld < MAX_WIP ? 0.75 : 0)
  move('steel', 'cut', 1, w.cut < 2 ? 0.8 : 0)
  move('drive', 'qc', 1, w.qc < MAX_WIP ? 0.75 : 0)
  move('parts', 'drive', 2, w.drive < 2 ? 0.8 : 0)   // consumes 2 (edge weight)
  if (w.steel < 5 && tick % 2 === 0) w.steel += 1
  if (w.parts < 6) w.parts += 1
  if (w.ship > 4) w.ship = 1
  return w
}

// On a phone the full line renders at ~4px per station label — unreadable. A
// narrow viewport gets a shorter line at a larger relative node size instead,
// so the idea (flow, heat, a weighted merge) still reads.
const COMPACT: SceneStation[] = [
  { id: 'steel',    name: 'Steel',    icon: 'Box',        color: '#6B7280', x: 10,  y: 30 },
  { id: 'weld',     name: 'Welding',  icon: 'Hammer',     color: '#EF4444', x: 250, y: 30 },
  { id: 'parts',    name: 'Parts',    icon: 'Box',        color: '#6B7280', x: 10,  y: 250 },
  { id: 'qc',       name: 'QC',       icon: 'ScanSearch', color: '#10B981', x: 250, y: 250 },
  { id: 'assembly', name: 'Assembly', icon: 'Factory',    color: '#8B5CF6', x: 500, y: 140 },
]
const COMPACT_EDGES: SceneEdge[] = [
  { from: 'steel', to: 'weld',     qty: 1 },
  { from: 'weld',  to: 'assembly', qty: 1 },
  { from: 'parts', to: 'qc',       qty: 2 },
  { from: 'qc',    to: 'assembly', qty: 1 },
]

function useIsNarrow(breakpoint = 720): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < breakpoint)
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < breakpoint)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [breakpoint])
  return narrow
}

export default function LiveLineDemo() {
  const wip = useFlowSimulation(INITIAL, step, 650)
  const narrow = useIsNarrow()
  return narrow
    ? <FlowScene stations={COMPACT} edges={COMPACT_EDGES} wip={wip}
                 worldW={702} worldH={372} node={92} maxWip={MAX_WIP} />
    : <FlowScene stations={STATIONS} edges={EDGES} wip={wip}
                 worldW={1180} worldH={400} node={92} maxWip={MAX_WIP} />
}
