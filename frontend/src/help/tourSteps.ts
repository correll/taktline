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
  body: string
  target?: string                 // data-tour attribute to highlight
  isDone?: (c: TourCtx) => boolean // auto-advance when true (omit for info steps)
}

// The little line the tour builds: two parts that merge into an assembly, then
// flow to a test station.
export const LINE = {
  sources: ['Steel', 'Motor'],
  merge: 'Assembly',
  followup: 'Testing',
  warehouse: 'Warehouse',
}
const ALL_STATIONS = [...LINE.sources, LINE.merge, LINE.followup, LINE.warehouse]

function idsByName(stations: Station[]): Map<string, string> {
  return new Map(stations.map((s) => [s.name.trim().toLowerCase(), s._id]))
}

function hasStations(c: TourCtx, names: string[]): boolean {
  const m = idsByName(c.stations)
  return names.every((n) => m.has(n.toLowerCase()))
}

function hasRoute(c: TourCtx, from: string, to: string): boolean {
  const m = idsByName(c.stations)
  const f = m.get(from.toLowerCase())
  const t = m.get(to.toLowerCase())
  if (!f || !t) return false
  return Object.values(c.routes).some((r) => r.load === f && r.unload === t)
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
    body: "Locations are the physical places on your floor where work happens. Click the location tool (the pin, top-left), then click the map to drop one — a dialog opens so you can name it. Add five: Steel, Motor, Assembly, Testing, and Warehouse. Drag any location to reposition it. The tour continues once all five exist.",
    target: 'map-tool-location',
    isDone: (c) => hasStations(c, ALL_STATIONS),
  },
  {
    id: 'map-add-routes',
    title: 'Connect them into a flow',
    body: "Now the route tool (the connector, top-left). Click a source location, then a target, to draw an arrow between them — that's a step in the flow. Wire four: Steel → Assembly, Motor → Assembly, Assembly → Testing, and Testing → Warehouse. Two routes into Assembly make it a merge where parts come together; the Warehouse, with no outgoing route, becomes your finished-goods store. (Click a route to delete it; Esc cancels.)",
    target: 'map-tool-route',
    isDone: (c) =>
      hasRoute(c, 'Steel', 'Assembly') &&
      hasRoute(c, 'Motor', 'Assembly') &&
      hasRoute(c, 'Assembly', 'Testing') &&
      hasRoute(c, 'Testing', 'Warehouse'),
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
    body: 'Open the Lots board from the top bar. Assembly now appears as a merge of Steel + Motor, flowing on to Testing and then the Warehouse — a complete little line, one column per location.',
    target: 'nav-lots',
    isDone: (c) => c.pathname === '/lots',
  },
  {
    id: 'pull-from-warehouse',
    title: 'Pull an order from the warehouse',
    body: "Demand starts at the finished-goods end. On the Warehouse column, click “⬇ pull precursors”: Taktline works backward through the whole line and seeds a Steel lot and a Motor lot in the source queues — creating default lot cards for you, no templates to set up. That's a pull system: a finished-goods order pulls raw material through the line. Then build forward — move both parts up into Assembly, press “Merge”, and advance the assembly through Testing into the Warehouse. Give it a try, then press Next.",
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
