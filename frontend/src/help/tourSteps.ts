import type { Station, Route, Process, LotTemplate } from '../models'

export interface TourCtx {
  pathname: string
  stations: Station[]
  routes: Record<string, Route>
  processes: Record<string, Process>
  templates: Record<string, LotTemplate>
}

export interface TourStep {
  id: string
  title: string
  /** A function when the wording depends on what the user actually built —
   *  their own station names, or what is still missing. */
  body: string | ((c: TourCtx) => string)
  target?: string                 // data-tour attribute to highlight
  isDone?: (c: TourCtx) => boolean // auto-advance when true (omit for info steps)
}

// The little line the tour builds: two parts that merge into an assembly, then
// flow on to a test station and finish in a warehouse.
//
// These names are only *suggestions* shown in the copy. Progress is judged on
// the SHAPE of what the user drew, never on what they called it — a typo
// ("Asembly") or a deliberate choice to use their own real station names must
// not strand someone five minutes into their first experience, staring at a
// tour that has silently stopped advancing with no way to find out why.
export const SUGGESTED = {
  sources: ['Steel', 'Motor'],
  merge: 'Assembly',
  followup: 'Testing',
  warehouse: 'Warehouse',
}
const SUGGESTED_COUNT = 5

interface Shape {
  routeCount: number
  /** A station two or more routes arrive at — parts coming together. */
  merge?: { _id: string; name: string }
  /** A station with arrivals but no departures — finished goods stop here. */
  warehouse?: { _id: string; name: string }
}

/** What the drawn graph *is*, independent of naming. */
function shapeOf(c: TourCtx): Shape {
  const routes = Object.values(c.routes)
  const incoming = new Map<string, number>()
  const outgoing = new Map<string, number>()
  for (const r of routes) {
    incoming.set(r.unload, (incoming.get(r.unload) ?? 0) + 1)
    outgoing.set(r.load, (outgoing.get(r.load) ?? 0) + 1)
  }
  return {
    routeCount: routes.length,
    merge: c.stations.find((s) => (incoming.get(s._id) ?? 0) >= 2),
    warehouse: c.stations.find(
      (s) => (incoming.get(s._id) ?? 0) >= 1 && !(outgoing.get(s._id) ?? 0)),
  }
}

/** The lesson: parts merge somewhere, flow onward, and end where they are kept. */
function hasLineShape(c: TourCtx): boolean {
  const { routeCount, merge, warehouse } = shapeOf(c)
  return routeCount >= 4 && !!merge && !!warehouse && merge._id !== warehouse._id
}

/**
 * The five stations the tour asked for, in the order they were dropped.
 *
 * Sorted by creation time because `GET /stations/` has no ORDER BY — the array
 * arrives in whatever order Postgres felt like returning, so "the first one you
 * placed" only means something once we sort. Without this the routing
 * instructions below would name the user's stations in an arbitrary order,
 * which is worse than naming ours: it would look authoritative and be wrong.
 */
function droppedInOrder(c: TourCtx) {
  const ordered = [...c.stations].sort((a, b) =>
    String(a.createdAt ?? '').localeCompare(String(b.createdAt ?? '')))
  return ordered.length >= SUGGESTED_COUNT ? ordered.slice(0, SUGGESTED_COUNT) : null
}

/**
 * The four connections to draw, worded with whatever the user actually called
 * their stations.
 *
 * The instruction used to be hard-coded to our suggested names — "Steel →
 * Assembly, Motor → Assembly, …" — while the step above openly invites people
 * to use their own. Someone who named their stations Cutting, Welding and
 * Paint was then told to wire up five things that do not exist on their floor
 * plan, and had to work out the mapping themselves at the exact moment they
 * know least about the product. Follow the suggestion and this reads word for
 * word as it did before.
 */
function wiringPlan(c: TourCtx) {
  const five = droppedInOrder(c)
  const names = five
    ? five.map((s) => s.name)
    : [...SUGGESTED.sources, SUGGESTED.merge, SUGGESTED.followup, SUGGESTED.warehouse]
  const [a, b, m, t, w] = names
  const legs: [number, number][] = [[0, 2], [1, 2], [2, 3], [3, 4]]

  const drawn = new Set(Object.values(c.routes).map((r) => `${r.load}>${r.unload}`))
  const steps = legs.map(([from, to]) => ({
    text: `${names[from]} → ${names[to]}`,
    done: five ? drawn.has(`${five[from]._id}>${five[to]._id}`) : false,
  }))
  return { a, b, m, t, w, steps, known: !!five }
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: 'welcome',
    title: 'Build your first line',
    body: "We'll draw a tiny but complete line right on the floor plan — two parts (Steel and Motor) that merge into an Assembly, flow on to Testing, and finish in a Warehouse — then run a lot through it. Follow the highlights; the tour advances on its own as you go. It takes about five minutes. Press Next to begin.",
  },
  {
    id: 'open-map',
    title: 'Open the floor plan',
    body: "We'll lay the line out on the floor plan — the floor where your stations live. Open the Floor plan view from the top bar.",
    target: 'nav-map',
    isDone: (c) => c.pathname === '/map',
  },
  {
    id: 'map-add-stations',
    title: 'Drop five stations',
    body: (c) => {
      const left = SUGGESTED_COUNT - c.stations.length
      return "Stations are the physical places on your floor where work happens. Click the station tool (the pin, top-left), then click the floor plan to drop one — a dialog opens so you can name it. Add five. We'll call ours Steel, Motor, Assembly, Testing and Warehouse, but the names are yours — use your own real stations if you prefer, the tour follows along either way. Drag any station to reposition it."
        + (left > 0 ? ` ${left} to go.` : "")
    },
    target: 'map-tool-station',
    isDone: (c) => c.stations.length >= SUGGESTED_COUNT,
  },
  {
    id: 'map-add-routes',
    title: 'Connect them into a flow',
    body: (c) => {
      const plan = wiringPlan(c)
      const base = `Now the route tool (the connector, top-left). Click a source station, then a target, to draw an arrow between them — that's a step in the flow. Here, connect ${plan.a} → ${plan.m}, ${plan.b} → ${plan.m}, ${plan.m} → ${plan.t}, and ${plan.t} → ${plan.w}. What matters is the shape, not the names: two routes arriving at one station make it a merge — where parts come together — and a last station with no outgoing route becomes your finished-goods store. (Click a route to delete it; Esc cancels.)`

      // Once we know their stations, name the connections still missing rather
      // than describing them in the abstract ("two routes arriving at the same
      // station"), which is only useful to someone who already understands the
      // model the tour is trying to teach.
      const left = plan.steps.filter((s) => !s.done).map((s) => s.text)
      if (plan.known && left.length) {
        return `${base}\n\nStill to draw: ${left.join(', ')}.`
      }

      const { routeCount, merge, warehouse } = shapeOf(c)
      const missing: string[] = []
      if (!merge) missing.push("two routes arriving at the same station, to make a merge")
      if (!warehouse) missing.push("a final station with no outgoing route")
      if (!missing.length && routeCount < 4) missing.push(`${4 - routeCount} more route(s)`)
      return missing.length ? `${base}\n\nStill needed: ${missing.join("; ")}.` : base
    },
    target: 'map-tool-route',
    isDone: hasLineShape,
  },
  {
    id: 'see-in-settings',
    title: 'See & fine-tune it in Settings',
    body: "Everything you just drew is also in Settings — open it. Your Stations, Process, and Routes are here as editable lists, and it's where you add lot templates, rename things, or upload a floor-plan image under Settings → Floor plan. (On the floor plan you can also right-click a station to edit or delete it.) Have a look around, then press Next.",
    target: 'nav-settings',
    // Deliberately no `isDone`. Arriving at /settings used to advance the tour
    // by itself, which meant the step vanished at the exact moment the user
    // acted on it — they clicked Settings and were immediately shown something
    // else, having read none of the page they had just been sent to look at.
    // Auto-advance is right when the instruction is "do this thing" and the
    // thing is the point (drop five stations, draw the routes); it is wrong
    // when the instruction is "go and look", because looking takes time.
  },
  {
    id: 'open-lots',
    title: 'See your board',
    body: (c) => {
      const { merge, warehouse } = shapeOf(c)
      return `Open the Lots board from the top bar. ${merge?.name ?? 'Your merge station'} now appears as a merge of the two parts feeding it, flowing on to ${warehouse?.name ?? 'the warehouse'} — a complete little line, one column per station.`
    },
    target: 'nav-lots',
    isDone: (c) => c.pathname === '/lots',
  },
  {
    id: 'pull-from-warehouse',
    title: 'Pull an order from the warehouse',
    body: (c) => `Demand starts at the finished-goods end. On the ${shapeOf(c).warehouse?.name ?? 'Warehouse'} column, click “⬇ pull precursors”: Taktline works backward through the whole line and seeds a lot in each source queue — creating default lot cards for you, no templates to set up. That's a pull system: a finished-goods order pulls raw material through the line. Then build forward — move both parts up into ${shapeOf(c).merge?.name ?? 'the merge'}, press “Merge”, and advance the assembly onward until it lands in ${shapeOf(c).warehouse?.name ?? 'the warehouse'}. Give it a try, then press Next.`,
    target: 'lots-pull',
  },
  {
    id: 'open-operator',
    title: 'Work a station',
    body: 'Open the Operator view — this is the shop-floor screen your team uses (and the default on a phone or tablet).',
    target: 'nav-operator',
    isDone: (c) => c.pathname === '/operator',
  },
  {
    id: 'operator-run',
    title: 'Run the line',
    body: 'Pick a station, select a lot, set how many pieces you’re working on, and press Start to run the timer; press Stop when done. Then advance the lot to the next station along the route — carry it all the way through Testing into the Warehouse, where it lands as a finished good. That timing is what powers the takt-time and OEE you’ll see in Statistics. Press Next to wrap up.',
  },
  {
    id: 'done',
    title: 'That’s a working line! 🎉',
    body: 'You built a line, arranged it on the floor, pulled a lot through a merge, ran a station, and sent a finished lot to the Warehouse. From here, invite your team from Settings → Members, and open the manual any time from the Help menu.',
  },
]
