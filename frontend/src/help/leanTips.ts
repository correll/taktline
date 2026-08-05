/** Lean "tips of the day" — distilled from "The Seven Deadly Wastes"
 *  and complemented with classic lean practice (5S, SMED, poka-yoke, jidoka,
 *  heijunka, PDCA, theory of constraints, …) plus hands-on Taktline workflow
 *  tips. One tip is shown per calendar day, rotating deterministically so every
 *  user in a plant sees the same tip on the same day. */

export interface LeanTip {
  /** Permanent, unique handle. It is the public URL of the tip's share card
   *  (`/i/<id>`), so it must survive both reordering and rewording — which is
   *  why it is written down rather than derived from the position or a hash of
   *  the text. Once a tip has been shared, its id is a promise. */
  id: string
  category: string   // short chip shown above the tip
  text: string
  /** Position in the trio quoted on the public landing page. Marked here so the
   *  page and the daily rotation stay one source of truth — reword a tip and
   *  both follow. */
  featured?: 1 | 2 | 3
}

export const LEAN_TIPS: LeanTip[] = [
  // ── The lean method ─────────────────────────────────────────────────────────
  { id: 'lean-method-five-steps-lean-define', category: 'Lean method',   text: 'The five steps to lean: define value, map the value stream, create flow, establish pull, pursue perfection. Then start over — it’s a loop, not a checklist, because every improvement exposes the next problem that was hidden underneath it.' },
  { id: 'lean-method-start-every-improvement-customer', category: 'Lean method',   text: 'Start every improvement from customer value: what quality, price, and delivery is your customer actually paying for? Every change is measured against that.' },
  { id: 'lean-method-cannot-improve-cannot-see', category: 'Lean method',   text: 'You cannot improve what you cannot see. Mapping your value stream — and getting live data onto it — is always the first step.' },
  { id: 'lean-method-lean-best-learned-genba', category: 'Lean method',   text: 'Lean is best learned at the genba — “the actual place”. Walk your floor with the live map in hand and keep your eyes open for waste.' },
  { id: 'lean-method-improve-small-steps-japanese', category: 'Lean method',   text: 'Improve in small steps — the Japanese call it kata. A tiny change whose effect you can watch beats a big redesign whose effects you can’t untangle.' },
  { id: 'lean-method-becoming-lean-involves-everyone', category: 'Lean method',   text: 'Becoming lean involves everyone — from the line worker to sales. The best person to improve a station’s daily work is the person who runs it.' },
  { id: 'lean-method-t-make-obvious-improvement', category: 'Lean method',   text: 'When you can’t make the obvious improvement, don’t give up — optimize your second choices. The sum of small changes wins in the long run.' },
  { id: 'lean-method-change-speeds-up-station', category: 'Lean method',   text: 'A change that speeds up your station can still slow down the line, because stations are coupled: your extra output is simply the next station’s growing queue. Always check what an improvement does one station up- and downstream.' },
  { id: 'lean-method-toyota-s-true-north', category: 'Lean method',   text: 'Toyota’s “true north”: the closer you get to optimal, the less rules of thumb help — and the harder you must look at your own data.' },
  { id: 'lean-method-looks-like-collection-lean', category: 'Lean method',   text: 'What looks like a collection of lean rules is really a set of trade-offs. Speed vs. energy, inventory vs. resilience — knowing your goal decides them.' },

  // ── TIMWOOD: the seven wastes ───────────────────────────────────────────────
  { id: 'timwood-memorize-seven-wastes-timwood', category: 'TIMWOOD',       text: 'Memorize the seven wastes as TIMWOOD: Transport, Inventory, Motion, Waiting, Over-processing, Overproduction, Defects.' },
  { id: 'transport-transport-easiest-waste-spot', category: 'Transport',     text: 'Transport is the easiest waste to spot and often the cheapest to fix — distance is a tax you pay again on every single lot, forever. Store what a station needs as close to it as possible.' },
  { id: 'transport-frequently-used-items-belong', category: 'Transport',     text: 'Frequently used items belong in the closest stations; rarely used ones can live far away. Sort by frequency of use, not by category.' },
  { id: 'transport-stations-drawn-scale-floor', category: 'Transport',     text: 'Your stations are drawn to scale on the floor plan — so the transport statistic is real meters. Rearrange the floor and watch the meters fall.' },
  { id: 'inventory-wip-costs-twice-capital', category: 'Inventory',     text: 'WIP costs you twice: capital and labor already invested, plus the sale it isn’t yet. Cut work-in-process before adding capacity.', featured: 1 },
  { id: 'inventory-pile-wip-front-station', category: 'Inventory',     text: 'A pile of WIP in front of a station is your bottleneck introducing itself. The heatmap shows it in red.' },
  { id: 'inventory-inventory-hides-problems-buffering', category: 'Inventory',     text: 'Inventory hides problems by buffering them. Lowering WIP feels risky — but it exposes the issues you actually need to fix.' },
  { id: 'inventory-fewer-part-variants-means', category: 'Inventory',     text: 'Fewer part variants means less stock, better storage stations, and easier handling. Simplify the product to simplify the floor.' },
  { id: 'motion-motion-everything-body-reaching', category: 'Motion',        text: 'Motion is everything a body does — reaching, bending, turning. It always costs time and sometimes health. Level surfaces, closer tools, less strain.' },
  { id: 'motion-watch-task-like-d', category: 'Motion',        text: 'Watch a task like you’d watch video footage: where do hands travel? A workbench aligned with the machine can erase a thousand turns a week.' },
  { id: 'waiting-waiting-most-visible-enemy', category: 'Waiting',       text: 'Waiting is the most visible enemy of flow. Record cycle times per station — the numbers tell you where the line is out of balance.' },
  { id: 'waiting-line-only-fast-slowest', category: 'Waiting',       text: 'A line is only as fast as its slowest station. Speeding up any other station produces inventory, not output.' },
  { id: 'over-processing-over-processing-work-customer', category: 'Over-processing', text: 'Over-processing is work the customer never asked for: polishing what no one sees, treating every variant alike because routing is hard.' },
  { id: 'overproduction-overproduction-making-more-sooner', category: 'Overproduction', text: 'Overproduction is making more, or sooner, than is ordered — in the strictest reading, everything not yet sold. A pull cap prevents it mechanically: nothing new may start until something finished leaves.' },
  { id: 'overproduction-maximize-machine-utilization-overproduction', category: 'Overproduction', text: '“Maximize machine utilization” is how overproduction sneaks in: a machine kept busy beyond the pace of customer demand isn’t productive, it’s converting money into inventory. Machines exist to serve demand’s beat, not the other way around.', featured: 3 },
  { id: 'defects-later-defect-found-more', category: 'Defects',       text: 'The later a defect is found, the more added value is scrapped with it. Check quality at the station, not just at the end.' },
  { id: 'defects-wip-amplifies-defects-systematic', category: 'Defects',       text: 'WIP amplifies defects: a systematic error fills the whole buffer before quality control sees the first bad part. Less WIP = earlier detection.' },
  { id: 'timwood-waste-almost-always-looks', category: 'TIMWOOD',       text: 'Waste almost always looks necessary. It only becomes visible when you imagine a better way — that’s why fresh eyes on a genba walk find so much.' },
  { id: 'timwood-sometimes-adding-waste-one', category: 'TIMWOOD',       text: 'Sometimes adding waste in one category removes more in another: slowing a station down (waiting) can reduce defects and overproduction.' },
  { id: 'timwood-eighth-waste-over-qualification', category: 'TIMWOOD',       text: 'An eighth waste: over-qualification. If a task could be done with simpler skills or tools, the surplus is waste too.' },

  // ── Pull & Kanban ───────────────────────────────────────────────────────────
  { id: 'pull-pull-means-hard-cap', category: 'Pull',          text: '“Pull” means a hard cap on WIP: downstream consumption triggers upstream work. Everything else — however busy it looks — is push.' },
  { id: 'pull-lot-cards-kanban-cards', category: 'Pull',          text: 'Your lot cards are Kanban cards. Limit how many circulate and you’ve built a pull system — the cap is the whole trick.' },
  { id: 'pull-create-orders-pulling-end', category: 'Pull',          text: 'Create orders by pulling from the end of the line. Pulling at an intermediate station builds WIP that still has to travel — Taktline warns you for a reason.' },
  { id: 'pull-push-pull-produce-same', category: 'Pull',          text: 'Push and pull produce at the same rate — the slowest station decides both. Pull just gets there with a fraction of the WIP, lead time, and rework.' },
  { id: 'pull-pull-system-speed-limit', category: 'Pull',          text: 'A pull system is a speed limit on the highway: individuals grumble, everyone arrives sooner.' },
  { id: 'pull-right-size-kanban-count', category: 'Pull',          text: 'Right-size your kanban count: one card per station approximates single-piece flow, and every extra card is one more lot of WIP standing in line — by Little’s law, more lead time. Add cards only where variability genuinely needs a buffer.' },
  { id: 'pull-batch-sizes-one-sound', category: 'Pull',          text: 'Batch sizes of one sound extreme, but the arithmetic is plain: in a batch of ten, each part spends nine tenths of its life waiting for its batchmates. Every batch-size reduction cuts lead time, space, and rework — move that way in steps.' },

  // ── Numbers: lead time, takt, OEE ───────────────────────────────────────────
  { id: 'lead-time-little-s-law-lead', category: 'Lead time',     text: 'Little’s law: lead time ≈ WIP ÷ production rate. Halve the WIP in your line and lead time halves — without anyone working faster.', featured: 2 },
  { id: 'lead-time-three-levers-shorten-lead', category: 'Lead time',     text: 'Three levers shorten lead time: remove waste from the process, raise the bottleneck’s rate, and cut WIP with pull. Work them in that order.' },
  { id: 'takt-takt-time-available-time', category: 'Takt',          text: 'Takt time = available time ÷ customer demand — the beat your line must hold to meet demand exactly. Producing to takt is itself a pull system: the beat admits work at the rate the customer consumes it, no faster. A line is balanced when every station’s cycle time sits close to takt.' },
  { id: 'takt-three-different-numbers-constantly', category: 'Takt',          text: 'Three different numbers, constantly confused. Takt time is the beat you need (available time ÷ demand) — a target you set. Cycle time is how long the work actually takes — what Start/Stop measures. Line cycle time is how often a piece really leaves. Cycle time under takt but line cycle time over it means the work is fine and the flow is not.' },
  { id: 'takt-gap-between-cycle-time', category: 'Takt',          text: 'The gap between cycle time and line cycle time is your waste, in seconds. If a station works a piece in 2 minutes but only ships one every 9, the missing 7 are queueing, blocking or transport — speeding up the operator wins nothing.' },
  { id: 'takt-one-pass-fail-test', category: 'Takt',          text: 'The one pass/fail test on the whole board: line cycle time ≤ takt time. If demand needs a unit every 4 minutes and pieces really leave every 3, you are meeting it; if they leave every 5, you are falling a unit behind every 20 minutes, whatever the cycle times say. Check this before anything else — a line can hit every station’s cycle-time target and still miss demand, because cycle time measures the work and takt measures the promise.' },
  { id: 'takt-cycle-time-far-below', category: 'Takt',          text: 'When cycle time is far below line cycle time, the work is not the problem — the flow is. A station that fills a piece in 2 minutes but only releases one every 20 is idle 90% of the time: starved from upstream, blocked downstream, or waiting on transport. That ratio is the cheapest improvement in the plant, because you are buying back time you are already paying for.' },
  { id: 'takt-chase-cycle-line-cycle', category: 'Takt',          text: 'Chase a cycle/line-cycle gap in this order: upstream first (is the station starved?), then downstream (is it blocked by a full queue?), then transport and changeover. The station showing the gap is rarely the station causing it — which is why “work faster” is almost always the wrong instruction.' },
  { id: 'takt-station-s-cycle-time', category: 'Takt',          text: 'When a station’s cycle time exceeds takt, no amount of flow improvement saves you: the work itself is slower than demand. That is a capacity decision — a second operator, a parallel station, a faster process, or fewer orders — not something a better queue can fix. Cycle time above takt is the one problem you cannot organise your way out of.' },
  { id: 'takt-takt-constant-recompute-whenever', category: 'Takt',          text: 'Takt is not a constant. Recompute it whenever demand or the shift pattern changes: the same line running one shift instead of two has half the available time and therefore half the takt. A takt set once and forgotten is a target measured against last quarter’s order book.' },
  { id: 'takt-quote-delivery-dates-line', category: 'Takt',          text: 'Quote delivery dates from line cycle time, not cycle time. Cycle time is the flattering number — it counts only the minutes someone was actually working, and every hour a lot spent queueing is still an hour your customer waited.' },
  { id: 'takt-balance-demand-capacity-station', category: 'Takt',          text: 'Balance to demand, not to capacity. A station running faster than takt — the pace customer demand sets — isn’t being productive; it’s stacking inventory in front of the next station.' },
  { id: 'takt-balance-line-lift-slowest', category: 'Takt',          text: 'To balance a line: lift the slowest station with lean improvements, slow the fastest only if it saves real money, and split or merge stations when gaps stay wide.' },
  { id: 'oee-oee-overall-equipment-effectiveness', category: 'OEE',           text: 'OEE — Overall Equipment Effectiveness, actual output ÷ theoretical maximum — means nothing as a single number, because “theoretical maximum” is defined differently everywhere. It’s the change that talks: a sudden drop says “look here” — downtime, starvation, or quality.' },
  { id: 'oee-very-high-oee-station', category: 'OEE',           text: 'A very high OEE (a station running near its maximum output) is a warning, not a trophy: a station at capacity has no slack, so work queues in front of it — you’re looking at your bottleneck.' },
  { id: 'oee-station-only-run-upstream', category: 'OEE',           text: 'A station can only run when its upstream neighbor feeds it — so a low OEE downstream usually indicts the station before it, not the idle one. Never judge equipment effectiveness in isolation; read the whole line.' },
  { id: 'oee-don-t-set-oee', category: 'OEE',           text: 'Don’t set OEE as a target: people will hit it by keeping machines busy making parts nobody ordered — utilization up, overproduction up. Use OEE to locate problems, and optimize toward customer value instead.' },

  // ── Digital lean & automation ───────────────────────────────────────────────
  { id: 'digital-lean-digitize-whole-process-before', category: 'Digital lean',  text: 'Digitize the whole process before digitizing one machine: data without an order attached is hard to turn into customer value.' },
  { id: 'digital-lean-lean-first-automate-layout', category: 'Digital lean',  text: 'Lean first, then automate. Layout and flow improvements are free — and they define what a robot must actually do before you buy one.' },
  { id: 'digital-lean-machine-saves-labor-disrupts', category: 'Digital lean',  text: 'A machine that saves labor but disrupts flow is a net loss. Judge equipment by its effect on the value stream, not its spec sheet.' },
  { id: 'digital-lean-real-time-data-turns', category: 'Digital lean',  text: 'Real-time data turns weeks of clipboard studies into hours: watch cycle time, OEE, and the heatmap respond the same day you change something.' },

  // ── Classic lean practice (beyond the book) ────────────────────────────────
  { id: '5s-5s-sort-set-order', category: '5S',            text: '5S: Sort, Set in order, Shine, Standardize, Sustain. A workplace where everything has a visible home makes waste — and missing tools — obvious at a glance.' },
  { id: '5s-outline-tool-positions-shadow', category: '5S',            text: 'Outline tool positions with shadow boards or tape. If a tool is missing you see it in one second, not after ten minutes of searching.' },
  { id: 'smed-smed-single-minute-exchange', category: 'SMED',          text: 'SMED — single-minute exchange of die: split every changeover into “external” work you can do while the machine runs and “internal” work you can’t. Then move steps from internal to external.' },
  { id: 'smed-faster-changeovers-don-t', category: 'SMED',          text: 'Faster changeovers don’t just save time — they make small batches economical. Cut the changeover in half and you can halve the batch, the WIP, and the lead time.' },
  { id: 'poka-yoke-poka-yoke-mistake-proofing', category: 'Poka-yoke',     text: 'Poka-yoke — mistake-proofing: design the step so the error is impossible, not just discouraged. A connector that only fits one way beats a warning label every time.' },
  { id: 'poka-yoke-checklists-cheapest-poka-yoke', category: 'Poka-yoke',     text: 'Checklists are the cheapest poka-yoke. Put the check into the lot card’s fields so the operator confirms it where the work happens.' },
  { id: 'jidoka-jidoka-stop-line-something', category: 'Jidoka',        text: 'Jidoka: stop the line when something is wrong, immediately. One stopped station is cheap; a buffer full of defective parts is not.' },
  { id: 'jidoka-empower-every-operator-halt', category: 'Jidoka',        text: 'Empower every operator to halt work and flag a problem — the andon principle. Root-cause analysis (your five whys) is fastest while the evidence is still warm; wait a shift and the trail is cold, the WIP pile contaminated.' },
  { id: 'heijunka-heijunka-level-mix-alternate', category: 'Heijunka',      text: 'Heijunka — level the mix: alternate small batches of A, B, C instead of a week of each. Customers order a mix, and an even mix removes the demand spikes (mura) that would otherwise force big buffers everywhere — leveling is what makes a tight pull cap livable.' },
  { id: 'standard-work-standard-work-baseline-improvement', category: 'Standard work', text: 'Standard work is the baseline of improvement: without a documented “current best way”, you can’t tell whether a change helped or the day was just lucky.' },
  { id: 'standard-work-write-standard-people-who', category: 'Standard work', text: 'Write the standard with the people who do the work — then improve the standard, not the person.' },
  { id: 'muda-mura-muri-muda-waste-mura-unevenness', category: 'Muda·Mura·Muri', text: 'Muda is waste, mura is unevenness, muri is overburden. Uneven flow creates overburden, and overburden creates waste — level first, then optimize.' },
  { id: 'pdca-pdca-plan-check-act', category: 'PDCA',          text: 'PDCA — Plan, Do, Check, Act — is the engine inside kata, genba walks, and the five lean steps: they’re all the same improvement loop at different scales. Every change is an experiment, so decide before you act which number should move; most efforts die at “Check” because nobody ever looks.' },
  { id: 'five-whys-ask-five-times-get', category: 'Five whys',     text: 'Ask “why” five times to get behind the symptom: machine stopped → fuse blew → bearing seized → no lubrication → no maintenance plan. Fixing the fuse cures today; fixing the plan cures the whole class of failures. This is the root-cause drill inside every PDCA “Check”.' },
  { id: 'constraints-theory-constraints-pull-idea', category: 'Constraints',   text: 'The “theory of constraints” is the pull idea in different words: one station — the bottleneck — sets your whole line’s output, so release new work only at the pace that station consumes it. TOC does it with a schedule (“drum-buffer-rope”), kanban does it with cards; both are WIP caps.' },
  { id: 'constraints-protect-bottleneck-hour-lost', category: 'Constraints',   text: 'Protect the bottleneck: an hour lost there is an hour lost for the whole plant, because no other station can make up for it. Give it a small deliberate buffer so it never starves — and remember that an hour “saved” anywhere else doesn’t add output, it just piles WIP in front of the bottleneck.' },
  { id: 'visual-mgmt-visitor-should-understand-state', category: 'Visual mgmt',   text: 'A visitor should understand the state of your floor in three minutes without asking anyone. If they can’t, add visual management — boards, colors, markings.' },
  { id: 'visual-mgmt-metrics-belong-where-work', category: 'Visual mgmt',   text: 'Metrics belong where the work happens, not in a monthly PDF. A number nobody sees daily changes nobody’s behavior.' },
  { id: 'quality-quality-source-operator-checks', category: 'Quality',       text: 'Quality at the source: the operator checks their own output before passing it on. Ten seconds of self-check saves ten minutes of downstream rework.' },
  { id: 'quality-goodhart-s-law-measure', category: 'Quality',       text: 'Goodhart’s law: when a measure becomes a target, it stops measuring — people optimize the number, not the thing it stood for. Chase OEE and you get overproduction; chase ship-dates alone and you get defects. Reward improvement of the system, not the number.' },
  { id: 'layout-trace-one-product-s', category: 'Layout',        text: 'Trace one product’s actual path on a floor plan — the “spaghetti diagram”. The tangles you see are transport and motion waste you can delete with layout alone.' },
  { id: 'layout-store-parts-point-use', category: 'Layout',        text: 'Store parts at the point of use, in the orientation they’re used, at the height they’re used. Every re-grip and re-turn is motion waste.' },
  { id: 'layout-u-shaped-cells-put', category: 'Layout',        text: 'U-shaped cells put the first and last step side by side: one operator can run the whole loop, and imbalances become visible immediately.' },
  { id: 'people-lean-s-second-pillar', category: 'People',        text: 'Lean’s second pillar is respect for people. Nobody knows a station’s waste better than the person who runs it eight hours a day — ask them first.' },
  { id: 'people-cross-train-deliberately-keep', category: 'People',        text: 'Cross-train deliberately and keep a visible skill matrix. Multi-skilled teams absorb absences and demand spikes without breaking flow.' },
  { id: 'people-five-minute-daily-huddle', category: 'People',        text: 'A five-minute daily huddle at the board beats an hour-long weekly meeting in a conference room. Decide at the genba, with the data in view.' },
  { id: 'maintenance-total-productive-maintenance-small', category: 'Maintenance',   text: 'Total productive maintenance: small daily care by the operator — clean, inspect, lubricate — prevents big unplanned stops. Planned maintenance pauses one station on your schedule; a breakdown pauses the whole line on the machine’s schedule.' },
  { id: 'flow-fifo-first-first-out', category: 'Flow',          text: 'FIFO — first in, first out: work the oldest lot first. When lots overtake each other, some wait unpredictably long (your quoted lead time becomes a lie) and the time window for tracing a defect’s cause gets scrambled. Deviate only by a deliberate priority rule.' },
  { id: 'sequencing-shared-machine-runout', category: 'Sequencing',    text: 'At a machine several lines share, FIFO is fair to lots — not to lines. Run the line that starves first: each line’s clock is its downstream buffer divided by the rate it is actually consumed. Taktline’s lot picker at a shared station sorts by exactly this, and says why.' },
  { id: 'pareto-80-20-rule-holds', category: 'Pareto',        text: 'The 80/20 rule holds on the shop floor: a few defect types cause most rework, a few products cause most changeovers. Count first, then fix the tallest bar.' },

  // ── Taktline in practice ───────────────────────────────────────────────────
  { id: 'taktline-mount-tablet-operator-view', category: 'Taktline',      text: 'Mount a tablet with the Operator view at each station. Timing happens as a side effect of working — and your takt and OEE statistics build themselves.' },
  { id: 'taktline-print-lot-labels-scan', category: 'Taktline',      text: 'Print lot labels and scan to advance: one barcode scan moves the lot and timestamps the transport. No screen, no typing, no forgotten bookings.' },
  { id: 'taktline-set-real-work-hours', category: 'Taktline',      text: 'Set your real work hours in Settings → Global. OEE measured against a 24/7 clock punishes you for sleeping — measure against the hours you actually run.' },
  { id: 'taktline-lot-code-traceability-thread', category: 'Taktline',      text: 'A lot code is a traceability thread: released from an order it carries the order’s reference, and every split piece keeps it. Quote it in every quality conversation.' },
  { id: 'taktline-merge-station-check-feeding', category: 'Taktline',      text: 'At a merge station, check the feeding-stations panel before walking: it shows what’s finished upstream, and one tap jumps you there to fetch it.' },
  { id: 'taktline-watch-lots-board-week', category: 'Taktline',      text: 'Watch the Lots board for a week before changing anything. The column that’s always full is your real bottleneck — it is rarely the one everyone suspects.' },
  { id: 'taktline-let-orders-drive-floor', category: 'Taktline',      text: 'Let orders drive the floor: connect your shop or ERP and each sale releases exactly the lots it needs — pull all the way from the customer.' },
]

const TIP_EPOCH = Date.UTC(2026, 0, 1)   // rotation anchor — same tip for everyone on a given day

/** The day-to-day order, built once so that CATEGORIES are spread as far apart
 *  as the list allows.
 *
 *  The obvious scheme — stride the flat array by a step coprime to its length —
 *  guarantees every tip appears exactly once per cycle, which is the property
 *  one naturally checks. But nobody experiences "tip 45" and then "tip 48";
 *  they experience *another takt tip*. With 94 tips and a stride of 37, five
 *  days moved the index by only −3, so whole neighbourhoods came back inside a
 *  week: Takt on the 22nd and again on the 27th, Lean method on the 26th and
 *  again on the 31st. Two quality tips a day apart — Defects then Poka-yoke —
 *  read as the same tip repeated, which is how this was noticed.
 *
 *  So each position takes the tip whose category has gone longest unused, ties
 *  broken by the original order. Deterministic, so everyone still sees the same
 *  tip on the same day, and every tip still appears exactly once per cycle —
 *  but a category with two entries now sits ~47 days apart instead of possibly
 *  three.
 */
function spreadByCategory(tips: LeanTip[]): number[] {
  // Each tip is placed at its category's *fractional* position: the k-th of a
  // category with m entries belongs (k + ½)/m of the way through the cycle.
  // Sorting by that interleaves every category evenly, so a category with two
  // tips lands ~47 days apart and the eleven takt tips ~8.5 days apart.
  //
  // Greedily taking "whichever category has waited longest" was the obvious
  // alternative and it fails at the tail: once the small categories are spent,
  // only the big one is left and its last entries come out back to back.
  const perCategory = new Map<string, number>()
  const total = new Map<string, number>()
  for (const t of tips) total.set(t.category, (total.get(t.category) ?? 0) + 1)

  return tips
    .map((t, i) => {
      const k = perCategory.get(t.category) ?? 0
      perCategory.set(t.category, k + 1)
      return { i, at: (k + 0.5) / (total.get(t.category) ?? 1), cat: t.category }
    })
    // Ties (two categories of the same size) resolve by name, then by original
    // order — anything deterministic will do, as long as it is stable.
    .sort((a, b) => a.at - b.at || a.cat.localeCompare(b.cat) || a.i - b.i)
    .map((e) => e.i)
}

const ROTATION = spreadByCategory(LEAN_TIPS)

/** The tips quoted on the landing page, in the order they read there: what WIP
 *  costs, why it costs that, and the belief that keeps producing it. Each one is
 *  meant to make a stranger recognise a problem they already have. */
export function featuredTips(): LeanTip[] {
  return LEAN_TIPS.filter((t) => t.featured)
                  .sort((a, b) => (a.featured ?? 0) - (b.featured ?? 0))
}

/** Deterministic tip for a given date (defaults to today). */
export function tipOfTheDay(date: Date = new Date()): LeanTip {
  const day = Math.floor((date.getTime() - TIP_EPOCH) / 86_400_000)
  const n = ROTATION.length
  return LEAN_TIPS[ROTATION[((day % n) + n) % n]]
}
