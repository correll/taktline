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
   *  their own location names, or what is still missing. */
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
  /** A location two or more routes arrive at — parts coming together. */
  merge?: { _id: string; name: string }
  /** A location with arrivals but no departures — finished goods stop here. */
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

export const TOUR_STEPS: TourStep[] = [
  {
    id: 'welcome',
    title: 'Build your first line',
    body: "We'll draw a tiny but complete line right on the map — two parts (Steel and Motor) that merge into an Assembly, flow on to Testing, and finish in a Warehouse — then run a lot through it. Follow the highlights; the tour advances on its own as you go. It takes about five minutes. Press Next to begin.",
  },
  {
    id: 'open-map',
    title: 'Open the map',
    body: "We'll lay the line out on the map — the floor where your locations live. Open the Map view from the top bar.",
    target: 'nav-map',
    isDone: (c) => c.pathname === '/map',
  },
  {
    id: 'map-add-locations',
    title: 'Drop five locations',
    body: (c) => {
      const left = SUGGESTED_COUNT - c.stations.length
      return "Locations are the physical places on your floor where work happens. Click the location tool (the pin, top-left), then click the map to drop one — a dialog opens so you can name it. Add five. We'll call ours Steel, Motor, Assembly, Testing and Warehouse, but the names are yours — use your own real stations if you prefer, the tour follows along either way. Drag any location to reposition it."
        + (left > 0 ? ` ${left} to go.` : "")
    },
    target: 'map-tool-location',
    isDone: (c) => c.stations.length >= SUGGESTED_COUNT,
  },
  {
    id: 'map-add-routes',
    title: 'Connect them into a flow',
    body: (c) => {
      const base = "Now the route tool (the connector, top-left). Click a source location, then a target, to draw an arrow between them — that's a step in the flow. Wire four, following our example: Steel → Assembly, Motor → Assembly, Assembly → Testing, Testing → Warehouse. What matters is the shape, not the names: two routes arriving at one location make it a merge — where parts come together, and a last location with no outgoing route becomes your finished-goods store. (Click a route to delete it; Esc cancels.)"
      const { routeCount, merge, warehouse } = shapeOf(c)
      const missing: string[] = []
      if (!merge) missing.push("two routes arriving at the same location, to make a merge")
      if (!warehouse) missing.push("a final location with no outgoing route")
      if (!missing.length && routeCount < 4) missing.push(`${4 - routeCount} more route(s)`)
      return missing.length ? `${base}\n\nStill needed: ${missing.join("; ")}.` : base
    },
    target: 'map-tool-route',
    isDone: hasLineShape,
  },
  {
    id: 'see-in-settings',
    title: 'See & fine-tune it in Settings',
    body: "Everything you just drew is also in Settings — open it. Your Locations, Process, and Routes are here as editable lists, and it's where you add lot templates, rename things, or upload a floor-plan image under Settings → Map. (On the map you can also right-click a location to edit or delete it.)",
    target: 'nav-settings',
    isDone: (c) => c.pathname === '/settings',
  },
  {
    id: 'open-lots',
    title: 'See your board',
    body: (c) => {
      const { merge, warehouse } = shapeOf(c)
      return `Open the Lots board from the top bar. ${merge?.name ?? 'Your merge station'} now appears as a merge of the two parts feeding it, flowing on to ${warehouse?.name ?? 'the warehouse'} — a complete little line, one column per location.`
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
