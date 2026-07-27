/** Lean "tips of the day" — distilled from "The Seven Deadly Wastes" (book/)
 *  and complemented with classic lean practice (5S, SMED, poka-yoke, jidoka,
 *  heijunka, PDCA, theory of constraints, …) plus hands-on Taktline workflow
 *  tips. One tip is shown per calendar day, rotating deterministically so every
 *  user in a plant sees the same tip on the same day. */

export interface LeanTip {
  category: string   // short chip shown above the tip
  text: string
}

export const LEAN_TIPS: LeanTip[] = [
  // ── The lean method ─────────────────────────────────────────────────────────
  { category: 'Lean method',   text: 'The five steps to lean: define value, map the value stream, create flow, establish pull, pursue perfection. Then start over — it’s a loop, not a checklist, because every improvement exposes the next problem that was hidden underneath it.' },
  { category: 'Lean method',   text: 'Start every improvement from customer value: what quality, price, and delivery is your customer actually paying for? Every change is measured against that.' },
  { category: 'Lean method',   text: 'You cannot improve what you cannot see. Mapping your value stream — and getting live data onto it — is always the first step.' },
  { category: 'Lean method',   text: 'Lean is best learned at the genba — "the actual place". Walk your floor with the live map in hand and keep your eyes open for waste.' },
  { category: 'Lean method',   text: 'Improve in small steps — the Japanese call it kata. A tiny change whose effect you can watch beats a big redesign whose effects you can’t untangle.' },
  { category: 'Lean method',   text: 'Becoming lean involves everyone — from the line worker to sales. The best person to improve a station’s daily work is the person who runs it.' },
  { category: 'Lean method',   text: 'When you can’t make the obvious improvement, don’t give up — optimize your second choices. The sum of small changes wins in the long run.' },
  { category: 'Lean method',   text: 'A change that speeds up your station can still slow down the line, because stations are coupled: your extra output is simply the next station’s growing queue. Always check what an improvement does one station up- and downstream.' },
  { category: 'Lean method',   text: 'Toyota’s "true north": the closer you get to optimal, the less rules of thumb help — and the harder you must look at your own data.' },
  { category: 'Lean method',   text: 'What looks like a collection of lean rules is really a set of trade-offs. Speed vs. energy, inventory vs. resilience — knowing your goal decides them.' },

  // ── TIMWOOD: the seven wastes ───────────────────────────────────────────────
  { category: 'TIMWOOD',       text: 'Memorize the seven wastes as TIMWOOD: Transport, Inventory, Motion, Waiting, Over-processing, Overproduction, Defects.' },
  { category: 'Transport',     text: 'Transport is the easiest waste to spot and often the cheapest to fix — distance is a tax you pay again on every single lot, forever. Store what a station needs as close to it as possible.' },
  { category: 'Transport',     text: 'Frequently used items belong in the closest locations; rarely used ones can live far away. Sort by frequency of use, not by category.' },
  { category: 'Transport',     text: 'Your stations are drawn to scale on the map — so the transport statistic is real meters. Rearrange the floor and watch the meters fall.' },
  { category: 'Inventory',     text: 'WIP costs you twice: capital and labor already invested, plus the sale it isn’t yet. Cut work-in-process before adding capacity.' },
  { category: 'Inventory',     text: 'A pile of WIP in front of a station is your bottleneck introducing itself. The heatmap shows it in red.' },
  { category: 'Inventory',     text: 'Inventory hides problems by buffering them. Lowering WIP feels risky — but it exposes the issues you actually need to fix.' },
  { category: 'Inventory',     text: 'Fewer part variants means less stock, better storage locations, and easier handling. Simplify the product to simplify the floor.' },
  { category: 'Motion',        text: 'Motion is everything a body does — reaching, bending, turning. It always costs time and sometimes health. Level surfaces, closer tools, less strain.' },
  { category: 'Motion',        text: 'Watch a task like you’d watch video footage: where do hands travel? A workbench aligned with the machine can erase a thousand turns a week.' },
  { category: 'Waiting',       text: 'Waiting is the most visible enemy of flow. Record cycle times per station — the numbers tell you where the line is out of balance.' },
  { category: 'Waiting',       text: 'A line is only as fast as its slowest station. Speeding up any other station produces inventory, not output.' },
  { category: 'Over-processing', text: 'Over-processing is work the customer never asked for: polishing what no one sees, treating every variant alike because routing is hard.' },
  { category: 'Overproduction', text: 'Overproduction is making more, or sooner, than is ordered — in the strictest reading, everything not yet sold. A pull cap prevents it mechanically: nothing new may start until something finished leaves.' },
  { category: 'Overproduction', text: '"Maximize machine utilization" is how overproduction sneaks in: a machine kept busy beyond the pace of customer demand isn’t productive, it’s converting money into inventory. Machines exist to serve demand’s beat, not the other way around.' },
  { category: 'Defects',       text: 'The later a defect is found, the more added value is scrapped with it. Check quality at the station, not just at the end.' },
  { category: 'Defects',       text: 'WIP amplifies defects: a systematic error fills the whole buffer before quality control sees the first bad part. Less WIP = earlier detection.' },
  { category: 'TIMWOOD',       text: 'Waste almost always looks necessary. It only becomes visible when you imagine a better way — that’s why fresh eyes on a genba walk find so much.' },
  { category: 'TIMWOOD',       text: 'Sometimes adding waste in one category removes more in another: slowing a station down (waiting) can reduce defects and overproduction.' },
  { category: 'TIMWOOD',       text: 'An eighth waste: over-qualification. If a task could be done with simpler skills or tools, the surplus is waste too.' },

  // ── Pull & Kanban ───────────────────────────────────────────────────────────
  { category: 'Pull',          text: '"Pull" means a hard cap on WIP: downstream consumption triggers upstream work. Everything else — however busy it looks — is push.' },
  { category: 'Pull',          text: 'Your lot cards are Kanban cards. Limit how many circulate and you’ve built a pull system — the cap is the whole trick.' },
  { category: 'Pull',          text: 'Create orders by pulling from the end of the line. Pulling at an intermediate station builds WIP that still has to travel — Taktline warns you for a reason.' },
  { category: 'Pull',          text: 'Push and pull produce at the same rate — the slowest station decides both. Pull just gets there with a fraction of the WIP, lead time, and rework.' },
  { category: 'Pull',          text: 'A pull system is a speed limit on the highway: individuals grumble, everyone arrives sooner.' },
  { category: 'Pull',          text: 'Right-size your kanban count: one card per station approximates single-piece flow, and every extra card is one more lot of WIP standing in line — by Little’s law, more lead time. Add cards only where variability genuinely needs a buffer.' },
  { category: 'Pull',          text: 'Batch sizes of one sound extreme, but the arithmetic is plain: in a batch of ten, each part spends nine tenths of its life waiting for its batchmates. Every batch-size reduction cuts lead time, space, and rework — move that way in steps.' },

  // ── Numbers: lead time, takt, OEE ───────────────────────────────────────────
  { category: 'Lead time',     text: 'Little’s law: lead time ≈ WIP ÷ production rate. Halve the WIP in your line and lead time halves — without anyone working faster.' },
  { category: 'Lead time',     text: 'Three levers shorten lead time: remove waste from the process, raise the bottleneck’s rate, and cut WIP with pull. Work them in that order.' },
  { category: 'Takt',          text: 'Takt time = available time ÷ customer demand — the beat your line must hold to meet demand exactly. Producing to takt is itself a pull system: the beat admits work at the rate the customer consumes it, no faster. A line is balanced when every station’s cycle time sits close to takt.' },
  { category: 'Takt',          text: 'Balance to demand, not to capacity. A station running faster than takt — the pace customer demand sets — isn’t being productive; it’s stacking inventory in front of the next station.' },
  { category: 'Takt',          text: 'To balance a line: lift the slowest station with lean improvements, slow the fastest only if it saves real money, and split or merge stations when gaps stay wide.' },
  { category: 'OEE',           text: 'OEE — Overall Equipment Effectiveness, actual output ÷ theoretical maximum — means nothing as a single number, because "theoretical maximum" is defined differently everywhere. It’s the change that talks: a sudden drop says "look here" — downtime, starvation, or quality.' },
  { category: 'OEE',           text: 'A very high OEE (a station running near its maximum output) is a warning, not a trophy: a station at capacity has no slack, so work queues in front of it — you’re looking at your bottleneck.' },
  { category: 'OEE',           text: 'A station can only run when its upstream neighbor feeds it — so a low OEE downstream usually indicts the station before it, not the idle one. Never judge equipment effectiveness in isolation; read the whole line.' },
  { category: 'OEE',           text: 'Don’t set OEE as a target: people will hit it by keeping machines busy making parts nobody ordered — utilization up, overproduction up. Use OEE to locate problems, and optimize toward customer value instead.' },

  // ── Digital lean & automation ───────────────────────────────────────────────
  { category: 'Digital lean',  text: 'Digitize the whole process before digitizing one machine: data without an order attached is hard to turn into customer value.' },
  { category: 'Digital lean',  text: 'Lean first, then automate. Layout and flow improvements are free — and they define what a robot must actually do before you buy one.' },
  { category: 'Digital lean',  text: 'A machine that saves labor but disrupts flow is a net loss. Judge equipment by its effect on the value stream, not its spec sheet.' },
  { category: 'Digital lean',  text: 'Real-time data turns weeks of clipboard studies into hours: watch takt, OEE, and the heatmap respond the same day you change something.' },

  // ── Classic lean practice (beyond the book) ────────────────────────────────
  { category: '5S',            text: '5S: Sort, Set in order, Shine, Standardize, Sustain. A workplace where everything has a visible home makes waste — and missing tools — obvious at a glance.' },
  { category: '5S',            text: 'Outline tool positions with shadow boards or tape. If a tool is missing you see it in one second, not after ten minutes of searching.' },
  { category: 'SMED',          text: 'SMED — single-minute exchange of die: split every changeover into "external" work you can do while the machine runs and "internal" work you can’t. Then move steps from internal to external.' },
  { category: 'SMED',          text: 'Faster changeovers don’t just save time — they make small batches economical. Cut the changeover in half and you can halve the batch, the WIP, and the lead time.' },
  { category: 'Poka-yoke',     text: 'Poka-yoke — mistake-proofing: design the step so the error is impossible, not just discouraged. A connector that only fits one way beats a warning label every time.' },
  { category: 'Poka-yoke',     text: 'Checklists are the cheapest poka-yoke. Put the check into the lot card’s fields so the operator confirms it where the work happens.' },
  { category: 'Jidoka',        text: 'Jidoka: stop the line when something is wrong, immediately. One stopped station is cheap; a buffer full of defective parts is not.' },
  { category: 'Jidoka',        text: 'Empower every operator to halt work and flag a problem — the andon principle. Root-cause analysis (your five whys) is fastest while the evidence is still warm; wait a shift and the trail is cold, the WIP pile contaminated.' },
  { category: 'Heijunka',      text: 'Heijunka — level the mix: alternate small batches of A, B, C instead of a week of each. Customers order a mix, and an even mix removes the demand spikes (mura) that would otherwise force big buffers everywhere — leveling is what makes a tight pull cap livable.' },
  { category: 'Standard work', text: 'Standard work is the baseline of improvement: without a documented "current best way", you can’t tell whether a change helped or the day was just lucky.' },
  { category: 'Standard work', text: 'Write the standard with the people who do the work — then improve the standard, not the person.' },
  { category: 'Muda·Mura·Muri', text: 'Muda is waste, mura is unevenness, muri is overburden. Uneven flow creates overburden, and overburden creates waste — level first, then optimize.' },
  { category: 'PDCA',          text: 'PDCA — Plan, Do, Check, Act — is the engine inside kata, genba walks, and the five lean steps: they’re all the same improvement loop at different scales. Every change is an experiment, so decide before you act which number should move; most efforts die at "Check" because nobody ever looks.' },
  { category: 'Five whys',     text: 'Ask "why" five times to get behind the symptom: machine stopped → fuse blew → bearing seized → no lubrication → no maintenance plan. Fixing the fuse cures today; fixing the plan cures the whole class of failures. This is the root-cause drill inside every PDCA "Check".' },
  { category: 'Constraints',   text: 'The "theory of constraints" is the pull idea in different words: one station — the bottleneck — sets your whole line’s output, so release new work only at the pace that station consumes it. TOC does it with a schedule ("drum-buffer-rope"), kanban does it with cards; both are WIP caps.' },
  { category: 'Constraints',   text: 'Protect the bottleneck: an hour lost there is an hour lost for the whole plant, because no other station can make up for it. Give it a small deliberate buffer so it never starves — and remember that an hour "saved" anywhere else doesn’t add output, it just piles WIP in front of the bottleneck.' },
  { category: 'Visual mgmt',   text: 'A visitor should understand the state of your floor in three minutes without asking anyone. If they can’t, add visual management — boards, colors, markings.' },
  { category: 'Visual mgmt',   text: 'Metrics belong where the work happens, not in a monthly PDF. A number nobody sees daily changes nobody’s behavior.' },
  { category: 'Quality',       text: 'Quality at the source: the operator checks their own output before passing it on. Ten seconds of self-check saves ten minutes of downstream rework.' },
  { category: 'Quality',       text: 'Goodhart’s law: when a measure becomes a target, it stops measuring — people optimize the number, not the thing it stood for. Chase OEE and you get overproduction; chase ship-dates alone and you get defects. Reward improvement of the system, not the number.' },
  { category: 'Layout',        text: 'Trace one product’s actual path on a floor plan — the "spaghetti diagram". The tangles you see are transport and motion waste you can delete with layout alone.' },
  { category: 'Layout',        text: 'Store parts at the point of use, in the orientation they’re used, at the height they’re used. Every re-grip and re-turn is motion waste.' },
  { category: 'Layout',        text: 'U-shaped cells put the first and last step side by side: one operator can run the whole loop, and imbalances become visible immediately.' },
  { category: 'People',        text: 'Lean’s second pillar is respect for people. Nobody knows a station’s waste better than the person who runs it eight hours a day — ask them first.' },
  { category: 'People',        text: 'Cross-train deliberately and keep a visible skill matrix. Multi-skilled teams absorb absences and demand spikes without breaking flow.' },
  { category: 'People',        text: 'A five-minute daily huddle at the board beats an hour-long weekly meeting in a conference room. Decide at the genba, with the data in view.' },
  { category: 'Maintenance',   text: 'Total productive maintenance: small daily care by the operator — clean, inspect, lubricate — prevents big unplanned stops. Planned maintenance pauses one station on your schedule; a breakdown pauses the whole line on the machine’s schedule.' },
  { category: 'Flow',          text: 'FIFO — first in, first out: work the oldest lot first. When lots overtake each other, some wait unpredictably long (your quoted lead time becomes a lie) and the time window for tracing a defect’s cause gets scrambled. Deviate only by a deliberate priority rule.' },
  { category: 'Pareto',        text: 'The 80/20 rule holds on the shop floor: a few defect types cause most rework, a few products cause most changeovers. Count first, then fix the tallest bar.' },

  // ── Taktline in practice ───────────────────────────────────────────────────
  { category: 'Taktline',      text: 'Mount a tablet with the Operator view at each station. Timing happens as a side effect of working — and your takt and OEE statistics build themselves.' },
  { category: 'Taktline',      text: 'Print lot labels and scan to advance: one barcode scan moves the lot and timestamps the transport. No screen, no typing, no forgotten bookings.' },
  { category: 'Taktline',      text: 'Set your real work hours in Settings → Global. OEE measured against a 24/7 clock punishes you for sleeping — measure against the hours you actually run.' },
  { category: 'Taktline',      text: 'A lot code is a traceability thread: released from an order it carries the order’s reference, and every split piece keeps it. Quote it in every quality conversation.' },
  { category: 'Taktline',      text: 'At a merge station, check the feeding-locations panel before walking: it shows what’s finished upstream, and one tap jumps you there to fetch it.' },
  { category: 'Taktline',      text: 'Watch the Lots board for a week before changing anything. The column that’s always full is your real bottleneck — it is rarely the one everyone suspects.' },
  { category: 'Taktline',      text: 'Let orders drive the floor: connect your shop or ERP and each sale releases exactly the lots it needs — pull all the way from the customer.' },
]

const TIP_EPOCH = Date.UTC(2026, 0, 1)   // rotation anchor — same tip for everyone on a given day

// Stride through the list with a step coprime to its length: every tip still
// appears exactly once per cycle, but consecutive days hop between categories
// instead of walking through one topic for a week.
const STRIDE = 37

/** Deterministic tip for a given date (defaults to today). */
export function tipOfTheDay(date: Date = new Date()): LeanTip {
  const day = Math.floor((date.getTime() - TIP_EPOCH) / 86_400_000)
  const n = LEAN_TIPS.length
  const idx = (((day * STRIDE) % n) + n) % n
  return LEAN_TIPS[idx]
}
