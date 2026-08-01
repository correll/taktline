import { describe, expect, it } from 'vitest'
import { TOUR_STEPS, type TourCtx } from './tourSteps'

/**
 * The first five minutes anyone spends with the product.
 *
 * Both things checked here were reported by a real person going through the
 * tour, and both are the same class of mistake: the tour talking about its own
 * imagined line instead of the one in front of the user.
 */

const step = (id: string) => {
  const s = TOUR_STEPS.find((x) => x.id === id)
  if (!s) throw new Error(`no tour step "${id}" — was it renamed?`)
  return s
}
const text = (id: string, c: TourCtx) => {
  const b = step(id).body
  return typeof b === 'function' ? b(c) : b
}

let clock = 0
const station = (name: string) => ({
  _id: `st-${name}`, name, position: { x: 0, y: 0, width: 60, height: 60 },
  createdAt: new Date(Date.UTC(2026, 0, 1, 0, 0, clock++)).toISOString(),
  updatedAt: '', description: '', adapterType: null, adapterConfig: {},
}) as any

const route = (load: string, unload: string) => ({
  _id: `r-${load}-${unload}`, load: `st-${load}`, unload: `st-${unload}`,
  processId: 'p1', quantity: 1, createdAt: '', updatedAt: '',
}) as any

function ctx(names: string[], routes: any[] = [], pathname = '/map'): TourCtx {
  clock = 0
  return {
    pathname,
    stations: names.map(station),
    routes: Object.fromEntries(routes.map((r) => [r._id, r])),
    processes: {}, templates: {},
  }
}

const OURS = ['Steel', 'Motor', 'Assembly', 'Testing', 'Warehouse']
const THEIRS = ['Cutting', 'Bending', 'Welding', 'Paint', 'Finished goods']

describe('the Settings step', () => {
  it('does not advance on its own', () => {
    // Arriving at /settings used to complete the step, so it vanished at the
    // instant the user acted on it — sent to look at a page, then immediately
    // shown something else. `TourManager` renders a plain "Next" and runs no
    // auto-advance timer exactly when `isDone` is absent, so its absence *is*
    // the fix.
    expect(step('see-in-settings').isDone).toBeUndefined()
  })

  it('still points at the nav entry, and asks for Next', () => {
    expect(step('see-in-settings').target).toBe('nav-settings')
    expect(text('see-in-settings', ctx(OURS))).toMatch(/press Next/i)
  })

  it('leaves auto-advance on the steps where doing IS the point', () => {
    // The fix must not become "nothing advances by itself" — dropping stations
    // and drawing routes are actions the tour can see completed, and waiting
    // for Next there would make it feel broken.
    expect(step('map-add-stations').isDone).toBeTypeOf('function')
    expect(step('map-add-routes').isDone).toBeTypeOf('function')
  })
})

describe('the routing instruction', () => {
  it('uses the names the user actually chose', () => {
    const body = text('map-add-routes', ctx(THEIRS))
    expect(body).toContain('Cutting → Welding')
    expect(body).toContain('Bending → Welding')
    expect(body).toContain('Welding → Paint')
    expect(body).toContain('Paint → Finished goods')
    for (const ours of OURS) expect(body).not.toContain(ours)
  })

  it('reads exactly as before when the suggestion was followed', () => {
    const body = text('map-add-routes', ctx(OURS))
    expect(body).toContain('Steel → Assembly')
    expect(body).toContain('Motor → Assembly')
    expect(body).toContain('Assembly → Testing')
    expect(body).toContain('Testing → Warehouse')
  })

  it('names the connections still missing, in the user’s words', () => {
    const c = ctx(THEIRS, [route('Cutting', 'Welding'), route('Bending', 'Welding')])
    const body = text('map-add-routes', c)
    expect(body).toMatch(/Still to draw:/)
    expect(body).toContain('Welding → Paint')
    expect(body).toContain('Paint → Finished goods')
    // The two already drawn must not be listed as outstanding.
    expect(body.split('Still to draw:')[1]).not.toContain('Cutting → Welding')
  })

  it('stops nagging once all four are drawn', () => {
    const c = ctx(THEIRS, [
      route('Cutting', 'Welding'), route('Bending', 'Welding'),
      route('Welding', 'Paint'), route('Paint', 'Finished goods'),
    ])
    expect(text('map-add-routes', c)).not.toMatch(/Still to draw:/)
  })

  it('reads by creation order, not the order the API happened to return', () => {
    // `GET /stations/` has no ORDER BY. Naming stations positionally out of an
    // arbitrary array would produce an instruction that looks authoritative
    // and sends people to wire the wrong things together.
    const c = ctx(THEIRS)
    c.stations = [...c.stations].reverse()
    expect(text('map-add-routes', c)).toContain('Cutting → Welding')
  })

  it('falls back to the example names before five stations exist', () => {
    const body = text('map-add-routes', ctx(['Cutting', 'Bending']))
    expect(body).toContain('Steel → Assembly')
    expect(body).not.toMatch(/Still to draw:/)   // nothing to enumerate yet
  })
})
