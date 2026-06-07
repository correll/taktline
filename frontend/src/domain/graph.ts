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
