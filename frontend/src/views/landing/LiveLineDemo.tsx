import React, { useEffect, useState } from 'react'
import FlowScene, { useFlowSimulation, type SceneEdge, type SceneStation, type Wip }
  from '../../components/demo/FlowScene'

// The landing hero: a battery remanufacturing line, drawn with the app's own
// map primitives and driven by a toy flow simulation.
//
// Chosen over a straight assembly line because it is the shape Taktline can
// draw that a spreadsheet cannot. A pack is TORN DOWN — one lot fans out into
// four modules and two busbars at once, which the weight badges say out loud —
// the two streams are worked in parallel, and a merge recombines them into a
// reman pack. Fan out, then converge. An assembly line only ever shows the
// second half of that.
//
// It also tells the truth about itself: Module Test receives four modules a
// cycle and passes on three, so work visibly banks up there and the heat
// climbs. That surplus is exactly what the accumulation warning flags on a
// real map, and setting it aside to a spares shelf is what drains it.

const STATIONS: SceneStation[] = [
  { id: 'intake',   name: 'Used packs',       icon: 'Truck',        color: '#6B7280', x: 10,   y: 152 },
  { id: 'teardown', name: 'Teardown',         icon: 'Hammer',       color: '#B45309', x: 232,  y: 152 },
  { id: 'modules',  name: 'Module test',      icon: 'FlaskConical', color: '#2D5B8E', x: 462,  y: 12  },
  { id: 'solution', name: 'Cleaning solution', icon: 'Box',         color: '#0E7490', x: 232,  y: 292 },
  { id: 'busbars',  name: 'Busbar clean',     icon: 'Wrench',       color: '#0E7490', x: 462,  y: 292 },
  { id: 'reasm',    name: 'Reassembly',       icon: 'Factory',      color: '#8B5CF6', x: 700,  y: 152 },
  { id: 'qa',       name: 'QA & dispatch',    icon: 'ScanSearch',   color: '#10B981', x: 938,  y: 152 },
]

// The weights are the story: one pack yields four modules and two busbars,
// and one reman pack consumes three modules and two clean busbars.
const EDGES: SceneEdge[] = [
  { from: 'intake',   to: 'teardown', qty: 1 },
  { from: 'teardown', to: 'modules',  qty: 4 },   // a pack yields 4 modules
  { from: 'teardown', to: 'busbars',  qty: 2 },   // …and 2 busbars
  { from: 'solution', to: 'busbars',  qty: 1 },
  { from: 'modules',  to: 'reasm',    qty: 3 },   // a reman pack takes 3
  { from: 'busbars',  to: 'reasm',    qty: 2 },
  { from: 'reasm',    to: 'qa',       qty: 1 },
]

// Heat is a RATIO against this, so it sets what counts as "piling up". Held
// well above the resting level of the queues on purpose: with it tight, every
// station glowed at once and the heatmap said nothing. Only the module bench,
// which really does bank a surplus, should run hot.
const MAX_WIP = 9
const CYCLE = 24   // ticks per starve/drain cycle at the reassembly bench

const INITIAL: Wip = {
  intake: 2, teardown: 0, modules: 0, solution: 2, busbars: 0, reasm: 0, qa: 0,
}

function step(prev: Wip, tick: number): Wip {
  const w = { ...prev }
  const phase = (tick % CYCLE) / CYCLE
  // The bench works only in the back half of the cycle, so the feeds fill and
  // drain and the heat breathes the way a real line does.
  const assembling = phase > 0.45

  // Reassembly: 3 modules + 2 clean busbars → one reman pack.
  if (assembling && w.modules >= 3 && w.busbars >= 2 && Math.random() < 0.9) {
    w.modules -= 3; w.busbars -= 2; w.reasm += 1
  }
  if (w.reasm >= 1 && Math.random() < 0.7) { w.reasm -= 1; w.qa += 1 }

  // The wash consumes solution to clean what the teardown sent.
  if (w.solution >= 1 && w.busbars < 5 && Math.random() < 0.6) w.solution -= 1

  // The teardown: ONE pack becomes four modules and two busbars, at once.
  // This is the split, and it is the only place the counts jump by more than
  // one — which is what makes the fan-out legible rather than decorative.
  if (w.intake >= 1 && w.modules < 7 && Math.random() < 0.55) {
    w.intake -= 1
    w.modules += 4
    w.busbars += 2
  }

  // Four modules arrive per pack and three leave, so the fourth banks up. Set
  // the spares aside now and then, or the shelf would fill without end.
  if (w.modules > 6 && tick % 3 === 0) w.modules -= 2

  // Fresh packs keep arriving; solution is replenished.
  // The queues are kept shallow: a supermarket that is always full is not a
  // queue, and its heat would drown the bench that is genuinely accumulating.
  if (w.intake < 2 && tick % 2 === 0) w.intake += 1
  if (w.solution < 2) w.solution += 1
  if (w.qa > 3) w.qa = 1
  return w
}

// On a phone the full line renders at ~4px per station label — unreadable. A
// narrow viewport gets the essential shape at a larger relative node size: the
// teardown fanning out, and the merge pulling the two streams back together.
// Labels are kept to one short word: at phone width a tile is ~43px across and
// anything longer is simply cut off mid-word, which reads as a rendering fault
// rather than a name. Margins on both ends for the same reason — a tile flush
// against the container edge looks clipped even when it is whole.
const COMPACT: SceneStation[] = [
  { id: 'teardown', name: 'Teardown', icon: 'Hammer',       color: '#B45309', x: 28,  y: 140 },
  { id: 'modules',  name: 'Modules',  icon: 'FlaskConical', color: '#2D5B8E', x: 276, y: 12  },
  { id: 'busbars',  name: 'Busbars',  icon: 'Wrench',       color: '#0E7490', x: 276, y: 268 },
  { id: 'reasm',    name: 'Rebuild',  icon: 'Factory',      color: '#8B5CF6', x: 524, y: 140 },
]
const COMPACT_EDGES: SceneEdge[] = [
  { from: 'teardown', to: 'modules', qty: 4 },
  { from: 'teardown', to: 'busbars', qty: 2 },
  { from: 'modules',  to: 'reasm',   qty: 3 },
  { from: 'busbars',  to: 'reasm',   qty: 2 },
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
                 worldW={644} worldH={400} node={92} maxWip={MAX_WIP} />
    : <FlowScene stations={STATIONS} edges={EDGES} wip={wip}
                 worldW={1180} worldH={424} node={92} maxWip={MAX_WIP} />
}
