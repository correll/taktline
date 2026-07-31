import type { SceneEdge, SceneStation, Wip } from '../../components/demo/FlowScene'

/** The three lines the landing hero rotates through.
 *
 *  Each is a real shape from a different trade, chosen because all three need
 *  the thing a spreadsheet cannot hold: one lot fanning out into several, worked
 *  in parallel, then recombined. A battery is torn down, a sweatshirt is cut,
 *  a window is mitred — same graph, three industries.
 *
 *  Each carries two value streams over the same stations, because a shared
 *  floor is the normal case and the reason the map bothers with colours.
 *
 *  The weights on the edges are the RECIPE — how many pieces one unit yields,
 *  and how many one assembly consumes. The counts on the tiles are stock on
 *  hand, which is a different quantity: a line that cuts 32 busbars from a pack
 *  still only has a handful sitting on the bench at any moment. Simulating the
 *  recipe literally would fill every station on the first tick and the heatmap
 *  would say nothing ever again.
 */

export interface DemoLine {
  id: string
  label: string
  blurb: string
  processNames: Record<string, string>
  stations: SceneStation[]
  edges: SceneEdge[]
  compact: SceneStation[]
  compactEdges: SceneEdge[]
  initial: Wip
  /** Stations that make something from several inputs — the merges. */
  merges: string[]
  /** Stations that fan one unit out into several — the splits. */
  splits: string[]
  /** Queues that top themselves back up, and to what depth. */
  sources: Record<string, number>
  /** Where finished goods land, and where the count wraps so it keeps moving. */
  sink: string
}

// ─── 1 · Battery remanufacturing ─────────────────────────────────────────────

const battery: DemoLine = {
  id: 'battery',
  label: 'Battery remanufacturing',
  blurb: 'One pack torn down into modules and busbars, rebuilt as a reman pack.',
  processNames: { nmc: 'NMC packs', lfp: 'LFP packs' },
  stations: [
    { id: 'odoo',     name: 'Odoo',          icon: 'Box',          color: '#714B67',
      x: 700, y: 6, provider: 'odoo' },
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
  ],
  // Yield in equals consumption out: nothing is left over, so the line balances
  // and no station banks a permanent surplus.
  edges: [
    { from: 'odoo',     to: 'reasm',    qty: 1,  process: 'nmc' },
    { from: 'intake',   to: 'teardown', qty: 1,  process: 'nmc' },
    { from: 'intake',   to: 'teardown', qty: 1,  process: 'lfp' },
    { from: 'teardown', to: 'modules',  qty: 8,  process: 'nmc' },
    { from: 'teardown', to: 'modules',  qty: 4,  process: 'lfp' },
    { from: 'teardown', to: 'busbars',  qty: 32, process: 'nmc' },
    { from: 'teardown', to: 'busbars',  qty: 16, process: 'lfp' },
    { from: 'prep',     to: 'busbars',  qty: 1,  process: 'nmc' },
    { from: 'modules',  to: 'reasm',    qty: 8,  process: 'nmc' },
    { from: 'modules',  to: 'reasm',    qty: 4,  process: 'lfp' },
    { from: 'busbars',  to: 'reasm',    qty: 32, process: 'nmc' },
    { from: 'busbars',  to: 'reasm',    qty: 16, process: 'lfp' },
    { from: 'reasm',    to: 'qa',       qty: 1,  process: 'nmc' },
    { from: 'reasm',    to: 'qa',       qty: 1,  process: 'lfp' },
  ],
  compact: [
    { id: 'teardown', name: 'Teardown', icon: 'Hammer',       color: '#B45309',
      x: 28, y: 140, pulseMs: 2600 },
    { id: 'modules',  name: 'Modules',  icon: 'FlaskConical', color: '#2D5B8E',
      x: 276, y: 12, pulseMs: 1700 },
    { id: 'busbars',  name: 'Busbars',  icon: 'Wrench',       color: '#0E7490',
      x: 276, y: 268, pulseMs: 2100 },
    { id: 'reasm',    name: 'Rebuild',  icon: 'Factory',      color: '#8B5CF6',
      x: 524, y: 140, pulseMs: 3400 },
  ],
  compactEdges: [
    { from: 'teardown', to: 'modules', qty: 8,  process: 'nmc' },
    { from: 'teardown', to: 'modules', qty: 4,  process: 'lfp' },
    { from: 'teardown', to: 'busbars', qty: 32, process: 'nmc' },
    { from: 'modules',  to: 'reasm',   qty: 8,  process: 'nmc' },
    { from: 'modules',  to: 'reasm',   qty: 4,  process: 'lfp' },
    { from: 'busbars',  to: 'reasm',   qty: 32, process: 'nmc' },
  ],
  initial: { odoo: 0, intake: 2, teardown: 0, modules: 0, prep: 2, busbars: 0, reasm: 0, qa: 0 },
  merges: ['reasm', 'busbars'],
  splits: ['teardown'],
  sources: { intake: 2, prep: 2 },
  sink: 'qa',
}

// ─── 2 · Cut and sew ─────────────────────────────────────────────────────────

const sweatshirt: DemoLine = {
  id: 'sweatshirt',
  label: 'Cut & sew — sweatshirts',
  blurb: 'One lay cut into four panel types, then a progressive sewing line.',
  processNames: { crew: 'Crew neck', hood: 'Hooded' },
  // A garment line is not a diamond, and drawing it as one would have been a
  // re-skin of the battery. It fans WIDE — a single lay is cut into every panel
  // the style needs at once — and then runs DEEP: the progressive bundle
  // system is a sequence of operations, not one bench. So four branches into a
  // four-input merge, followed by a chain.
  stations: [
    { id: 'fleece',  name: 'Fleece rolls', icon: 'Layers',   color: '#6B7280', x: 10,  y: 174 },
    { id: 'cutting', name: 'Spread & cut', icon: 'Scissors', color: '#B45309',
      x: 180, y: 174, pulseMs: 2200 },
    { id: 'front',   name: 'Front & back', icon: 'Layers',   color: '#2D5B8E',
      x: 372, y: 6,   pulseMs: 1400 },
    { id: 'sleeves', name: 'Sleeves',      icon: 'Layers',   color: '#2D5B8E',
      x: 372, y: 118, pulseMs: 1600 },
    { id: 'ribbing', name: 'Ribbing',      icon: 'Layers',   color: '#0E7490',
      x: 372, y: 230, pulseMs: 1900 },
    { id: 'hoods',   name: 'Hood panels',  icon: 'Layers',   color: '#0E7490',
      x: 372, y: 342, pulseMs: 2300 },
    { id: 'shopify', name: 'Shopify',      icon: 'Box',      color: '#5E8E3E',
      x: 566, y: 14,  provider: 'shopify' },
    { id: 'sewing',  name: 'Sewing line',  icon: 'Cog',      color: '#8B5CF6',
      x: 566, y: 174, pulseMs: 2800 },
    { id: 'overlock', name: 'Seam & hem',  icon: 'Cog',      color: '#8B5CF6',
      x: 760, y: 174, pulseMs: 2400 },
    { id: 'finish',  name: 'Print & pack', icon: 'Printer',  color: '#10B981',
      x: 954, y: 174, pulseMs: 3000 },
  ],
  // The hood branch belongs to ONE style: a crew neck is cut without it. Two
  // processes over one cutting table that do not even use the same branches —
  // which a single-process drawing cannot express at all.
  edges: [
    { from: 'shopify', to: 'sewing',   qty: 1,  process: 'crew' },
    { from: 'fleece',  to: 'cutting',  qty: 1,  process: 'crew' },
    { from: 'fleece',  to: 'cutting',  qty: 1,  process: 'hood' },
    { from: 'cutting', to: 'front',    qty: 24, process: 'crew' },
    { from: 'cutting', to: 'front',    qty: 24, process: 'hood' },
    { from: 'cutting', to: 'sleeves',  qty: 24, process: 'crew' },
    { from: 'cutting', to: 'sleeves',  qty: 24, process: 'hood' },
    { from: 'cutting', to: 'ribbing',  qty: 24, process: 'crew' },
    { from: 'cutting', to: 'ribbing',  qty: 12, process: 'hood' },
    { from: 'cutting', to: 'hoods',    qty: 24, process: 'hood' },
    { from: 'front',   to: 'sewing',   qty: 24, process: 'crew' },
    { from: 'front',   to: 'sewing',   qty: 24, process: 'hood' },
    { from: 'sleeves', to: 'sewing',   qty: 24, process: 'crew' },
    { from: 'sleeves', to: 'sewing',   qty: 24, process: 'hood' },
    { from: 'ribbing', to: 'sewing',   qty: 24, process: 'crew' },
    { from: 'ribbing', to: 'sewing',   qty: 12, process: 'hood' },
    { from: 'hoods',   to: 'sewing',   qty: 24, process: 'hood' },
    { from: 'sewing',  to: 'overlock', qty: 1,  process: 'crew' },
    { from: 'sewing',  to: 'overlock', qty: 1,  process: 'hood' },
    { from: 'overlock', to: 'finish',  qty: 1,  process: 'crew' },
    { from: 'overlock', to: 'finish',  qty: 1,  process: 'hood' },
  ],
  // The phone keeps the wide fan, which is what makes this line its own shape,
  // and drops the chain — three branches read at 43px, five stations do not.
  compact: [
    { id: 'cutting', name: 'Cut',     icon: 'Scissors', color: '#B45309',
      x: 20, y: 154, pulseMs: 2200 },
    { id: 'front',   name: 'Panels',  icon: 'Layers',   color: '#2D5B8E',
      x: 250, y: 10, pulseMs: 1400 },
    { id: 'sleeves', name: 'Sleeves', icon: 'Layers',   color: '#2D5B8E',
      x: 250, y: 154, pulseMs: 1600 },
    { id: 'ribbing', name: 'Ribbing', icon: 'Layers',   color: '#0E7490',
      x: 250, y: 298, pulseMs: 1900 },
    { id: 'sewing',  name: 'Sewing',  icon: 'Cog',      color: '#8B5CF6',
      x: 490, y: 154, pulseMs: 2800 },
  ],
  compactEdges: [
    { from: 'cutting', to: 'front',   qty: 24, process: 'crew' },
    { from: 'cutting', to: 'sleeves', qty: 24, process: 'crew' },
    { from: 'cutting', to: 'ribbing', qty: 24, process: 'crew' },
    { from: 'cutting', to: 'ribbing', qty: 12, process: 'hood' },
    { from: 'front',   to: 'sewing',  qty: 24, process: 'crew' },
    { from: 'sleeves', to: 'sewing',  qty: 24, process: 'crew' },
    { from: 'ribbing', to: 'sewing',  qty: 24, process: 'crew' },
    { from: 'ribbing', to: 'sewing',  qty: 12, process: 'hood' },
  ],
  initial: {
    shopify: 0, fleece: 2, cutting: 0, front: 0, sleeves: 0, ribbing: 0, hoods: 0,
    sewing: 0, overlock: 0, finish: 0,
  },
  merges: ['sewing'],
  splits: ['cutting'],
  sources: { fleece: 2 },
  sink: 'finish',
}

// ─── 3 · Window making ───────────────────────────────────────────────────────

const windows: DemoLine = {
  id: 'windows',
  label: 'Window fabrication',
  blurb: 'Profile mitred into frame and sash, glazed with a sealed unit.',
  processNames: { casement: 'Casement', tilt: 'Tilt & turn' },
  stations: [
    { id: 'netsuite', name: 'NetSuite',     icon: 'Box',        color: '#1F5FA9',
      x: 700, y: 6, provider: 'netsuite' },
    { id: 'profile',  name: 'uPVC profile', icon: 'Box',        color: '#6B7280', x: 10,  y: 168 },
    { id: 'saw',      name: 'Cut & mitre',  icon: 'Scissors',   color: '#B45309',
      x: 232, y: 168, pulseMs: 2400 },
    { id: 'frames',   name: 'Weld & clean', icon: 'Thermometer', color: '#2D5B8E',
      x: 462, y: 26,  pulseMs: 1800 },
    { id: 'glass',    name: 'Glass store',  icon: 'Layers',     color: '#0E7490', x: 232, y: 310 },
    { id: 'igu',      name: 'Sealed units', icon: 'Layers',     color: '#0E7490',
      x: 462, y: 310, pulseMs: 2000 },
    { id: 'glazing',  name: 'Glazing',      icon: 'Factory',    color: '#8B5CF6',
      x: 700, y: 168, pulseMs: 3200 },
    { id: 'dispatch', name: 'QC & load',    icon: 'Truck',      color: '#10B981',
      x: 938, y: 168, pulseMs: 3200 },
  ],
  // A frame is four mitred lengths; a tilt-and-turn carries a sash as well, so
  // it takes eight. Casements here are single-light, tilt-and-turns double.
  edges: [
    { from: 'netsuite', to: 'glazing', qty: 1, process: 'casement' },
    { from: 'profile',  to: 'saw',     qty: 1, process: 'casement' },
    { from: 'profile',  to: 'saw',     qty: 1, process: 'tilt' },
    { from: 'saw',      to: 'frames',  qty: 4, process: 'casement' },
    { from: 'saw',      to: 'frames',  qty: 8, process: 'tilt' },
    { from: 'glass',    to: 'igu',     qty: 2, process: 'casement' },
    { from: 'glass',    to: 'igu',     qty: 4, process: 'tilt' },
    { from: 'frames',   to: 'glazing', qty: 4, process: 'casement' },
    { from: 'frames',   to: 'glazing', qty: 8, process: 'tilt' },
    { from: 'igu',      to: 'glazing', qty: 1, process: 'casement' },
    { from: 'igu',      to: 'glazing', qty: 2, process: 'tilt' },
    { from: 'glazing',  to: 'dispatch', qty: 1, process: 'casement' },
    { from: 'glazing',  to: 'dispatch', qty: 1, process: 'tilt' },
  ],
  compact: [
    { id: 'saw',     name: 'Mitre',   icon: 'Scissors',    color: '#B45309',
      x: 28, y: 140, pulseMs: 2400 },
    { id: 'frames',  name: 'Frames',  icon: 'Thermometer', color: '#2D5B8E',
      x: 276, y: 12, pulseMs: 1800 },
    { id: 'igu',     name: 'Glass',   icon: 'Layers',      color: '#0E7490',
      x: 276, y: 268, pulseMs: 2000 },
    { id: 'glazing', name: 'Glazing', icon: 'Factory',     color: '#8B5CF6',
      x: 524, y: 140, pulseMs: 3200 },
  ],
  compactEdges: [
    { from: 'saw',    to: 'frames',  qty: 4, process: 'casement' },
    { from: 'saw',    to: 'frames',  qty: 8, process: 'tilt' },
    { from: 'frames', to: 'glazing', qty: 4, process: 'casement' },
    { from: 'frames', to: 'glazing', qty: 8, process: 'tilt' },
    { from: 'igu',    to: 'glazing', qty: 1, process: 'casement' },
    { from: 'igu',    to: 'glazing', qty: 2, process: 'tilt' },
  ],
  initial: { netsuite: 0, profile: 2, saw: 0, frames: 0, glass: 2, igu: 0, glazing: 0, dispatch: 0 },
  merges: ['glazing', 'igu'],
  splits: ['saw'],
  sources: { profile: 2, glass: 2 },
  sink: 'dispatch',
}

export const DEMO_LINES: DemoLine[] = [battery, sweatshirt, windows]

// ─── One simulator for all three ─────────────────────────────────────────────

const MAX_WIP = 9
const CYCLE = 24   // ticks per starve/drain cycle at the final merge

/** Moves stock around a line, driven by its shape rather than by a hand-written
 *  script per industry — three bespoke step functions would drift apart and two
 *  of them would rot unnoticed.
 *
 *  It deliberately does NOT apply the edge weights literally. Those are the
 *  recipe, in the units a real order is written in (32 busbars to a pack, 36
 *  panels to a lay); applying them to a tile count would peg every station on
 *  the first tick and the heatmap would never move again. Stock on hand is its
 *  own quantity, and this simulates that.
 */
export function makeStep(line: DemoLine) {
  const feeds: Record<string, string[]> = {}
  const outs: Record<string, string[]> = {}
  for (const e of line.edges) {
    if (!feeds[e.to]?.includes(e.from)) (feeds[e.to] ??= []).push(e.from)
    if (!outs[e.from]?.includes(e.to)) (outs[e.from] ??= []).push(e.to)
  }
  const partners = new Set(line.stations.filter((s) => s.provider).map((s) => s.id))
  const material = (ids: string[] = []) => ids.filter((id) => !partners.has(id))

  return (prev: Wip, tick: number): Wip => {
    const w = { ...prev }
    // The last merge works only in the back half of its cycle, so its feeds
    // fill and drain and the heat breathes the way a real line does.
    const working = (tick % CYCLE) / CYCLE > 0.45

    for (const m of line.merges) {
      const ins = material(feeds[m])
      const isFinal = m === line.merges[0]
      if (isFinal && !working) continue
      if (ins.every((i) => w[i] >= 2) && Math.random() < 0.85) {
        ins.forEach((i) => { w[i] -= 2 })
        w[m] = (w[m] ?? 0) + 2
      }
    }

    // Assemblies move on.
    for (const m of line.merges) {
      const next = material(outs[m])[0]
      if (next && w[m] >= 1 && Math.random() < 0.7) { w[m] -= 1; w[next] = (w[next] ?? 0) + 1 }
    }

    // The split: one unit becomes a piece on EVERY branch at once. The only
    // place counts jump by more than one, which is what makes a fan-out legible
    // rather than decorative.
    for (const sp of line.splits) {
      const branches = material(outs[sp])
      const feeder = material(feeds[sp])[0]
      const room = branches.every((b) => (w[b] ?? 0) < MAX_WIP - 2)
      if (feeder && w[feeder] >= 1 && room && Math.random() < 0.6) {
        w[feeder] -= 1
        branches.forEach((b, i) => { w[b] = (w[b] ?? 0) + (i === 0 ? 4 : 3) })
      }
    }

    // Queues top themselves back up, shallowly: a supermarket that is always
    // full is not a queue, and its heat would drown the bench that is genuinely
    // accumulating.
    for (const [id, depth] of Object.entries(line.sources)) {
      if ((w[id] ?? 0) < depth && tick % 2 === 0) w[id] = (w[id] ?? 0) + 1
    }
    if ((w[line.sink] ?? 0) > 3) w[line.sink] = 1
    return w
  }
}
