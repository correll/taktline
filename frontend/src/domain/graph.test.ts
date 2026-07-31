import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import {
  computeLanes,
  findAccumulations,
  hasCycle,
  mergeNodes,
  sourceNodes,
  stationRoles,
  topoSort,
  warehouseNodes,
  wouldCreateCycle,
  type Edge,
} from './graph'

/**
 * The frontend's own view of the process graph.
 *
 * This module decides what the board and the floor plan *say* about a line —
 * which stations are labelled MERGE or SPLIT, which lanes a fan draws into,
 * where a warning about accumulating work appears. It reaches those
 * conclusions without asking the server, which is why it can disagree with the
 * server, which is what it has done three times: grouping a merge modal by raw
 * routes so every branch appeared twice, counting a handoff link as a split
 * branch, and hiding the pull button at a station the backend would happily
 * pull at.
 *
 * Until now nothing here was tested at all — there was no test runner in the
 * frontend. The last block is the important one: it checks this module against
 * a fixture generated from the backend's own reasoning, so the two cannot
 * drift apart quietly again.
 */

const ROOT = join(__dirname, '..', '..', '..')
const e = (load: string, unload: string, processId = 'p1'): Edge & { processId: string } =>
  ({ load, unload, processId })

describe('cycles', () => {
  it('finds a direct loop', () => {
    expect(hasCycle([e('a', 'b'), e('b', 'a')])).toBe(true)
  })

  it('finds a long loop', () => {
    expect(hasCycle([e('a', 'b'), e('b', 'c'), e('c', 'd'), e('d', 'b')])).toBe(true)
  })

  it('does not mistake a diamond for a loop', () => {
    // One source feeding two branches that meet again is the commonest shape
    // in the product. Calling it a cycle would make half the real lines
    // undrawable.
    expect(hasCycle([e('a', 'b'), e('a', 'c'), e('b', 'd'), e('c', 'd')])).toBe(false)
  })

  it('answers for an edge that has not been drawn yet', () => {
    const existing = [e('a', 'b'), e('b', 'c')]
    expect(wouldCreateCycle(existing, 'c', 'a')).toBe(true)
    expect(wouldCreateCycle(existing, 'c', 'd')).toBe(false)
  })
})

describe('roles', () => {
  it('two feeds in one process make a merge', () => {
    expect(stationRoles([e('a', 'm'), e('b', 'm')], {}).m.merge).toBe(true)
  })

  it('two feeds in DIFFERENT processes do not', () => {
    // A shared paint booth is two value streams passing through one bench, not
    // an assembly. Getting this wrong would demand a merge at every station
    // two lines happen to share.
    const roles = stationRoles([e('a', 'm', 'p1'), e('b', 'm', 'p2')], {})
    expect(roles.m?.merge ?? false).toBe(false)
  })

  it('the same feed drawn twice is still one feed', () => {
    expect(stationRoles([e('a', 'm'), e('a', 'm')], {}).m?.merge ?? false).toBe(false)
  })

  it('a fan is a split unless the station says otherwise', () => {
    const edges = [e('s', 'x'), e('s', 'y')]
    expect(stationRoles(edges, {}).s.fan).toBe('split')
    expect(stationRoles(edges, { s: 'split' }).s.fan).toBe('split')
    expect(stationRoles(edges, { s: 'choice' }).s.fan).toBe('choice')
  })

  it('declares nothing for a station that neither merges nor fans', () => {
    const roles = stationRoles([e('a', 'b'), e('b', 'c')], {})
    expect(roles.b?.merge ?? false).toBe(false)
    expect(roles.b?.fan ?? null).toBe(null)
  })

  it('a station can be a merge and a split at once', () => {
    // The battery line's wash: a split branch and a cleaning feed both arrive,
    // and it fans out again afterwards.
    const roles = stationRoles([e('a', 'm'), e('b', 'm'), e('m', 'x'), e('m', 'y')], {})
    expect(roles.m).toEqual({ merge: true, fan: 'split' })
  })
})

describe('sources, merges and warehouses', () => {
  it('a source is a station nothing feeds', () => {
    expect([...sourceNodes([e('a', 'b'), e('b', 'c')])].sort()).toEqual(['a'])
  })

  it('a warehouse is a station that sends nowhere', () => {
    expect([...warehouseNodes([e('a', 'b'), e('b', 'c')])].sort()).toEqual(['c'])
  })

  it('mergeNodes agrees with stationRoles', () => {
    const edges = [e('a', 'm'), e('b', 'm'), e('m', 'z')]
    const roles = stationRoles(edges, {})
    const byRole = Object.entries(roles).filter(([, r]) => r.merge).map(([id]) => id)
    expect([...mergeNodes(edges)].sort()).toEqual(byRole.sort())
  })
})

describe('layout', () => {
  it('orders a chain sources first', () => {
    expect(topoSort([e('b', 'c'), e('a', 'b')], ['a', 'b', 'c'])).toEqual(['a', 'b', 'c'])
  })

  it('keeps isolated stations rather than dropping them', () => {
    // A station with no routes yet is one somebody is in the middle of wiring
    // up. Losing it from the board mid-edit is how you lose your place.
    expect(topoSort([e('a', 'b')], ['a', 'b', 'lonely']).sort())
      .toEqual(['a', 'b', 'lonely'])
  })

  it('does not hang on a cycle', () => {
    expect(() => topoSort([e('a', 'b'), e('b', 'a')], ['a', 'b'])).not.toThrow()
  })

  it('gives every station in a fan its own lane', () => {
    const lanes = computeLanes([e('s', 'x'), e('s', 'y')], ['s', 'x', 'y'])
    expect(lanes.length).toBeGreaterThan(1)
    expect(lanes.flatMap((l) => l.nodes).sort()).toEqual(['s', 'x', 'y'])
  })
})

describe('accumulation', () => {
  const flow = (load: string, unload: string, quantity: number) =>
    ({ load, unload, quantity, processId: 'p1' })

  // The documented shape, and the only one where the numbers mean anything: a
  // weight is legal exactly where the graph branches. `s` splits into two
  // branches — three pieces down one, one down the other — and both feed a
  // merge that takes one of each. So `b` receives three a cycle and gives up
  // one, and two pile up on the bench every single cycle.
  const DIAMOND = (n: number) => [
    flow('s', 'b', n), flow('s', 'd', 1), flow('b', 'm', 1), flow('d', 'm', 1),
  ]
  const IDS = ['s', 'b', 'd', 'm']

  it('reports the surplus where more arrives than leaves', () => {
    const found = findAccumulations(DIAMOND(3), IDS)
    const b = found.find((f) => f.stationId === 'b')
    expect(b, JSON.stringify(found)).toBeDefined()
    expect(b!.surplus).toBe(2)
  })

  it('says nothing when the rates match', () => {
    expect(findAccumulations(DIAMOND(1), IDS)).toEqual([])
  })

  it('never flags the merge itself', () => {
    // Its inputs are consumed there by design — that is what a merge is.
    expect(findAccumulations(DIAMOND(3), IDS).map((f) => f.stationId)).not.toContain('m')
  })

  it('never flags a warehouse', () => {
    // A shelf is meant to fill up. Warning about it is noise that teaches
    // people to ignore the warning that matters.
    const found = findAccumulations(DIAMOND(3), IDS, new Set(), new Set(['b']))
    expect(found.map((f) => f.stationId)).not.toContain('b')
  })

  it('never flags a station with its own branch to storage', () => {
    // It already has the relief valve the warning exists to recommend.
    const edges = [...DIAMOND(3), flow('b', 'store', 1)]
    const found = findAccumulations(edges, [...IDS, 'store'], new Set(), new Set(['store']))
    expect(found.map((f) => f.stationId)).not.toContain('b')
  })
})

// ── The contract with the backend ──────────────────────────────────────────

describe('agrees with the backend about the shipped lines', () => {
  const contract = JSON.parse(
    readFileSync(join(ROOT, 'contracts', 'station-roles.json'), 'utf8'),
  ) as Record<string, Record<string, boolean>>

  const examples = readdirSync(join(ROOT, 'examples')).filter((f) => f.endsWith('.json'))

  it('covers every line the repo ships', () => {
    expect(Object.keys(contract).sort())
      .toEqual(examples.map((f) => f.replace(/\.json$/, '')).sort())
  })

  for (const file of examples) {
    const name = file.replace(/\.json$/, '')

    it(`labels ${name} the way the server does`, () => {
      const doc = JSON.parse(readFileSync(join(ROOT, 'examples', file), 'utf8'))
      const partners = new Set(
        doc.stations.filter((s: any) => s.integrationProvider).map((s: any) => s.ref),
      )
      // An edge touching an integration node is a boundary link, not material
      // flow, and is excluded from every graph judgement. This is the rule the
      // frontend has forgotten before — twice.
      const edges = doc.routes
        .filter((r: any) => !partners.has(r.load) && !partners.has(r.unload))
        .map((r: any) => ({ load: r.load, unload: r.unload, processId: r.process }))

      const names: Record<string, string> = Object.fromEntries(
        doc.stations.map((s: any) => [s.ref, s.name]),
      )
      const roles = stationRoles(edges, {})
      const mine = Object.fromEntries(
        doc.stations.map((s: any) => [s.name, roles[s.ref]?.merge ?? false]),
      )
      void names
      expect(mine).toEqual(contract[name])
    })
  }
})
