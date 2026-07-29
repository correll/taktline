import React from 'react'
import { STATION_ICONS } from '../components/map/StationNode'
import { color, font, size, shadow } from '../theme/tokens'
import { useHelpStore } from './helpStore'
import { TaktlineLogo } from '../components/TaktlineLogo'
import { FigureBottleneck, FigureFlow, FigureMerge, FigurePull } from './ManualFigures'

const H2: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <h2 style={{ color: color.textPrimary, fontSize: 18, marginTop: size.sp8, marginBottom: size.sp3,
               borderBottom: `1px solid ${color.border}`, paddingBottom: size.sp2 }}>{children}</h2>
)
const H3: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <h3 style={{ color: color.textPrimary, fontSize: 14, marginTop: size.sp5, marginBottom: size.sp2 }}>{children}</h3>
)
const P: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p style={{ color: color.textSecondary, fontSize: 13.5, lineHeight: 1.65, margin: `${size.sp2} 0` }}>{children}</p>
)
const B: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <strong style={{ color: color.textPrimary }}>{children}</strong>
)
const LI: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <li style={{ color: color.textSecondary, fontSize: 13.5, lineHeight: 1.6, marginBottom: 6 }}>{children}</li>
)
const Code: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span style={{ fontFamily: font.mono, fontSize: 12.5, color: color.blueBright }}>{children}</span>
)

// Prebuilt connectors shipped with Taktline (connectors/taktline_connect).
const CONNECTORS: { name: string; maps: string }[] = [
  { name: 'Odoo',                maps: 'Manufacturing Orders' },
  { name: 'NetSuite',            maps: 'Work Orders' },
  { name: 'Shopify',             maps: 'Paid orders · cancels & refunds' },
  { name: 'WooCommerce',         maps: 'Processing orders' },
  { name: 'QuickBooks Online',   maps: 'Accepted Estimates' },
  { name: 'Xero',                maps: 'Accepted Quotes' },
  { name: 'ShipStation',         maps: 'Awaiting-shipment orders' },
  { name: 'Generic REST / JSON', maps: 'Any JSON orders endpoint' },
]

export function UserManual() {
  const open = useHelpStore((s) => s.manualOpen)
  const close = useHelpStore((s) => s.closeManual)
  const startTour = useHelpStore((s) => s.startTour)
  if (!open) return null

  return (
    <div onClick={close} style={{
      position: 'fixed', inset: 0, background: color.backdrop, zIndex: 10000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: size.sp6,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: 760, maxWidth: '100%', maxHeight: '90vh', display: 'flex', flexDirection: 'column',
        background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
        boxShadow: shadow.lg,
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: `${size.sp4} ${size.sp6}`, borderBottom: `1px solid ${color.border}`, flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3 }}>
            <TaktlineLogo height={18} mark color={color.textPrimary} />
            <span style={{ fontFamily: font.sans, fontWeight: 500, letterSpacing: '0.1em', color: color.textPrimary, fontSize: 14 }}>
              Taktline · User manual
            </span>
          </div>
          <button onClick={close} style={{ background: 'none', border: 'none', color: color.textDim, cursor: 'pointer', fontSize: 22, lineHeight: 1 }}>×</button>
        </div>

        {/* Body */}
        <div style={{ overflowY: 'auto', padding: `${size.sp4} ${size.sp8} ${size.sp8}`, fontFamily: font.sans }}>
          <ManualContent />

          <div style={{ marginTop: size.sp8, display: 'flex', gap: size.sp3 }}>
            <button onClick={startTour}
                    style={{ background: color.bluePrimary, color: color.white, border: 'none', borderRadius: size.radius,
                             padding: `${size.sp2} ${size.sp5}`, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              Take the interactive tour
            </button>
            <button onClick={close}
                    style={{ background: 'transparent', color: color.textSecondary, border: `1px solid ${color.border}`,
                             borderRadius: size.radius, padding: `${size.sp2} ${size.sp5}`, fontSize: 13, cursor: 'pointer' }}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** The manual body — shared by the in-app overlay above and the public
 *  /manual page on the landing site (same content, no sign-in needed). */
export function ManualContent() {
  return (
    <>
          <P>
            Taktline is a digital <B>Kanban / Manufacturing Execution System</B>. It models your
            production as a <B>graph</B>: locations are nodes, transfers between them are edges, and
            physical work travels through the graph as <B>lot cards</B>. This manual uses a running
            example — assembling an <B>e-bike</B> — to explain the ideas.
          </P>

          <H2>Philosophy</H2>
          <P>
            A factory is a flow. Taktline makes that flow explicit and visible so you can see where
            work is, how long each step takes, and where it piles up. Four principles:
          </P>
          <ul>
            <LI><B>Model the flow as a graph.</B> Draw the real process once — where things happen and
              how they connect — and every view (map, board, statistics) derives from it.</LI>
            <LI><B>Work travels on cards.</B> A lot card is attached to a physical lot of products and
              moves with it from station to station, carrying quantity and history.</LI>
            <LI><B>Assemblies are merges, disassemblies are splits.</B> When several parts come
              together into one product, their precursor cards are consumed and a new assembly card
              is born. When one piece of material becomes many — a bar cut into tubes — the card
              multiplies along the split route instead.</LI>
            <LI><B>Map today, improve tomorrow.</B> Taktline maps your workflow exactly as it runs today.
              Don’t change anything yet — start using the system as-is, watch where work actually piles up,
              then reshape your process to maximize flow.</LI>
          </ul>

          <FigureFlow />

          <H2>The lean method in five steps</H2>
          <P>
            Taktline is built on <B>lean manufacturing</B> — a framework for doing more with less
            while staying focused on what the customer actually pays for. Lean is best learned at the
            <i> genba</i> (Japanese for "the actual place" — your shop floor), and it follows five
            proven steps, applied as a loop rather than a checklist:
          </P>
          <ul>
            <LI><B>1 · Define value.</B> Start from what your customer is paying for — quality, price,
              delivery time, sustainability. Every improvement is measured against this, and it changes
              as your business evolves.</LI>
            <LI><B>2 · Map the value stream.</B> List every step your product passes through and ask of
              each: does this add value the customer would pay for? Everything else — moving, waiting,
              storing, reworking — is <B>waste</B> to be reduced.</LI>
            <LI><B>3 · Create flow.</B> Any standstill is waste. Rearrange tasks, balance workloads
              across stations, and cross-train people so work keeps moving instead of piling up.</LI>
            <LI><B>4 · Establish pull.</B> Cap the work-in-process (WIP) in your line and let
              consumption at the <i>end</i> of the line trigger new work at the start — instead of
              pushing work in on a schedule. Kanban cards are the classic way to enforce this cap.</LI>
            <LI><B>5 · Pursue perfection.</B> Re-evaluate continuously — walk the floor
              (<i>genba walks</i>), question whether the process still meets customer needs, and improve
              in small, deliberate steps (<i>kata</i>). The closer you get to optimal, the fewer rules
              of thumb apply.</LI>
          </ul>

          <H3>Value stream mapping</H3>
          <P>
            A <B>value stream</B> is the sequence of activities that incrementally adds value to a
            product — from raw material to finished good. <B>Value stream mapping</B> makes that
            sequence visible: which stations work adds value at, how material travels between them, and
            where it sits idle. On a real floor the stream spans machines, people, and buildings over
            days — far too much to see from any one spot. That's why mapping it, and getting live data
            onto the map, is the first step of every lean effort: you cannot improve what you cannot
            see. Once mapped, the stream tells you where to apply continuous improvement, where a
            sensor would pay off, and where (if anywhere) automation belongs — in that order.
          </P>

          <H3>The seven deadly wastes — TIMWOOD</H3>
          <P>
            Everything that does not directly create customer value is waste. The seven classic wastes
            spell <B>TIMWOOD</B>:
          </P>
          <ul>
            <LI><B>T · Transport</B> — moving material between stations, buildings, or continents.
              Easy to spot, and the first place to gain: shorten distances, reorder stations, group
              destinations.</LI>
            <LI><B>I · Inventory</B> — raw stock, and especially <B>work-in-process (WIP)</B>: partly
              finished goods binding capital, labor, and space. WIP piling up in front of a station is
              the signature of a bottleneck — and it <i>hides</i> other problems by buffering them.</LI>
            <LI><B>M · Motion</B> — what workers' bodies do: reaching, bending, turning, walking.
              Motion costs time and sometimes health; fix it with better cell layout and tool
              placement.</LI>
            <LI><B>W · Waiting</B> — people waiting on machines or on each other. The cure is
              measuring cycle times and <B>balancing the line</B>.</LI>
            <LI><B>O · Over-processing</B> — steps the customer never asked for: treating all variants
              identically because routing them is hard, polishing what no one sees.</LI>
            <LI><B>O · Overproduction</B> — making more, or sooner, than is actually ordered. Often
              caused by chasing utilization metrics; the pull system is its antidote.</LI>
            <LI><B>D · Defects</B> — broken or off-spec parts and the rework they trigger. Defects
              compound: the later one is found, the more added value is thrown away with it. WIP
              makes this worse — a systematic defect fills the whole buffer before it's caught.</LI>
          </ul>
          <P>
            Waste is hard to see because it almost always looks <i>necessary</i> — it only becomes
            visible once you imagine a better way. Two numbers help you reason about it:
            <B> Little's law</B>, <i>lead&nbsp;time ≈ WIP ÷ production&nbsp;rate</i> — cut WIP in half
            and lead time halves with it — and <B>takt time</B>, the beat your line must hold to meet
            customer demand (<i>available&nbsp;time ÷ demand</i>). A line is balanced when every
            station's cycle time is close to takt.
          </P>

          <H3>Takt time, cycle time and line cycle time</H3>
          <P>
            These three get muddled constantly, and the confusion is expensive: they answer different
            questions, and only one of them is something you choose.
          </P>
          <ul>
            <LI><B>Takt time — the beat you need.</B> Available working time ÷ customer demand. If you
              work 8 hours and need 120 units, takt is 4 minutes: one unit must leave every 4 minutes.
              It is a <i>target you set</i>, never a measurement — it comes from your customer, not
              your floor. Set it per process in <B>Settings → Processes → Desired takt time</B>.</LI>
            <LI><B>Cycle time — how long the work takes.</B> The time an operator actually spends on a
              unit at a station: exactly what Taktline records between <B>Start</B> and <B>Stop</B>,
              divided by the units in the lot. Measured, per station, and the number to compare
              against takt. A station whose cycle time exceeds takt cannot keep up, no matter how well
              it is run.</LI>
            <LI><B>Line cycle time — how often a piece actually leaves.</B> The real exit rate: the
              interval between departures from a station, per piece. The clock starts when work
              <i>could</i> have moved — the beginning of the shift — and restarts at each departure,
              so a lot finished after hours is charged to the next shift rather than to the night. A
              lot of ten leaving counts as ten pieces, not one.</LI>
          </ul>
          <P>
            The gap between cycle time and line cycle time is where the waste lives. If a station takes
            2 minutes of work but a piece only leaves every 9 minutes, the other 7 minutes are queueing,
            blocking, transport or waiting — none of it work, all of it lead time. Speeding up the
            operator would win you nothing; the constraint is elsewhere. And if line cycle time is
            longer than takt anywhere in the flow, you are not meeting demand, whatever the cycle times
            say.
          </P>

          <H2>Getting lean with Taktline</H2>
          <P>
            Taktline is a <B>digital lean</B> tool: it gives you the bird's-eye, real-time view of your
            value stream that lets you spot in hours what a clipboard study finds in weeks. Here is how
            each part of the app serves the five steps and hunts each waste:
          </P>
          <H3>Map the value stream — literally</H3>
          <ul>
            <LI>The <B>Map view</B> <i>is</i> your value stream map: stations on your real floor plan,
              routes showing how work flows, drawn to scale. The <B>heatmap</B> shows where WIP
              concentrates — a red station is your bottleneck candidate.</LI>
            <LI>Because station positions are to scale, the <B>transport</B> statistic measures real
              meters traveled per lot. Watch it drop as you rearrange the floor — that's waste
              <B> T</B> shrinking.</LI>
            <LI>The <B>Lots board</B> is the same stream flattened into columns. Wildly different card
              counts per column = an unbalanced line, visible at a glance (wastes <B>I</B> and
              <B> W</B>).</LI>
          </ul>
          <H3>See waste in the statistics</H3>
          <ul>
            <LI><B>Cycle time per station</B> — each station's average working time per unit. Compare
              it against the takt your demand requires; the slowest station sets your whole line's
              production rate, so speed that one up first (waste <B>W</B>).</LI>
            <LI><B>Line cycle time per station</B> — how often a piece really leaves, measured from the
              start of the shift and re-anchored at every departure. When it is much larger than the
              cycle time beside it, the station is waiting rather than working, and the fix is upstream
              or in transport — not in the operator's hands (wastes <B>W</B>, <B>T</B> and
              <B> I</B>).</LI>
            <LI><B>OEE</B> (measured against your configured <B>work hours</B>, so nights and weekends
              don't distort it) — a very high OEE means the station is a bottleneck with work queueing;
              a very low one means it's starved by an upstream constraint. Never optimize OEE for its
              own sake — chasing utilization <i>creates</i> overproduction (waste <B>O</B>).</LI>
            <LI><B>Lot history</B> — every card records when it arrived, who worked it, and how long.
              That's Little's law made measurable: WIP, production rate, and lead time from live data,
              not estimates.</LI>
            <LI><B>Flagging & card events</B> — flag a defective lot and trace back exactly where it
              was and when (waste <B>D</B>); the audit trail survives even deletion.</LI>
          </ul>
          <FigureBottleneck />

          <H3>Run a pull system</H3>
          <ul>
            <LI>Lot cards <i>are</i> Kanban cards. Creating lots by <B>pulling from the end of the
              line</B> (the warehouse) seeds exactly the precursors one order needs — no more. That's
              pull: downstream demand triggers upstream work (wastes <B>I</B> and <B>O</B>).</LI>
            <LI>Taktline warns you when you pull at an intermediate station: building intermediate
              product ahead of demand is overproduction by another name.</LI>
            <LI><B>Production orders</B> extend pull all the way to the customer: an order in your shop
              or ERP releases the lots, and the finished good reaching the warehouse reports completion
              back. Customer demand — not a forecast — sets the pace.</LI>
            <LI><B>Merge stations</B> encode your bill of materials as edge weights (3 × motor + 1 ×
              frame), so precursors are made in the right ratio — never "a few extra just in case".</LI>
          </ul>
          <FigurePull />

          <H3>Improve continuously</H3>
          <ul>
            <LI>Model your process <B>as it runs today</B> — resist redesigning it on day one. After a
              week of real data the bottleneck is usually not where everyone believed it was.</LI>
            <LI>Make one small change at a time (<i>kata</i>), then watch the heatmap, takt and OEE
              respond. The statistics are your before/after evidence.</LI>
            <LI>Use the Map view on a tablet during <B>genba walks</B> — the live picture in hand,
              at the actual place.</LI>
            <LI>Considering a new machine or robot? Do lean first: the savings from layout and flow
              come free, and the value stream data then tells you exactly what the machine must do —
              and whether it pays.</LI>
          </ul>

          <H2>Core concepts</H2>
          <ul>
            <LI><B>Location (station)</B> — a place where work happens: a node in the graph. E.g.
              <i> Steel Inventory, Frame Welding, Bike Testing</i>.</LI>
            <LI><B>Route</B> — a directed edge from one location to another. Its <B>quantity</B> is how
              many upstream units are consumed per downstream unit (e.g. an assembly needs 3 of part B).</LI>
            <LI><B>Process</B> — a named collection of routes forming a <B>directed acyclic graph</B>.
              Cycles are rejected so the board can be laid out in flow order.</LI>
            <LI><B>Queue / source</B> — a location with no incoming routes. New lots originate here from a
              lot template.</LI>
            <LI><B>Merge station</B> — a location with two or more incoming routes. Precursor lots are
              consumed there and a new assembly lot is created; each route's weight is how many
              upstream units go into one assembly.</LI>
            <LI><B>Split station</B> — the mirror image: a location with two or more outgoing routes,
              where one unit becomes several pieces. A route's weight is how many pieces each unit
              yields (one steel bar cut into four tubes), so advancing a lot along it multiplies the
              card — and pulling four tubes orders just one bar.</LI>
            <LI><B>Warehouse</B> — a leaf with no outgoing routes: where finished goods end up.</LI>
            <LI><B>Lot template</B> — the card design for a product, pinned to the source location that
              originates it.</LI>
            <LI><B>Lot card</B> — travels with a physical lot; holds a total quantity distributed across
              <B> bins</B> (one per current location).</LI>
            <LI><B>Work session</B> — an operator's timer at a station; feeds the <B>OEE</B> and
              <B> takt-time</B> statistics.</LI>
          </ul>

          <FigureMerge />

          <H2>Station icons</H2>
          <P>When you create a location you can give it an icon so the map and board read at a glance.
             These are the built-in icons:</P>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: size.sp2, marginTop: size.sp3 }}>
            {STATION_ICONS.map(({ id, label, Icon }) => (
              <div key={id} style={{ display: 'flex', alignItems: 'center', gap: size.sp2,
                                     background: color.bgCard, border: `1px solid ${color.border}`,
                                     borderRadius: size.radius, padding: `${size.sp2} ${size.sp3}` }}>
                <Icon size={16} color={color.blueBright} />
                <span style={{ fontSize: 12, color: color.textSecondary }}>{label}</span>
              </div>
            ))}
          </div>

          <H2>Setting up a line</H2>
          <P>Configuration lives under <B>Settings</B> (admins only). Build a line in four moves:</P>
          <H3>1 · Locations</H3>
          <P>On <B>Settings → Locations</B>, add every place work happens. For the e-bike frame branch
             that's <i>Steel Inventory → Tube Cutting → Frame Welding → Frame Painting</i>; the drivetrain
             branch is <i>Parts Inventory → Drivetrain Assembly → Drivetrain QC</i>.</P>
          <H3>2 · Process &amp; routes</H3>
          <P>On <B>Settings → Processes</B>, create a process and open <B>Routes</B> to connect the
             locations in flow order. Point both branches at <i>Frame Integration</i> — with two incoming
             routes it becomes a <B>merge</B> that combines a frame and a drivetrain into an e-bike
             assembly. Continue <i>Frame Integration → Electrical Installation → Bike Testing → Final
             Packaging → Finished Goods Warehouse</i>.</P>
          <H3>3 · Templates</H3>
          <P>On <B>Settings → Templates</B>, add a lot template for each product, pinned to the location
             that originates it (e.g. <i>E-Bike Frame</i> starting at Steel Inventory). Source queues use
             these to create new lots; the merge station uses the assembly template for its output.</P>
          <H3>4 · Map</H3>
          <P>On <B>Settings → Map</B>, optionally upload a floor-plan image and set the scale (pixels per
             meter/foot) so the Map view shows your stations on the real layout with a heatmap of activity.</P>

          <H2>Operating the line</H2>
          <H3>Lots board</H3>
          <P>The <B>Lots</B> view is your kanban board — one column per location, in flow order. Source
             queues have a <B>+ create lot</B> button; merge stations offer <B>⬇ pull precursors</B> and a
             <B> Merge</B> action when enough inputs are present. Admins can press <B>DRAG</B> to unlock the
             board and move lots between stations (dragging a merged assembly backward <B>un-merges</B> it
             into its parts). If you try to drag while the board is locked, the lock button flashes.</P>
          <H3>Operator view</H3>
          <P>The <B>Operator</B> view is the shop-floor screen (also the default in portrait / tablet
             mode). Pick your station, select a lot, set the quantity and press <B>Start</B> to run the
             timer; press <B>Stop</B> when done, then <B>Move</B> to advance the lot to the next station.
             Operators can log time and advance lots along defined routes, but not reconfigure the line.</P>
          <H3>Statistics</H3>
          <P>The <B>Statistics</B> view aggregates each station's <B>takt-time</B> (average time per unit),
             <B> OEE</B> (running time ÷ elapsed time), throughput, and transport. This is where the timing
             your operators capture turns into insight.</P>

          <H2>Who can do what</H2>
          <P><B>Admins</B> configure the line (locations, routes, templates, floor plan) and manage the
             team. <B>Members</B> get a read-only board plus the Operator view — they can log work and
             advance lots, but not change the process. Invite teammates from <B>Settings → Members</B>.</P>

          <H2>Integrations &amp; ERP</H2>
          <P>Connect your ERP, online store, or automation tools from <B>Settings → Integrations</B>.
             Every integration authenticates with a scoped <B>API key</B> and speaks one small, stable
             contract — so orders flow in and completions flow back without any custom code in Taktline's
             core. Taktline owns the flow graph and execution; your ERP keeps owning the bill of materials
             and inventory.</P>

          <H3>API keys &amp; scopes</H3>
          <P>Create a key under <B>Settings → Integrations</B> — it's shown once, company-scoped, and
             revocable. Grant only the scopes an integration needs:</P>
          <ul>
            <LI><Code>orders</Code> — release production orders, drain completions, and cancel.</LI>
            <LI><Code>cards:advance</Code> — advance a lot along a route (scan-to-advance) and print lot
              labels.</LI>
            <LI><Code>reports</Code> — read-only order &amp; throughput feeds for BI dashboards.</LI>
          </ul>

          <H3>The order contract</H3>
          <P>Every integration uses the same endpoints, so connectors stay thin:</P>
          <ul>
            <LI><B>Release</B> — <Code>POST /orders</Code> creates and releases a production run.
              Idempotent on <i>(source, externalRef)</i>, so a redelivered webhook never double-releases.</LI>
            <LI><B>Complete</B> — when a finished lot reaches a warehouse, Taktline records the completion;
              a connector polls <Code>GET /orders/outbox</Code>, delivers it, then acks. No lost or
              duplicated "done" events.</LI>
            <LI><B>Cancel</B> — <Code>POST /orders/cancel</Code> (by <i>source</i> + <i>externalRef</i>)
              scraps the in-flight lots. This is the path a store's <B>cancel or refund</B> takes.</LI>
          </ul>

          <H3>Prebuilt connectors</H3>
          <P>Each system links to Taktline through a small connector that speaks this contract. We ship a
             ready-made connector for each of the systems below — it just needs an API key and a product
             mapping, with nothing to build and no work on the shop floor. Available today:</P>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: size.sp2, marginTop: size.sp3 }}>
            {CONNECTORS.map((c) => (
              <div key={c.name} style={{ background: color.bgCard, border: `1px solid ${color.border}`,
                                         borderRadius: size.radius, padding: `${size.sp2} ${size.sp3}` }}>
                <div style={{ fontSize: 13, color: color.textPrimary, fontWeight: 600 }}>{c.name}</div>
                <div style={{ fontSize: 12, color: color.textDim, marginTop: 2 }}>{c.maps}</div>
              </div>
            ))}
          </div>

          <H3>No-code &amp; automation</H3>
          <ul>
            <LI><B>CSV / Excel import</B> — release a batch straight from a spreadsheet in the Integrations
              tab. Columns: <Code>product</Code> (template name or id), <Code>quantity</Code>, optional
              <Code> source</Code>, <Code>externalRef</Code>, <Code>note</Code>. Each row is idempotent, and
              a bad row is reported without failing the rest.</LI>
            <LI><B>Zapier / Make / webhooks</B> — any tool that can send an HTTP request with the key can
              release and drain orders directly against the contract, with no connector to run.</LI>
            <LI><B>Generic REST</B> — point the <i>generic</i> connector at any JSON orders endpoint and map
              its field names; the on-ramp for systems like Zoho, Cin7/DEAR, MRPeasy, Acumatica, and
              Dynamics 365 Business Central.</LI>
          </ul>

          <H3>Shop floor &amp; dashboards</H3>
          <ul>
            <LI><B>Scan-to-advance &amp; labels</B> — print a lot label (Zebra/Brother <B>ZPL</B> with a
              barcode of the lot id). A scanner or print station holding a <Code>cards:advance</Code> key
              advances the lot the moment it's scanned — no logged-in screen needed.</LI>
            <LI><B>BI dashboards</B> — point <B>Power BI</B>, <B>Grafana</B>, or <B>Metabase</B> at the
              <Code> reports</Code> feeds (<Code>/reports/orders</Code>, <Code>/reports/throughput</Code>)
              with a <Code>reports</Code> key.</LI>
          </ul>

          <H3>Mapping products</H3>
          <P>Each integration maps an external product reference (an SKU, item code, or Odoo
             <Code> default_code</Code>) to a Taktline <B>lot-template id</B>. Copy the ids you need from the
             <B> Product ids</B> panel in Settings → Integrations, or grab the whole
             <Code> PRODUCT_MAPPING</Code> block with one click.</P>
    </>
  )
}
