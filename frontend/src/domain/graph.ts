// Shared graph utilities for process DAG operations.
// All functions treat routes as directed edges: load → unload.

export interface Edge {
  load: string
  unload: string
}

type AdjMap = Map<string, string[]>

function buildAdj(edges: Edge[]): AdjMap {
  const adj: AdjMap = new Map()
  for (const e of edges) {
    if (!adj.has(e.load)) adj.set(e.load, [])
    adj.get(e.load)!.push(e.unload)
  }
  return adj
}

// Returns true if the edge set contains a directed cycle (DFS with recursion stack).
export function hasCycle(edges: Edge[]): boolean {
  const adj = buildAdj(edges)
  const all = new Set<string>()
  for (const e of edges) { all.add(e.load); all.add(e.unload) }

  const visited = new Set<string>()
  const inStack = new Set<string>()

  function dfs(node: string): boolean {
    visited.add(node)
    inStack.add(node)
    for (const next of adj.get(node) ?? []) {
      if (inStack.has(next)) return true
      if (!visited.has(next) && dfs(next)) return true
    }
    inStack.delete(node)
    return false
  }

  for (const node of all) {
    if (!visited.has(node) && dfs(node)) return true
  }
  return false
}

// Returns true if adding newLoad → newUnload to the existing edges would create a cycle.
export function wouldCreateCycle(existing: Edge[], newLoad: string, newUnload: string): boolean {
  if (newLoad === newUnload) return true           // self-loop is trivially a cycle
  return hasCycle([...existing, { load: newLoad, unload: newUnload }])
}

// Station IDs with no incoming edges (queue origins / leaf-nodes at the start of the graph).
export function sourceNodes(edges: Edge[]): Set<string> {
  const all      = new Set<string>()
  const hasIn    = new Set<string>()
  for (const e of edges) {
    all.add(e.load)
    all.add(e.unload)
    hasIn.add(e.unload)
  }
  return new Set([...all].filter((n) => !hasIn.has(n)))
}

// Station IDs with 2+ incoming edges (valid merge / assembly stations).
/** Locations where two or more feeds converge **within one process**.
 *
 *  The scoping is the whole point. A bench two lines happen to share has two
 *  incoming routes in total but one per process, and it assembles nothing —
 *  counting across processes rendered it as a merge column on the board and
 *  offered a merge the backend would rightly refuse. Alternative routing is
 *  modelled as a second process for the same reason, so it would have been
 *  mis-read too.
 *
 *  Edges without a processId are all treated as one graph, which keeps the
 *  helper usable for the single-process figures in the manual.
 */
export function mergeNodes(edges: (Edge & { processId?: string })[]): Set<string> {
  const perProcess = new Map<string, Map<string, number>>()
  for (const e of edges) {
    const key = e.processId ?? ''
    const inDeg = perProcess.get(key) ?? new Map<string, number>()
    inDeg.set(e.unload, (inDeg.get(e.unload) ?? 0) + 1)
    perProcess.set(key, inDeg)
  }
  const merges = new Set<string>()
  for (const inDeg of perProcess.values()) {
    for (const [id, d] of inDeg) if (d >= 2) merges.add(id)
  }
  return merges
}

// Kahn's topological sort. Returns ordered station IDs, sources first.
// Returns all nodes in insertion order if the graph has no edges.
// Does NOT throw on cycles — callers should check hasCycle first if they need to know.
export function topoSort(edges: Edge[], allNodeIds: string[]): string[] {
  const adj    = buildAdj(edges)
  const inDeg  = new Map<string, number>()
  for (const id of allNodeIds) inDeg.set(id, 0)
  for (const e of edges) inDeg.set(e.unload, (inDeg.get(e.unload) ?? 0) + 1)

  const queue  = allNodeIds.filter((id) => (inDeg.get(id) ?? 0) === 0)
  const result: string[] = []

  while (queue.length > 0) {
    const id = queue.shift()!
    result.push(id)
    for (const next of adj.get(id) ?? []) {
      const d = (inDeg.get(next) ?? 0) - 1
      inDeg.set(next, d)
      if (d === 0) queue.push(next)
    }
  }

  // Append any nodes not reached (cycle members or disconnected — keep them visible)
  for (const id of allNodeIds) {
    if (!result.includes(id)) result.push(id)
  }
  return result
}

// A span of columns [start, end] used for branch-group bars in LotsView.
export interface BarSpan { start: number; end: number }

// Returns a branch-first column order plus solid bars (sequential segments) and
// dashed bars (parallel groups feeding a merge node) for LotsView rendering.
//
// Branch-first order: each source's chain is completed before the next source is
// processed. When the last predecessor of a merge node is visited, the merge node
// joins that chain's BFS queue, so post-merge segments are contiguous with the
// branch that "unlocks" them.
export function computeColumnGroups(
  edges: Edge[],
  allNodeIds: string[],
): { order: string[]; solidBars: BarSpan[]; dashedBars: BarSpan[] } {
  if (allNodeIds.length === 0) return { order: [], solidBars: [], dashedBars: [] }

  // Build per-node adjacency and in-degree (only for known nodes)
  const adj   = new Map<string, string[]>()
  const inDeg = new Map<string, number>()
  for (const id of allNodeIds) { adj.set(id, []); inDeg.set(id, 0) }
  for (const e of edges) {
    if (!adj.has(e.load) || !inDeg.has(e.unload)) continue
    adj.get(e.load)!.push(e.unload)
    inDeg.set(e.unload, (inDeg.get(e.unload) ?? 0) + 1)
  }

  // ── 1. Branch-first topological order ──────────────────────────────────
  const remaining = new Map(inDeg)
  const inResult  = new Set<string>()
  const order: string[] = []

  const sources = allNodeIds.filter((id) => (inDeg.get(id) ?? 0) === 0)
  for (const src of sources) {
    if (inResult.has(src)) continue
    const queue: string[] = [src]
    while (queue.length > 0) {
      const id = queue.shift()!
      if (inResult.has(id)) continue
      inResult.add(id)
      order.push(id)
      for (const next of adj.get(id) ?? []) {
        const d = (remaining.get(next) ?? 0) - 1
        remaining.set(next, d)
        if (d === 0) queue.push(next)
      }
    }
  }
  for (const id of allNodeIds) if (!inResult.has(id)) order.push(id)

  const pos = new Map<string, number>()
  order.forEach((id, i) => pos.set(id, i))

  // ── 2. Sequential segments (solid bars) ────────────────────────────────
  // A segment starts at a source (inDeg=0) or merge node (inDeg≥2) and
  // walks the single-path chain until a fork, a merge node, or a sink.
  const solidBars: BarSpan[]        = []
  const segStartIdx = new Map<string, number>()  // node → first index of its segment
  const segDone     = new Set<string>()

  const starters = allNodeIds
    .filter((id) => (inDeg.get(id) ?? 0) !== 1)
    .sort((a, b) => (pos.get(a) ?? 0) - (pos.get(b) ?? 0))

  for (const startId of starters) {
    if (segDone.has(startId)) continue
    const nodes: string[] = []
    let cur = startId
    while (!segDone.has(cur)) {
      segDone.add(cur)
      nodes.push(cur)
      const nexts = adj.get(cur) ?? []
      if (nexts.length !== 1) break
      if ((inDeg.get(nexts[0]) ?? 0) >= 2) break  // next is a merge — stop before it
      cur = nexts[0]
    }
    if (nodes.length === 0) continue
    const indices = nodes.map((n) => pos.get(n) ?? 0)
    const s = Math.min(...indices)
    const e = Math.max(...indices)
    nodes.forEach((n) => segStartIdx.set(n, s))
    if (e > s) solidBars.push({ start: s, end: e })
  }
  for (const id of allNodeIds) {
    if (!segStartIdx.has(id)) segStartIdx.set(id, pos.get(id) ?? 0)
  }

  // ── 3. Parallel groups (dashed bars) ───────────────────────────────────
  // For each merge node, span a dashed bar from the earliest predecessor's
  // segment start to the latest predecessor's column position.
  const dashedBars: BarSpan[] = []
  for (const id of allNodeIds) {
    if ((inDeg.get(id) ?? 0) < 2) continue
    const preds = edges
      .filter((e) => e.unload === id && allNodeIds.includes(e.load))
      .map((e) => e.load)
    if (preds.length < 2) continue
    const s = Math.min(...preds.map((p) => segStartIdx.get(p) ?? (pos.get(p) ?? 0)))
    const e = Math.max(...preds.map((p) => pos.get(p) ?? 0))
    if (e > s) dashedBars.push({ start: s, end: e })
  }

  return { order, solidBars, dashedBars }
}

// Computes display lanes for the split view: one lane per parallel path.
//
// A lane starts at each source node, and forks: when a station splits (two or
// more outgoing routes) the lane follows its first successor while every other
// successor starts a lane of its own — otherwise the split branches would be
// invisible in this view. Merge nodes are claimed first-come-first-served, so
// a post-merge segment extends exactly one lane. `offset` is the column depth
// the lane begins at, so a branch can be indented under the station it leaves.
export interface Lane { nodes: string[]; offset: number }

export function computeLanes(edges: Edge[], allNodeIds: string[]): Lane[] {
  if (allNodeIds.length === 0) return []

  const adj   = new Map<string, string[]>()
  const inDeg = new Map<string, number>()
  for (const id of allNodeIds) { adj.set(id, []); inDeg.set(id, 0) }
  for (const e of edges) {
    if (!adj.has(e.load) || !inDeg.has(e.unload)) continue
    adj.get(e.load)!.push(e.unload)
    inDeg.set(e.unload, (inDeg.get(e.unload) ?? 0) + 1)
  }

  // Longest downstream chain per node, so a lane can follow the "trunk" of a
  // split instead of whichever branch happened to be drawn first (a two-step
  // scrap branch shouldn't hijack the lane from the main line).
  const reach = new Map<string, number>()
  const depthOf = (id: string, seen = new Set<string>()): number => {
    const cached = reach.get(id)
    if (cached !== undefined) return cached
    if (seen.has(id)) return 0            // defensive: cycles are rejected elsewhere
    seen.add(id)
    const d = 1 + Math.max(0, ...(adj.get(id) ?? []).map((n) => depthOf(n, seen)))
    seen.delete(id)
    reach.set(id, d)
    return d
  }
  for (const id of allNodeIds) depthOf(id)
  const trunkFirst = (ids: string[]) =>
    [...ids].sort((a, b) => (reach.get(b) ?? 0) - (reach.get(a) ?? 0))

  const sources       = allNodeIds.filter((id) => (inDeg.get(id) ?? 0) === 0)
  const mergeAssigned = new Set<string>()
  const lanes: Lane[] = []
  const pending: { start: string; offset: number }[] =
    trunkFirst(sources).map((id) => ({ start: id, offset: 0 }))
  const started = new Set<string>()

  while (pending.length > 0) {
    const { start, offset } = pending.shift()!
    if (started.has(start)) continue
    started.add(start)

    const nodes: string[] = []
    const branches: { start: string; offset: number }[] = []
    let cur: string | null = start
    let depth = offset

    while (cur !== null) {
      const node: string = cur
      nodes.push(node)
      depth += 1
      const nexts: string[] = trunkFirst(adj.get(node) ?? [])

      // The trunk continues into the deepest successor; every other successor
      // starts its own lane, indented to the column it branches from.
      for (const branch of nexts.slice(1)) {
        if (!started.has(branch) && (inDeg.get(branch) ?? 0) < 2) {
          branches.push({ start: branch, offset: depth })
        }
      }

      if (nexts.length === 0) {
        cur = null                       // sink — end of lane
      } else {
        const next: string = nexts[0]
        if ((inDeg.get(next) ?? 0) >= 2) {
          if (!mergeAssigned.has(next)) {
            mergeAssigned.add(next)
            cur = next                   // claim the merge and continue through it
          } else {
            cur = null                   // another lane owns it — stop here
          }
        } else if (started.has(next)) {
          cur = null                     // already shown in another lane
        } else {
          started.add(next)
          cur = next
        }
      }
    }

    if (nodes.length > 0) lanes.push({ nodes, offset })
    // Branches read best directly under the lane they leave, before the next source.
    pending.unshift(...branches)
  }

  return lanes
}


// ─── Flow balance: where does material pile up? ──────────────────────────────
// A weighted edge, scoped to the process it belongs to.
export interface FlowEdge extends Edge { quantity: number; processId: string }

export interface Accumulation {
  stationId: string
  processId: string
  produced: number   // units delivered here per cycle
  consumed: number   // units the downstream steps take per cycle
  surplus: number    // the leftovers that pile up (produced - consumed)
}

// Stations with incoming routes but none outgoing: finished goods land there on
// purpose, so they are never "accumulating" and are left out of heat and OEE.
export function warehouseNodes(edges: Edge[]): Set<string> {
  const hasIn = new Set<string>()
  const hasOut = new Set<string>()
  for (const e of edges) { hasIn.add(e.unload); hasOut.add(e.load) }
  return new Set([...hasIn].filter((id) => !hasOut.has(id)))
}

// Finds stations that structurally accumulate work: the weights upstream
// deliver more units per cycle than the weights downstream consume. Example —
// loc1 --(x3)--> loc2 --> loc4 : three pieces arrive at loc2 each cycle but the
// merge at loc4 only takes one, so two pile up every time.
//
// A "cycle" is one unit at each end of the process. Per process:
//   • need(S)  — units of S required to satisfy one cycle, walked backwards.
//   • supply(S) — units actually delivered when the upstream runs at its own
//                 need, walked forwards.
// The gap between them is the surplus. Merge stations are skipped (their inputs
// are consumed there by design) as are warehouses (they are meant to fill up).
export function findAccumulations(edges: FlowEdge[], allNodeIds: string[]): Accumulation[] {
  const out: Accumulation[] = []
  const byProcess = new Map<string, FlowEdge[]>()
  for (const e of edges) {
    if (!byProcess.has(e.processId)) byProcess.set(e.processId, [])
    byProcess.get(e.processId)!.push(e)
  }

  for (const [processId, pEdges] of byProcess.entries()) {
    const nodes = new Set<string>()
    for (const e of pEdges) { nodes.add(e.load); nodes.add(e.unload) }
    const ids = allNodeIds.filter((id) => nodes.has(id))

    const outgoing = new Map<string, FlowEdge[]>()
    const incoming = new Map<string, FlowEdge[]>()
    for (const id of ids) { outgoing.set(id, []); incoming.set(id, []) }
    for (const e of pEdges) {
      outgoing.get(e.load)?.push(e)
      incoming.get(e.unload)?.push(e)
    }
    const isMerge = (id: string) => (incoming.get(id)?.length ?? 0) >= 2
    const isSplit = (id: string) => (outgoing.get(id)?.length ?? 0) >= 2

    // Units appearing at `unload` per unit moved out of `load`: only a split
    // multiplies, and only when the target is not itself a merge (there the
    // weight counts consumption instead).
    const produces = (e: FlowEdge) =>
      isSplit(e.load) && !isMerge(e.unload) ? Math.max(1, e.quantity) : 1
    // Units of `load`'s product consumed per unit produced at `unload`.
    const consumes = (e: FlowEdge) => (isMerge(e.unload) ? Math.max(1, e.quantity) : 1)

    const order = topoSort(pEdges.map((e) => ({ load: e.load, unload: e.unload })), ids)

    // Backward: how many units of each station one cycle requires.
    const need = new Map<string, number>()
    for (const id of [...order].reverse()) {
      const outs = outgoing.get(id) ?? []
      if (outs.length === 0) { need.set(id, 1); continue }   // a sink: one per cycle
      const perBranch = outs.map((e) =>
        Math.ceil((consumes(e) * (need.get(e.unload) ?? 1)) / produces(e)))
      // One unit at a split becomes a piece on every branch at once, so the
      // hungriest branch sets the requirement; a plain chain has just one.
      need.set(id, Math.max(1, ...perBranch))
    }

    // Forward: what the upstream actually delivers at those rates.
    for (const id of ids) {
      if (isMerge(id)) continue                       // inputs are consumed here
      if ((outgoing.get(id)?.length ?? 0) === 0) continue   // warehouse — meant to fill
      const ins = incoming.get(id) ?? []
      if (ins.length === 0) continue                  // a source produces to order
      const produced = ins.reduce((sum, e) => sum + (need.get(e.load) ?? 1) * produces(e), 0)
      const consumed = need.get(id) ?? 0
      if (produced > consumed) {
        out.push({ stationId: id, processId, produced, consumed, surplus: produced - consumed })
      }
    }
  }
  return out
}
