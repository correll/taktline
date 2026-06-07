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
export function mergeNodes(edges: Edge[]): Set<string> {
  const inDeg = new Map<string, number>()
  for (const e of edges) inDeg.set(e.unload, (inDeg.get(e.unload) ?? 0) + 1)
  return new Set([...inDeg.entries()].filter(([, d]) => d >= 2).map(([id]) => id))
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

// Computes display lanes for the split view: one lane per source node.
// Post-merge segments are appended to the first lane that "claims" the merge
// node (first-come-first-served in source order), so the longest lane is the
// one whose source feeds the first merge. The lane count equals the number of
// source nodes, which is also the peak parallelism of the process.
export function computeLanes(edges: Edge[], allNodeIds: string[]): string[][] {
  if (allNodeIds.length === 0) return []

  const adj   = new Map<string, string[]>()
  const inDeg = new Map<string, number>()
  for (const id of allNodeIds) { adj.set(id, []); inDeg.set(id, 0) }
  for (const e of edges) {
    if (!adj.has(e.load) || !inDeg.has(e.unload)) continue
    adj.get(e.load)!.push(e.unload)
    inDeg.set(e.unload, (inDeg.get(e.unload) ?? 0) + 1)
  }

  const sources       = allNodeIds.filter((id) => (inDeg.get(id) ?? 0) === 0)
  const mergeAssigned = new Set<string>()
  const lanes: string[][] = []

  for (const src of sources) {
    const lane: string[] = []
    let cur: string | null = src

    while (cur !== null) {
      const node = cur  // const narrows to string; cur is mutable so TS won't narrow it
      lane.push(node)
      const nexts: string[] = adj.get(node) ?? []

      if (nexts.length === 0) {
        cur = null  // sink — end of lane
      } else {
        const next: string = nexts[0]  // follow first successor; forks: first edge wins
        if ((inDeg.get(next) ?? 0) >= 2) {
          if (!mergeAssigned.has(next)) {
            mergeAssigned.add(next)
            cur = next  // claim merge node and continue this lane through it
          } else {
            cur = null  // another lane already owns this merge — stop here
          }
        } else {
          cur = next
        }
      }
    }

    if (lane.length > 0) lanes.push(lane)
  }

  return lanes
}
