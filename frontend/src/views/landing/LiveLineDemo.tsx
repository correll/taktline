import React, { useEffect, useState } from 'react'
import FlowScene, { useFlowSimulation, type SceneEdge, type SceneStation, type Wip }
  from '../../components/demo/FlowScene'

// The landing hero: a battery remanufacturing floor carrying TWO chemistries,
// drawn with the app's own map primitives.
//
// Chosen over a straight assembly line because it is the shape Taktline can
// draw that a spreadsheet cannot. A pack is TORN DOWN — one lot fans out into
// modules and busbars at once, which the weight badges say out loud — the two
// streams are worked in parallel, and a merge recombines them into a rebuilt
// pack. Fan out, then converge.
//
// Two processes share every station, each in its own colour and shifted onto
// its own lane, because that is the case a shared floor actually presents and
// the reason the map bothers with colours at all. An Odoo node raises the
// demand, wearing its letter mark rather than an icon: on a map of a shop
// floor an integration should read as a foreign object, which is what it is.
//
// It also tells the truth about itself: NMC delivers four modules a cycle and
// its merge takes three, so work banks up at the module bench and the heat
// climbs there — exactly the surplus the accumulation warning flags.

const NMC = 'nmc', LFP = 'lfp'
const PROCESS_NAMES = { [NMC]: 'NMC packs', [LFP]: 'LFP packs' }

const STATIONS: SceneStation[] = [
  { id: 'odoo',     name: 'Odoo',          icon: 'Box',          color: '#714B67',
    x: 700, y: 6,   provider: 'odoo' },
  { id: 'intake',   name: 'Used packs',    icon: 'Truck',        color: '#6B7280', x: 10,  y: 168 },
  { id: 'teardown', name: 'Teardown',      icon: 'Hammer',       color: '#B45309',
    x: 232, y: 168, pulseMs: 2600 },
  { id: 'modules',  name: 'Module test',   icon: 'FlaskConical', color: '#2D5B8E',
    x: 462, y: 26,  pulseMs: 1700 },
  { id: 'prep',     name: 'Cleaning prep', icon: 'Box',          color: '#0E7490', x: 232, y: 310 },
  { id: 'busbars',  name: 'Busbar clean',  icon: 'Wrench',       color: '#0E7490',
    x: 462, y: 310, pulseMs: 2100 },
  { id: 'reasm',    name: 'Reassembly',    icon: 'Factory',      color: '#8B5CF6',
    x: 700, y: 168, pulseMs: 3400 },
  { id: 'qa',       name: 'QA & dispatch', icon: 'ScanSearch',   color: '#10B981',
    x: 938, y: 168, pulseMs: 3400 },
]

// The weights are the story, and the two chemistries disagree about them: an
// NMC pack yields four modules, an LFP pack six. Same floor, same stations.
const EDGES: SceneEdge[] = [
  { from: 'odoo',     to: 'reasm',    qty: 1, process: NMC },   // demand
  { from: 'intake',   to: 'teardown', qty: 1, process: NMC },
  { from: 'intake',   to: 'teardown', qty: 1, process: LFP },
  { from: 'teardown', to: 'modules',  qty: 4, process: NMC },
  { from: 'teardown', to: 'modules',  qty: 6, process: LFP },
  { from: 'teardown', to: 'busbars',  qty: 2, process: NMC },
  { from: 'teardown', to: 'busbars',  qty: 1, process: LFP },
  { from: 'prep',     to: 'busbars',  qty: 1, process: NMC },
  { from: 'modules',  to: 'reasm',    qty: 3, process: NMC },
  { from: 'modules',  to: 'reasm',    qty: 6, process: LFP },
  { from: 'busbars',  to: 'reasm',    qty: 2, process: NMC },
  { from: 'busbars',  to: 'reasm',    qty: 1, process: LFP },
  { from: 'reasm',    to: 'qa',       qty: 1, process: NMC },
  { from: 'reasm',    to: 'qa',       qty: 1, process: LFP },
]

// Heat is a RATIO against this, so it sets what counts as "piling up". Held
// well above the resting level of the queues on purpose: with it tight, every
// station glowed at once and the heatmap said nothing. Only the module bench,
// which really does bank a surplus, should run hot.
const MAX_WIP = 9
const CYCLE = 24   // ticks per starve/drain cycle at the reassembly bench

const INITIAL: Wip = {
  odoo: 0, intake: 2, teardown: 0, modules: 0, prep: 2, busbars: 0, reasm: 0, qa: 0,
}

function step(prev: Wip, tick: number): Wip {
  const w = { ...prev }
  const phase = (tick % CYCLE) / CYCLE
  // The bench works only in the back half of the cycle, so the feeds fill and
  // drain and the heat breathes the way a real line does.
  const assembling = phase > 0.45

  if (assembling && w.modules >= 3 && w.busbars >= 2 && Math.random() < 0.9) {
    w.modules -= 3; w.busbars -= 2; w.reasm += 1
  }
  if (w.reasm >= 1 && Math.random() < 0.7) { w.reasm -= 1; w.qa += 1 }
  if (w.prep >= 1 && w.busbars < 5 && Math.random() < 0.6) w.prep -= 1

  // The teardown: ONE pack becomes four modules and two busbars, at once. This
  // is the split, and the only place counts jump by more than one — which is
  // what makes the fan-out legible rather than decorative.
  if (w.intake >= 1 && w.modules < 7 && Math.random() < 0.55) {
    w.intake -= 1
    w.modules += 4
    w.busbars += 2
  }

  // Four modules arrive per pack and three leave, so the fourth banks up. Set
  // the spares aside now and then, or the shelf would fill without end.
  if (w.modules > 6 && tick % 3 === 0) w.modules -= 2

  // The queues are kept shallow: a supermarket that is always full is not a
  // queue, and its heat would drown the bench that is genuinely accumulating.
  if (w.intake < 2 && tick % 2 === 0) w.intake += 1
  if (w.prep < 2) w.prep += 1
  if (w.qa > 3) w.qa = 1
  return w
}

// On a phone the full line renders at ~4px per station label — unreadable. A
// narrow viewport gets the essential shape at a larger relative node size: the
// teardown fanning out, both chemistries, and the merge pulling them back.
// Labels are one short word, because a tile is ~43px across there and anything
// longer is cut mid-word, which reads as a rendering fault rather than a name.
const COMPACT: SceneStation[] = [
  { id: 'teardown', name: 'Teardown', icon: 'Hammer',       color: '#B45309',
    x: 28, y: 140, pulseMs: 2600 },
  { id: 'modules',  name: 'Modules',  icon: 'FlaskConical', color: '#2D5B8E',
    x: 276, y: 12, pulseMs: 1700 },
  { id: 'busbars',  name: 'Busbars',  icon: 'Wrench',       color: '#0E7490',
    x: 276, y: 268, pulseMs: 2100 },
  { id: 'reasm',    name: 'Rebuild',  icon: 'Factory',      color: '#8B5CF6',
    x: 524, y: 140, pulseMs: 3400 },
]
const COMPACT_EDGES: SceneEdge[] = [
  { from: 'teardown', to: 'modules', qty: 4, process: NMC },
  { from: 'teardown', to: 'modules', qty: 6, process: LFP },
  { from: 'teardown', to: 'busbars', qty: 2, process: NMC },
  { from: 'modules',  to: 'reasm',   qty: 3, process: NMC },
  { from: 'modules',  to: 'reasm',   qty: 6, process: LFP },
  { from: 'busbars',  to: 'reasm',   qty: 2, process: NMC },
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
                 worldW={644} worldH={400} node={92} maxWip={MAX_WIP}
                 processNames={PROCESS_NAMES} />
    : <FlowScene stations={STATIONS} edges={EDGES} wip={wip}
                 worldW={1180} worldH={440} node={92} maxWip={MAX_WIP}
                 processNames={PROCESS_NAMES} />
}
