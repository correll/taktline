import React from 'react'
import { STATION_ICONS } from '../components/map/StationNode'
import { color, font, size, shadow } from '../theme/tokens'
import { useHelpStore } from './helpStore'
import { TaktlineLogo } from '../components/TaktlineLogo'
import { FigureBottleneck, FigureFlow, FigureMerge, FigurePull } from './ManualFigures'
import { Eq, Frac, Sub, Sup, Term, Times, V } from './Equation'
import { CHAPTERS_META, MANUAL_ANCHORS, type ChapterId } from './manualAnchors'
import { ShareConceptButton } from '../share/ShareConceptButton'

/**
 * The manual, as chapters ordered by difficulty rather than one long scroll.
 *
 * One page worked at four sections; at thirty it buried the basics under
 * queueing theory and made "read the manual" a threat. The order is a
 * learning path: what the app is → the method it serves → the tools of that
 * method → the science underneath → the wiring. Deep links (`manualSection`)
 * keep working across the split: every anchor knows its chapter
 * (`manualAnchors.ts`), so a "Read more" from a tip or the line doctor
 * switches chapter and scrolls, exactly as it did when there was one page.
 */

// A heading that names one of the flow-science results carries a share button;
// every other heading renders exactly as before (`ShareConceptButton` returns
// null). Driving it off the anchor means the eight cannot drift out of sync
// with the eight sections.
const H2: React.FC<{ children: React.ReactNode; id?: string }> = ({ children, id }) => (
  <h2 id={id} style={{ color: color.textPrimary, fontSize: 18, marginTop: size.sp8, marginBottom: size.sp3,
               borderBottom: `1px solid ${color.border}`, paddingBottom: size.sp2,
               scrollMarginTop: size.sp4, display: 'flex', alignItems: 'center',
               gap: size.sp3 }}>
    <span style={{ flex: 1 }}>{children}</span>
    <ShareConceptButton anchor={id} />
  </h2>
)
const H3: React.FC<{ children: React.ReactNode; id?: string }> = ({ children, id }) => (
  <h3 id={id} style={{ color: color.textPrimary, fontSize: 14, marginTop: size.sp5, marginBottom: size.sp2,
               scrollMarginTop: size.sp4 }}>{children}</h3>
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

// ─── Chapter 1 · Basics ───────────────────────────────────────────────────────

function BasicsChapter() {
  return (
    <>
      <P>
        Taktline is a digital <B>Kanban / Manufacturing Execution System</B>. It models your
        production as a <B>graph</B>: stations are nodes, transfers between them are edges, and
        physical work travels through the graph as <B>lot cards</B>. A lot card is attached to a
        group of products — <B>lots contain products</B>, and every count in Taktline counts
        products, not cards. This manual uses a running example — assembling an <B>e-bike</B> —
        to explain the ideas.
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

      <H2 id="concepts">Core concepts</H2>
      <ul>
        <LI><B>Station</B> — a place where work happens: a node in the graph. E.g.
          <i> Steel Inventory, Frame Welding, Bike Testing</i>.</LI>
        <LI><B>Route</B> — a directed edge from one station to another. Its <B>quantity</B> is how
          many upstream products are consumed per downstream product (e.g. an assembly needs 3 of part B).</LI>
        <LI><B>Process</B> — a named collection of routes forming a <B>directed acyclic graph</B>.
          Cycles are rejected so the board can be laid out in flow order.</LI>
        <LI><B>Queue / source</B> — a station with no incoming routes. New lots originate here from a
          lot template.</LI>
        <LI><B>Merge station</B> — a station with two or more incoming routes. Precursor lots are
          consumed there and a new assembly lot is created; each route's weight is how many
          upstream products go into one assembly.</LI>
        <LI><B>Split station</B> — the mirror image: a station with two or more outgoing routes,
          where one product becomes several. A route's weight is how many pieces each product
          yields (one steel bar cut into four tubes), so advancing a lot along it multiplies the
          card — and pulling four tubes orders just one bar.</LI>
        <LI><B>Warehouse</B> — a leaf with no outgoing routes: where finished goods end up.</LI>
        <LI><B>Lot template</B> — the card design for a product, pinned to the source station that
          originates it.</LI>
        <LI><B>Lot card</B> — travels with a physical lot; holds a total quantity of products
          distributed across <B>bins</B> (one per current station).</LI>
        <LI><B>Work session</B> — an operator's timer at a station; feeds the <B>cycle-time</B> and
          <B> utilisation</B> statistics.</LI>
      </ul>

      <FigureMerge />

      <H2>Station icons</H2>
      <P>When you create a station you can give it an icon so the floor plan and board read at a glance.
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
      <H3>1 · Stations</H3>
      <P>On <B>Settings → Stations</B>, add every place work happens. For the e-bike frame branch
         that's <i>Steel Inventory → Tube Cutting → Frame Welding → Frame Painting</i>; the drivetrain
         branch is <i>Parts Inventory → Drivetrain Assembly → Drivetrain QC</i>.</P>
      <H3>2 · Process &amp; routes</H3>
      <P>On <B>Settings → Processes</B>, create a process and open <B>Routes</B> to connect the
         stations in flow order. Point both branches at <i>Frame Integration</i> — with two incoming
         routes it becomes a <B>merge</B> that combines a frame and a drivetrain into an e-bike
         assembly. Continue <i>Frame Integration → Electrical Installation → Bike Testing → Final
         Packaging → Finished Goods Warehouse</i>.</P>
      <H3>3 · Templates</H3>
      <P>On <B>Settings → Templates</B>, add a lot template for each product, pinned to the station
         that originates it (e.g. <i>E-Bike Frame</i> starting at Steel Inventory). Source queues use
         these to create new lots; the merge station uses the assembly template for its output.</P>
      <H3>4 · Map</H3>
      <P>On <B>Settings → Floor plan</B>, optionally upload a floor-plan image and set the scale (pixels per
         meter/foot) so the Floor plan view shows your stations on the real layout with a heatmap of activity.</P>

      <H2>Operating the line</H2>
      <H3>Lots board</H3>
      <P>The <B>Lots</B> view is your kanban board — one column per station, in flow order. Source
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
      <P>The <B>Statistics</B> view aggregates each station's <B>cycle time</B> (average working time
         per product), <B>line cycle time</B> (how often a product actually leaves), <B>utilisation</B>,
         throughput, and transport. This is where the timing your operators capture turns into
         insight — the <i>Lean method</i> chapter explains how to read it.</P>

      <H2>Who can do what</H2>
      <P><B>Admins</B> configure the line (stations, routes, templates, floor plan) and manage the
         team. <B>Members</B> get a read-only board plus the Operator view — they can log work and
         advance lots, but not change the process. Invite teammates from <B>Settings → Members</B>.</P>
    </>
  )
}

// ─── Chapter 2 · The lean method ─────────────────────────────────────────────

function LeanChapter() {
  return (
    <>
      <H2 id="lean-method">The lean method in five steps</H2>
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
        onto the floor plan, is the first step of every lean effort: you cannot improve what you cannot
        see. Once mapped, the stream tells you where to apply continuous improvement, where a
        sensor would pay off, and where (if anywhere) automation belongs — in that order.
      </P>

      <H3 id="waste">The seven deadly wastes — TIMWOOD</H3>
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
          caused by chasing utilisation metrics; the pull system is its antidote.</LI>
        <LI><B>D · Defects</B> — broken or off-spec parts and the rework they trigger. Defects
          compound: the later one is found, the more added value is thrown away with it. WIP
          makes this worse — a systematic defect fills the whole buffer before it's caught.</LI>
      </ul>
      <P>
        Waste is hard to see because it almost always looks <i>necessary</i> — it only becomes
        visible once you imagine a better way. The <i>Flow science</i> chapter puts numbers on it:
        <B> Little's law</B> ties WIP to lead time, and <B>takt time</B> — available time ÷ demand —
        is the beat your line must hold to meet customer demand.
      </P>

      <H3 id="muda-mura-muri">Muda, mura, muri</H3>
      <P>
        TIMWOOD lists the <i>muda</i> — the wastes themselves. Toyota named two companions that
        breed them: <B>mura</B>, unevenness — a line that lurches between flooded and starved
        produces waiting and inventory no matter how good each station is — and <B>muri</B>,
        overburden — asking a person or machine for more than it can sustainably give, which buys a
        short burst now and pays for it in defects, breakdowns and injuries later. The order of
        attack matters: level the unevenness first (see <i>heijunka</i>), relieve the overburden,
        and much of the muda disappears without being chased directly.
      </P>

      <H3 id="timing">Takt time, cycle time and line cycle time</H3>
      <P>
        These three get muddled constantly, and the confusion is expensive: they answer different
        questions, and only one of them is something you choose.
      </P>
      <ul>
        <LI><B>Takt time — the beat you need.</B> Available working time ÷ customer demand. If you
          work 8 hours and need 120 products, takt is 4 minutes: one product must leave every 4
          minutes. It is a <i>target you set</i>, never a measurement — it comes from your customer,
          not your floor. Set it per process in <B>Settings → Processes → Desired takt time</B>.</LI>
        <LI><B>Cycle time — how long the work takes.</B> The time an operator actually spends on a
          product at a station: exactly what Taktline records between <B>Start</B> and <B>Stop</B>,
          divided by the products in the lot. Measured, per station, and the number to compare
          against takt. A station whose cycle time exceeds takt cannot keep up, no matter how well
          it is run.</LI>
        <LI><B>Line cycle time — how often a product actually leaves.</B> The real exit rate: the
          interval between departures from a station, per product. The clock starts when work
          <i>could</i> have moved — the beginning of the shift — and restarts at each departure,
          so a lot finished after hours is charged to the next shift rather than to the night. A
          lot of ten leaving counts as ten products, not one.</LI>
      </ul>
      <P>
        The gap between cycle time and line cycle time is where the waste lives. If a station takes
        2 minutes of work but a product only leaves every 9 minutes, the other 7 minutes are queueing,
        blocking, transport or waiting — none of it work, all of it lead time. Speeding up the
        operator would win you nothing; the constraint is elsewhere. And if line cycle time is
        longer than takt anywhere in the flow, you are not meeting demand, whatever the cycle times
        say.
      </P>

      <H2 id="digital-lean">Getting lean with Taktline</H2>
      <P>
        Taktline is a <B>digital lean</B> tool: it gives you the bird's-eye, real-time view of your
        value stream that lets you spot in hours what a clipboard study finds in weeks. Here is how
        each part of the app serves the five steps and hunts each waste:
      </P>
      <H3>Map the value stream — literally</H3>
      <ul>
        <LI>The <B>Floor plan view</B> <i>is</i> your value stream map: stations on your real floor plan,
          routes showing how work flows, drawn to scale. The <B>heatmap</B> shows where WIP
          concentrates — a red station is your bottleneck candidate.</LI>
        <LI>Because station positions are to scale, the <B>transport</B> statistic measures real
          meters traveled per lot. Watch it drop as you rearrange the floor — that's waste
          <B> T</B> shrinking.</LI>
        <LI>The <B>Lots board</B> is the same stream flattened into columns. Wildly different card
          counts per column = an unbalanced line, visible at a glance (wastes <B>I</B> and
          <B> W</B>).</LI>
      </ul>
      <H3 id="statistics">See waste in the statistics</H3>
      <ul>
        <LI><B>Cycle time per station</B> — each station's average working time per product. Compare
          it against the takt your demand requires; the slowest station sets your whole line's
          production rate, so speed that one up first (waste <B>W</B>).</LI>
        <LI><B>Line cycle time per station</B> — how often a product really leaves, measured from the
          start of the shift and re-anchored at every departure. When it is much larger than the
          cycle time beside it, the station is waiting rather than working, and the fix is upstream
          or in transport — not in the operator's hands (wastes <B>W</B>, <B>T</B> and
          <B> I</B>).</LI>
        <LI><B>Utilisation</B> — the share of the crew's open work time spent working; idle,
          breakdowns and changeovers count against it. It is measured against your configured
          <B>work hours</B>, so nights and weekends don't distort it. It is not OEE, which also
          needs ideal cycle times and scrap counts that Taktline does not record. A very high
          utilisation means the station is a bottleneck with work queueing; a very low one means
          it's starved by an upstream constraint. Never optimize it for its own sake — chasing
          utilisation <i>creates</i> overproduction (waste <B>O</B>).</LI>
        <LI><B>Lot history</B> — every card records when it arrived, who worked it, and how long.
          That's Little's law made measurable: WIP, production rate, and lead time from live data,
          not estimates.</LI>
        <LI><B>Flagging & card events</B> — flag a defective lot and trace back exactly where it
          was and when (waste <B>D</B>); the audit trail survives even deletion.</LI>
      </ul>
      <FigureBottleneck />

      <H3 id="pull">Run a pull system</H3>
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
        <LI>Make one small change at a time (<i>kata</i>), then watch the heatmap, takt and utilisation
          respond. The statistics are your before/after evidence.</LI>
        <LI>Use the Floor plan view on a tablet during <B>genba walks</B> — the live picture in hand,
          at the actual place.</LI>
        <LI>Considering a new machine or robot? Do lean first: the savings from layout and flow
          come free, and the value stream data then tells you exactly what the machine must do —
          and whether it pays.</LI>
      </ul>
    </>
  )
}

// ─── Chapter 3 · The improvement toolkit ─────────────────────────────────────

function ToolkitChapter() {
  return (
    <>
      <P>
        The named techniques of lean, each in a few sentences: what it is, why it works, and where
        Taktline helps. They are ordered roughly as a shop adopts them — housekeeping and standards
        first, flow and levelling later.
      </P>

      <H2 id="five-s">5S — a place for everything</H2>
      <P>
        Sort, set in order, shine, standardize, sustain. Keep only what the work needs, give every
        tool and lot a marked home, clean as inspection (a wiped-down machine shows its leaks),
        make the arrangement the standard, and audit it so it survives busy weeks. 5S is not
        tidiness for its own sake: it removes the searching and reaching that pad every cycle time,
        and it makes abnormality visible — on a floor where everything has a place, the lot that is
        in the wrong one announces itself.
      </P>

      <H2 id="standard-work">Standard work</H2>
      <P>
        The current best way to do a job, written down: the steps, their order, their timing, and
        the WIP the station holds. Not a cage — a baseline. Without a standard there is no such
        thing as an abnormality, no way to train the next person, and no way to tell whether a
        change improved anything. Taktline's operator spread statistic shows where a standard is
        missing: two people at one bench with very different cycle times are usually running two
        private methods, and the faster one is the draft of the standard.
      </P>

      <H2 id="visual-management">Visual management</H2>
      <P>
        The state of the line should be readable from the aisle in five seconds: what is running,
        what is waiting, what is wrong. Andon lights, marked floor positions, card counts — and in
        Taktline, the floor plan's heatmap and the board's columns — all serve the same rule:
        <B> make the invisible visible, then make the abnormal obvious</B>. A metric nobody can see
        governs nothing.
      </P>

      <H2 id="layout">Layout &amp; cells</H2>
      <P>
        Distance is waste you walk. Trace one product's path across the floor plan — the classic
        <i> spaghetti diagram</i> — and the tangles show where the layout fights the flow. The lean
        answer is the <B>cell</B>: the stations one product family visits, placed next to each
        other in flow order, often in a U so one person can tend several steps. Taktline's
        transport statistic measures the walk in real meters, so a rearranged floor shows up as a
        falling number rather than a feeling.
      </P>

      <H2 id="flow">One-piece flow</H2>
      <P>
        Move products one at a time (or in the smallest lot the process allows) rather than in big
        batches. A batch of fifty waits as a block: the first product finished waits for the other
        forty-nine before anything moves, at every step. Halving the transfer batch roughly halves
        the queue time, touches nothing else, and costs nothing — which is why shrinking lots is
        usually the cheapest lead-time improvement available. The limit is the changeover (see
        <i> SMED</i>): flow gets as small as setups allow.
      </P>

      <H2 id="poka-yoke">Poka-yoke — mistake-proofing</H2>
      <P>
        Design the step so the error is impossible, not merely discouraged: the plug that only fits
        one way, the fixture that will not close on a mis-set part, the count that must reach zero.
        People err at a steady low rate however careful they are — a checklist asks for attention,
        a poka-yoke removes the need for it. Taktline plays its part structurally: routes only
        accept moves the graph allows, merges refuse the wrong precursors, and a scan-to-advance
        station will not advance the wrong lot.
      </P>

      <H2 id="jidoka">Jidoka — stop and fix</H2>
      <P>
        Automation with a human touch: any person or machine that detects a defect stops the line
        rather than passing the defect on. Stopping feels expensive and is cheap — the alternative
        is a buffer full of the same fault. The <i>andon cord</i> is jidoka's handle: anyone can
        pull it, and the problem is fixed where and when it happened, while the evidence is still
        warm. In Taktline, flagging a lot is the cord: the flag travels with the card and the
        history shows exactly where it was raised.
      </P>

      <H2 id="quality">Built-in quality</H2>
      <P>
        Quality cannot be inspected into a product; inspection only sorts what has already been
        made. And sorting at the end is the costliest moment to do it — every defect found at
        final test carries all the value added since the fault occurred. Build quality into the
        work instead: check at the step (<i>source inspection</i>), hand nothing defective
        forward, and treat every defect found downstream as a process problem upstream. The
        arithmetic is stark: a fault caught at its own station costs one cycle; the same fault
        caught at final test costs the whole line's work, plus the hunt. WIP multiplies the damage, because a systematic defect fills every
        buffer before the first bad product reaches anyone who notices.
      </P>

      <H2 id="smed">SMED — quick changeover</H2>
      <P>
        Single-Minute Exchange of Die: the discipline of cutting setup times. Separate <i>internal</i>
        setup (the machine must be stopped) from <i>external</i> (can be prepared while it still
        runs), convert internal to external, then streamline what remains. Long changeovers force
        big batches — nobody sets up for an hour to run ten products — and big batches poison flow.
        Every minute cut from a changeover permits a smaller lot, and the lot size, not the machine
        speed, usually sets the lead time.
      </P>

      <H2 id="heijunka">Heijunka — level the mix</H2>
      <P>
        Level production by volume and mix over the day rather than chasing each order as it
        arrives: A-A-B-A-C repeated, not a week of A then a famine. A lurching schedule whips every
        upstream station between overload and starvation (<i>mura</i> breeding <i>muri</i>), and
        suppliers see the whip amplified. Levelling trades a little order-response time for a line
        that runs at one sustainable pace — which is what takt time is for: the beat is only
        holdable if the schedule lets the line hold it.
      </P>

      <H2 id="maintenance">Total productive maintenance</H2>
      <P>
        The machine's operator is its first mechanic: cleaning, tightening and lubricating daily,
        noticing the new noise a fitter would meet a week later as a breakdown. TPM's measure is
        OEE (Taktline's utilisation shows only its availability side; it records no ideal cycle
        times or scrap), and its point is that availability is earned in advance — an unplanned stop at the
        constraint costs the whole line's output (see <i>Theory of constraints</i>), so the hour of
        planned maintenance that prevents it is the cheapest hour on the floor.
      </P>

      <H2 id="pdca">PDCA — the improvement loop</H2>
      <P>
        Plan, Do, Check, Act — Deming's wheel, and the shape of every real improvement. Plan a
        small change and <i>predict its effect</i>; do it, ideally at one station; check the
        statistics against the prediction — Taktline's before/after numbers are this step; act by
        standardizing what worked or discarding what did not, and go round again. The discipline is
        in the prediction: a change whose effect was never predicted teaches nothing either way.
      </P>

      <H2 id="five-whys">Five whys</H2>
      <P>
        Ask why until the answer is a process and not a person — usually about five times. The
        machine stopped: why? Overloaded fuse. Why? Bearing ran dry. Why? The lubrication schedule
        skips it. Why? It was added after the schedule was written. Why? No step in the
        new-equipment checklist updates the schedule. Fix the checklist and this failure — and its
        cousins — never recurs. Stop at "operator error" and it recurs next month wearing a
        different name. Blame is where root-cause analysis goes to die.
      </P>

      <H2 id="pareto">Pareto — the vital few</H2>
      <P>
        Most of the trouble comes from few of the causes: a handful of products carry most of the
        volume, a couple of stations most of the delay, one defect type most of the scrap. Rank
        before fixing — sort the statistics table by the number that hurts and work from the top.
        The discipline is as much about what <i>not</i> to fix: effort spread evenly across all
        causes improves none of them noticeably.
      </P>

      <H2 id="people">Respect for people</H2>
      <P>
        The other pillar of the Toyota system, and the one that makes the first one work. The
        person doing the job knows more about its waste than anyone reviewing it — improvement
        proposals flow up from the floor, not down from the office. Cross-train so people can
        follow the work (a balanced line needs movable skills), and never use the numbers against
        the people producing them: the moment a metric becomes a whip, it stops being measured
        honestly. Taktline's statistics describe stations and flow, not people, on purpose.
      </P>
    </>
  )
}

// ─── Chapter 4 · Flow science ────────────────────────────────────────────────

function ScienceChapter() {
  return (
    <>
      <P>
        The results behind the rules of thumb. Everything here is arithmetic on numbers Taktline
        already measures, and everything speaks one vocabulary: <B>lots contain products</B> — WIP,
        throughput and lead time all count <i>products</i>, and a lot is the card a group of them
        travels on. The line doctor applies each of these results automatically; this chapter is
        what its findings rest on.
      </P>

      <H2 id="littles-law">Little's law</H2>
      <Eq>
        <span>lead time</span><span>=</span>
        <Frac num={<span>products in process</span>} den={<span>throughput</span>} />
      </Eq>
      <P>
        The most useful equation on any shop floor, and the least escapable: it holds for any
        stable system, regardless of layout, scheduling, or luck. If 60 products are on the floor
        and 20 leave per day, a product spends three days inside — full stop. The lever it hands
        you: <B>halve the WIP and lead time halves</B>, with nobody working faster. It also works
        in reverse as a lie detector — promised lead times can be checked against WIP and
        throughput in one division.
      </P>

      <H2 id="kingman">Kingman's formula — why busy factories are slow</H2>
      <Eq>
        <V>W<Sub>q</Sub></V>
        <span>≈</span>
        <Term label="utilisation">
          <Frac num={<V>ρ</V>} den={<span>1 − <V>ρ</V></span>} />
        </Term>
        <Times />
        <Term label="variability">
          <Frac num={<span><V>c<Sub>a</Sub></V><Sup>2</Sup> + <V>c<Sub>s</Sub></V><Sup>2</Sup></span>}
                den={<span>2</span>} />
        </Term>
        <Times />
        <Term label="work time">
          <V>t<Sub>e</Sub></V>
        </Term>
      </Eq>
      <P>
        The queueing result (also called the VUT equation) that explains why busy factories are
        slow ones. <V>W<Sub>q</Sub></V> is how long a product waits before its work;{' '}
        <V>t<Sub>e</Sub></V> is the work time per product; <V>ρ</V> is utilisation;{' '}
        <V>c<Sub>a</Sub></V> and <V>c<Sub>s</Sub></V> measure how irregular the arrivals and the
        work times are (spread ÷ mean).
      </P>
      <P>
        The utilisation term is <B>hyperbolic</B>. At 80% a product waits about 4× its work time;
        at 90%, 9×; at 95%, 19×. Push a station toward full utilisation and queue time runs away —
        smoothly, with no warning knee. The variability term multiplies the same queue at the same
        utilisation: irregular arrivals or irregular work times inflate the wait even on a
        half-loaded station. So there are <B>two independent levers</B> — load and variability —
        and "keep everyone busy" attacks neither. It is the policy the formula punishes hardest.
      </P>

      <H2 id="balance">Balance efficiency</H2>
      <Eq>
        <V>E</V><span>=</span>
        <Frac num={<span>Σ work content per product</span>}
              den={<span><V>n</V> <Times /> slowest station's work content</span>} />
      </Eq>
      <P>
        How evenly the work is spread across the <V>n</V> stations of a line. Every station is
        paced by the slowest one, so the difference between a station's work content and the
        slowest station's is <B>structural idle time</B> — designed-in waiting, paid for every
        cycle, however well anyone works. Balance loss is 1 − <V>E</V>. A line with a 40-minute
        station and a 25-minute station carries 15 minutes of built-in waiting per product;
        moving work from the slow station to the fast one — or merging two short stations —
        recovers it without anyone hurrying.
      </P>

      <H2 id="flow-efficiency">Flow efficiency</H2>
      <Eq>
        <span>flow efficiency</span><span>=</span>
        <Frac num={<span>value-added time</span>} den={<span>lead time</span>} />
      </Eq>
      <P>
        Of the time a product spends in the building, the share in which anyone is actually
        working on it. Real processes usually land between <B>1% and 5%</B>, and the implication
        is uncomfortable: if a product receives 3 hours of work and spends 3 weeks inside,
        doubling the speed of <i>every machine</i> improves lead time by about 1%. The leverage
        is entirely in the waiting — which is why this metric and Kingman's formula are the same
        argument from two directions, and why cutting WIP (Little's law) beats buying speed
        almost everywhere.
      </P>

      <H2 id="variability">Common cause and special cause</H2>
      <P>
        Shewhart's distinction, and the most practical statistics a floor can learn. <B>Common-cause
        variation</B> is inherent to the process: many small influences, always present. You can
        only reduce it by changing the system itself. <B>Special-cause variation</B> has a findable,
        external origin — a bad batch of material, a worn tool, a Tuesday. The control chart makes
        the split operational: inside the limits, <i>don't react</i>; outside, investigate.
      </P>
      <P>
        Reacting to common-cause noise is <B>tampering</B>, and Deming's funnel experiment showed
        it reliably makes variance <i>worse</i> — adjusting a process for every wobble adds your
        adjustments to its noise. A station whose utilisation bounces between 58% and 66% has one kind of
        problem (a system to improve); a station that drops to 30% on Tuesdays has a different one
        (an event to find). Taktline's line doctor makes exactly this split when it reads cycle
        times, per station and product, on a control chart of time per piece: a lot above the
        upper limit (three sigma, with sigma estimated from the moving range between successive
        lots) means something interrupts the work — go and see those cycles, not the average;
        with every lot inside the limits, a broad spread (spread ÷ mean of 0.75 or more) means
        no standard.
      </P>

      <H2 id="matched-sets">Matched sets</H2>
      <P>
        At a merge, an assembly needs <i>all</i> of its precursor products before it can start —
        and the set completes at the arrival of its <B>slowest member, not its average</B>. That
        has a blunt consequence: 90% of precursor products finished can still mean <B>zero
        assemblies possible</B>. Part-level completion percentages mislead badly in assembly
        shops, and releasing partial kits just moves inventory closer to the point where it still
        cannot be used. Teardown is the sharp version: a pack that becomes modules, busbars and
        cables is only worth as much as <i>the last one back</i>. The fix is to pace every branch
        off the same demand (Taktline's pull does this arithmetic) and to buffer the erratic
        branch in matched sets — complete kits — never in full bins of whichever part is easiest
        to make.
      </P>

      <H2 id="monument">Monuments</H2>
      <P>
        The lean name for a large, fixed, expensive, high-capacity machine that the flow has to
        route around instead of the other way round — heat-treat furnaces, plating lines, the big
        paint booth. Monuments force batching, because nobody runs a furnace one product at a
        time; they break one-piece flow; they create contention between product families that
        otherwise would never interact; and they tend to become permanent constraints, since you
        cannot buy half a second one. The lean preference is several <B>right-sized machines
        placed in the flow</B>, even at worse unit economics on paper — the spreadsheet that
        favors the monument rarely prices the queueing it causes. Until then: schedule it
        deliberately, buffer in front of it, and treat its changeovers as the whole floor's
        problem, because they are.
      </P>

      <H2 id="constraints">Theory of constraints</H2>
      <P>
        Every line has exactly one slowest point at a time, and the system's throughput <i>is</i>
        that point's throughput. Goldratt's five focusing steps follow: <B>identify</B> the
        constraint; <B>exploit</B> it — the constraint must never wait, so buffer in front of it,
        stagger its breaks, move inspection and prep off it; <B>subordinate</B> everything else to
        its pace — running non-constraints faster only builds inventory; <B>elevate</B> it — buy
        capacity only once exploitation is exhausted, because it is the expensive step; and
        <B> repeat</B>, because fixing one constraint reveals the next. The arithmetic to keep:
        an hour lost at the constraint is an hour lost for the whole line, and an hour saved
        anywhere else is a mirage. Taktline's line doctor names the constraint of each value
        stream as the station with the <B>highest utilisation</B> — the share of its open time it
        is working, broken down or being changed over — and reports beside it, as evidence, how
        often a finished product's worth of work leaves it, how many products wait in front of
        it, and how idle the stations it feeds stand.
      </P>

      <H2 id="runout">The runout rule</H2>
      <P>
        A station several lines share — the saw every product crosses, the paint booth, the
        monument — keeps getting one question: <B>what should I run next?</B> FIFO is the wrong
        default there, because FIFO is fair to <i>lots</i>, and nobody cares about fairness to
        lots. The station exists to keep the lines it feeds running, so the honest question is
        which line starves first. Each line gets a clock:
        <B> runout&nbsp;=&nbsp;units buffered at the next station&nbsp;÷&nbsp;the rate they are
        actually consumed</B> — the next station's measured line cycle time, waste included,
        because a buffer is eaten at the rate work really leaves, not the rate it theoretically
        could. Run the lot for the line with the smallest clock. The rule is dynamic and
        self-correcting: a line that slows down stops pulling attention, a line about to starve
        rises to the top, and no line waits forever.
      </P>
      <P>
        Taktline's Operator view applies this for you: at a station with several lines flowing
        through, the lot picker sorts by runout and says why — <i>"Feeds Weld — starves in
        ~40 min"</i>, <i>"Feeds Pack — 2 d of buffer, no rush"</i>. Three honesty rules shape
        what it shows. A <B>storage</B> branch never starves — a warehouse is meant to fill, so
        lines feeding only a shelf get no clock. An <B>unmeasured</B> next station gives no clock
        either — null is not zero, and a recommendation built on data nobody recorded would be a
        horoscope — so those lots simply stay FIFO. And on a <B>single line</B> the rule changes
        nothing: with one consumer downstream, FIFO and runout agree, which is exactly as it
        should be. Where changeovers are expensive and the mix is stable, consider a fixed
        repeating sequence (a product wheel) instead — predictability lets the stations around
        the shared machine synchronize to it.
      </P>
    </>
  )
}

// ─── Chapter 5 · Integrations & ERP ──────────────────────────────────────────

function IntegrationsChapter() {
  return (
    <>
      <H2 id="integrations">Integrations &amp; ERP</H2>
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

const CHAPTER_BODIES: Record<ChapterId, React.FC> = {
  basics: BasicsChapter,
  lean: LeanChapter,
  toolkit: ToolkitChapter,
  science: ScienceChapter,
  integrations: IntegrationsChapter,
}

const CHAPTER_BLURBS: Record<ChapterId, string> = {
  basics: 'What Taktline is, the core concepts, and how to set up and run a line.',
  lean: 'The five steps, the seven wastes, and the three timing numbers.',
  toolkit: '5S to five whys — the named techniques, each in a few sentences.',
  science: 'Little, Kingman, Shewhart: the equations behind the rules of thumb.',
  integrations: 'API keys, the order contract, connectors, scanners and BI.',
}

/** The manual body — shared by the in-app overlay and the public /manual page
 *  on the landing site (same content, no sign-in needed). */
export function ManualContent() {
  const section = useHelpStore((s) => s.manualSection)
  const [chapter, setChapter] = React.useState<ChapterId>(() =>
    (section && MANUAL_ANCHORS[section]) || 'basics')

  // A deep link ("Read more" on a tip, a line-doctor finding) names a section;
  // switch to its chapter first, then scroll and flash once it exists.
  React.useEffect(() => {
    if (!section) return
    const target = MANUAL_ANCHORS[section]
    if (target) setChapter(target)
    const raf = requestAnimationFrame(() => requestAnimationFrame(() => {
      const el = document.getElementById(section)
      if (!el) return
      el.scrollIntoView({ block: 'start' })
      el.style.transition = 'background 0.9s ease'
      el.style.background = `${color.bluePrimary}26`
      setTimeout(() => { el.style.background = 'transparent' }, 900)
    }))
    return () => cancelAnimationFrame(raf)
  }, [section])

  const idx = CHAPTERS_META.findIndex((c) => c.id === chapter)
  const Body = CHAPTER_BODIES[chapter]

  const goto = (id: ChapterId) => {
    setChapter(id)
    requestAnimationFrame(() =>
      document.getElementById('manual-top')?.scrollIntoView({ block: 'start' }))
  }

  return (
    <>
      <div id="manual-top" style={{ scrollMarginTop: size.sp4 }} />

      {/* Chapter picker — a learning path, not a table of contents. */}
      <nav aria-label="Manual chapters"
           style={{ display: 'flex', flexWrap: 'wrap', gap: size.sp2, margin: `${size.sp3} 0 ${size.sp2}` }}>
        {CHAPTERS_META.map((c, i) => {
          const active = c.id === chapter
          return (
            <button key={c.id} onClick={() => goto(c.id)} aria-current={active ? 'page' : undefined}
                    style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                      gap: 1, cursor: 'pointer', textAlign: 'left',
                      background: active ? color.blueSubtle : color.bgCard,
                      border: `1px solid ${active ? color.borderActive : color.border}`,
                      borderRadius: size.radiusMd, padding: `${size.sp2} ${size.sp3}`,
                    }}>
              <span style={{ fontSize: 9.5, fontFamily: font.mono, letterSpacing: '0.08em',
                             textTransform: 'uppercase', color: color.textDim }}>
                {i + 1} · {c.level}
              </span>
              <span style={{ fontSize: 13, fontWeight: active ? 600 : 400,
                             color: active ? color.textPrimary : color.textSecondary }}>
                {c.title}
              </span>
            </button>
          )
        })}
      </nav>
      <p style={{ margin: `0 0 ${size.sp2}`, fontSize: 12, color: color.textDim }}>
        {CHAPTER_BLURBS[chapter]}
      </p>

      <Body />

      {/* Next/previous, so the chapters read as a path. */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: size.sp8,
                    borderTop: `1px solid ${color.border}`, paddingTop: size.sp4 }}>
        {idx > 0 ? (
          <button onClick={() => goto(CHAPTERS_META[idx - 1].id)}
                  style={{ background: 'none', border: 'none', color: color.blueBright,
                           fontSize: 13, cursor: 'pointer', padding: 0 }}>
            ← {CHAPTERS_META[idx - 1].title}
          </button>
        ) : <span />}
        {idx < CHAPTERS_META.length - 1 ? (
          <button onClick={() => goto(CHAPTERS_META[idx + 1].id)}
                  style={{ background: 'none', border: 'none', color: color.blueBright,
                           fontSize: 13, cursor: 'pointer', padding: 0 }}>
            {CHAPTERS_META[idx + 1].title} →
          </button>
        ) : <span />}
      </div>
    </>
  )
}

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
