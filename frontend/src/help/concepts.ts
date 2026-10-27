/**
 * Every idea in the manual worth putting on a card: the flow-science results
 * and the improvement toolkit.
 *
 * This is NOT a second copy of those chapters. The manual explains; a card has
 * to *land* on a stranger's phone in one glance, so each entry here is the one
 * claim the idea makes and the number or image that makes it uncomfortable.
 * `anchor` points at the section that does the explaining, so a card is always
 * an invitation to the manual rather than a replacement for it.
 *
 * `ShareConceptButton` keys off the anchor, so adding an entry here is what
 * puts a share button on that heading — there is no second list to keep in
 * step, and no way to leave a button pointing at a section that no longer
 * exists.
 *
 * `id` is the public URL of the share card (`/i/<id>`) and is permanent.
 */

export type ConceptAnimation =
  | 'queue'        // a station filling as utilisation rises
  | 'wip'          // lots on a line, halved, lead time halving with them
  | 'balance'      // work-content bars against the slowest
  | 'flow'         // a lead-time bar with a sliver of value-added
  | 'control'      // a run chart with limits, common vs special cause
  | 'matched'      // three feeds, an assembly waiting for the last
  | 'monument'     // small cells vs one big machine everything routes to
  | 'constraint'   // a chain, one weak link

export interface Concept {
  id: string
  /** Which chapter it belongs to — decides the eyebrow on the share page. */
  chapter: 'science' | 'toolkit'
  /** Manual section id (see `MANUAL_ANCHORS`) — where the full argument lives. */
  anchor: string
  title: string
  /** The claim, in one sentence. This is the card's headline and the OG title;
   *  it has to make sense with no other context at all. */
  claim: string
  /** Plain-text formula for the card. Rendered typeset in the app. */
  formula?: string
  /** Two or three sentences: why it is true and what to do about it. */
  body: string
  /** Optional. The eight flow-science results are arguments about two
   *  situations being different, which is exactly what an animation is for.
   *  Most toolkit ideas are practices rather than diagrams, and inventing a
   *  picture for one would be decoration pretending to be explanation. */
  animation?: ConceptAnimation
}

export const CONCEPTS: Concept[] = [
  {
    id: 'littles-law',
    chapter: 'science',
    anchor: 'littles-law',
    title: "Little's law",
    claim: 'Halve the work on your floor and lead time halves — with nobody working faster.',
    formula: 'lead time = products in process ÷ throughput',
    body:
      'It holds for any stable system, whatever the layout, scheduling or luck. Sixty products ' +
      'on the floor and twenty leaving a day means three days inside — full stop. It also works ' +
      'backwards as a lie detector: check a promised lead time against WIP and throughput in one ' +
      'division.',
    animation: 'wip',
  },
  {
    id: 'kingman',
    chapter: 'science',
    anchor: 'kingman',
    title: "Kingman's formula",
    claim: 'At 90% utilisation a product waits nine times its own work time. At 95%, nineteen.',
    formula: 'Wq ≈ ρ/(1−ρ) × (ca² + cs²)/2 × te',
    body:
      'The utilisation term is hyperbolic, so queue time runs away smoothly with no warning knee ' +
      '— which is why busy factories are slow ones. The variability term multiplies the same ' +
      'queue at the same load, so irregular arrivals inflate the wait even on a half-loaded ' +
      'station. Two independent levers, and "keep everyone busy" attacks neither.',
    animation: 'queue',
  },
  {
    id: 'balance-efficiency',
    chapter: 'science',
    anchor: 'balance',
    title: 'Balance efficiency',
    claim: 'A 40-minute station beside a 25-minute one buys you 15 minutes of waiting per product — every product, forever.',
    formula: 'E = Σ work content ÷ (n × slowest station)',
    body:
      'Every station is paced by the slowest, so the gap between a station and the slowest one is ' +
      'structural idle time: designed in, paid every cycle, however well anyone works. Move work ' +
      'from the slow station to the fast one, or merge two short ones, and you recover it without ' +
      'anyone hurrying.',
    animation: 'balance',
  },
  {
    id: 'flow-efficiency',
    chapter: 'science',
    anchor: 'flow-efficiency',
    title: 'Flow efficiency',
    claim: 'If a product takes 3 hours of work and 3 weeks to arrive, doubling the speed of every machine improves delivery by 1%.',
    formula: 'flow efficiency = value-added time ÷ lead time',
    body:
      'Real processes land between 1% and 5%. The leverage is entirely in the waiting, which is ' +
      'why cutting WIP beats buying speed almost everywhere — and why this and Kingman are the ' +
      'same argument from two directions.',
    animation: 'flow',
  },
  {
    id: 'common-and-special-cause',
    chapter: 'science',
    anchor: 'variability',
    title: 'Common cause and special cause',
    claim: 'Adjusting a process for every wobble makes it worse. Most "corrective action" is tampering.',
    body:
      'Shewhart\'s split: common-cause variation is inherent to the system and can only be reduced ' +
      'by changing the system; special-cause variation has a findable external origin. Inside the ' +
      'limits, do not react. A station bouncing between 58% and 66% utilisation has a system to improve; ' +
      'one that drops to 30% on Tuesdays has an event to find.',
    animation: 'control',
  },
  {
    id: 'matched-sets',
    chapter: 'science',
    anchor: 'matched-sets',
    title: 'Matched sets',
    claim: '90% of parts finished can still mean zero assemblies possible.',
    body:
      'An assembly needs all of its precursors, so a kit completes at its slowest member, not its ' +
      'average. Part-level completion percentages mislead badly in assembly shops, and releasing ' +
      'partial kits just moves inventory nearer the point where it still cannot be used. Buffer in ' +
      'complete kits, never in bins of whichever part is easiest to make.',
    animation: 'matched',
  },
  {
    id: 'monuments',
    chapter: 'science',
    anchor: 'monument',
    title: 'Monuments',
    claim: 'The spreadsheet that justifies the big machine almost never prices the queue it creates.',
    body:
      'A monument is a large, fixed, high-capacity machine the flow has to route around: the ' +
      'furnace, the plating line, the big paint booth. It forces batching, breaks one-piece flow, ' +
      'and creates contention between product families that would otherwise never meet — and it ' +
      'becomes a permanent constraint, because you cannot buy half a second one.',
    animation: 'monument',
  },
  {
    id: 'theory-of-constraints',
    chapter: 'science',
    anchor: 'constraints',
    title: 'Theory of constraints',
    claim: 'An hour lost at the bottleneck is an hour lost for the whole plant. An hour saved anywhere else is a mirage.',
    body:
      'Every line has exactly one slowest point at a time, and the system\'s throughput is that ' +
      'point\'s throughput. Identify it, exploit it so it never waits, subordinate everything else ' +
      'to its pace, elevate it only once exploitation is exhausted — then repeat, because fixing ' +
      'one constraint reveals the next.',
    animation: 'constraint',
  },
  // ── The improvement toolkit ────────────────────────────────────────────────
  //
  // Practices rather than results, so most carry no animation. They earn a
  // share card for the same reason the flow-science ones do: each is a single
  // claim a foreman would recognise, and none of it is about us.
  {
    id: 'five-s', chapter: 'toolkit', anchor: 'five-s', title: '5S',
    claim: 'If a missing tool is not obvious in one second, your workplace is hiding it from you.',
    body:
      'Sort, set in order, shine, standardise, sustain. The test is not whether the ' +
      'floor looks tidy — it is whether an absence is visible. A shadow board shows a ' +
      'missing spanner instantly; a drawer hides it for ten minutes, every time.',
  },
  {
    id: 'standard-work', chapter: 'toolkit', anchor: 'standard-work',
    title: 'Standard work',
    claim: 'Without a documented current best way, you cannot tell whether a change helped or the day was just lucky.',
    body:
      'Standard work is the baseline improvement is measured against, which makes it ' +
      'the precondition for improvement rather than the enemy of it. Write it with the ' +
      'people who do the work — then improve the standard, not the person.',
  },
  {
    id: 'visual-management', chapter: 'toolkit', anchor: 'visual-management',
    title: 'Visual management',
    claim: 'A visitor should understand the state of your floor in three minutes without asking anyone.',
    body:
      'If they cannot, the information exists only in people\u2019s heads and in a monthly ' +
      'PDF nobody opens. Metrics belong where the work happens: a number nobody sees ' +
      'daily changes nobody\u2019s behaviour.',
  },
  {
    id: 'layout', chapter: 'toolkit', anchor: 'layout', title: 'Spaghetti diagrams',
    claim: 'Trace one product\u2019s actual path on your floor plan. The tangles are waste you can delete with layout alone.',
    body:
      'Transport and motion are the two wastes you can remove without changing how ' +
      'anyone works — you move the benches instead. Store parts at the point of use, in ' +
      'the orientation they are used, at the height they are used; every re-grip is motion.',
  },
  {
    id: 'one-piece-flow', chapter: 'toolkit', anchor: 'flow', title: 'One-piece flow',
    claim: 'In a batch of ten, each part spends nine tenths of its life waiting for its batchmates.',
    body:
      'That is the whole argument for small batches, and it is arithmetic rather than ' +
      'philosophy. Every batch-size reduction cuts lead time, floor space and rework — ' +
      'and each one needs a faster changeover to pay for itself, which is why SMED and ' +
      'flow are the same project.',
  },
  {
    id: 'poka-yoke', chapter: 'toolkit', anchor: 'poka-yoke', title: 'Poka-yoke',
    claim: 'A connector that only fits one way beats a warning label every time.',
    body:
      'Mistake-proofing means designing the step so the error is impossible, not ' +
      'discouraged. Training and attention are consumable; a jig that only accepts the ' +
      'part the right way round is not. Checklists are the cheapest version.',
  },
  {
    id: 'jidoka', chapter: 'toolkit', anchor: 'jidoka', title: 'Jidoka',
    claim: 'One stopped station is cheap. A buffer full of defective parts is not.',
    body:
      'Stop the line when something is wrong, immediately, and give every operator the ' +
      'authority to do it. Root-cause analysis is fastest while the evidence is warm — ' +
      'wait a shift and the trail is cold and the WIP pile is contaminated.',
  },
  {
    id: 'built-in-quality', chapter: 'toolkit', anchor: 'quality',
    title: 'Quality at the source',
    claim: 'The later a defect is found, the more added value is scrapped with it.',
    body:
      'Ten seconds of self-check at the station saves ten minutes of downstream rework — ' +
      'and WIP amplifies the arithmetic, because a systematic error fills the whole ' +
      'buffer before final inspection sees the first bad part. Less WIP, earlier detection.',
  },
  {
    id: 'smed', chapter: 'toolkit', anchor: 'smed', title: 'SMED',
    claim: 'Halve the changeover and you can halve the batch, the WIP and the lead time.',
    body:
      'Split every changeover into external work you can do while the machine runs and ' +
      'internal work you cannot, then move steps from internal to external. Faster ' +
      'changeovers do not just save the changeover — they make small batches economic.',
  },
  {
    id: 'heijunka', chapter: 'toolkit', anchor: 'heijunka', title: 'Heijunka',
    claim: 'Customers order a mix. Producing a week of each creates the demand spikes that force buffers everywhere.',
    body:
      'Level the mix: alternate small batches of A, B and C instead. Unevenness (mura) ' +
      'is what creates overburden, and overburden is what creates waste — so levelling ' +
      'comes first, and it is what makes a tight pull cap livable.',
  },
  {
    id: 'tpm', chapter: 'toolkit', anchor: 'maintenance',
    title: 'Total productive maintenance',
    claim: 'Planned maintenance pauses one station on your schedule. A breakdown pauses the line on the machine\u2019s.',
    body:
      'Small daily care by the operator — clean, inspect, lubricate — prevents the big ' +
      'unplanned stop. The person who runs the machine every day notices the noise ' +
      'change weeks before the bearing seizes, if they have been asked to listen.',
  },
  {
    id: 'pdca', chapter: 'toolkit', anchor: 'pdca', title: 'PDCA',
    claim: 'Most improvement efforts die at "Check", because nobody ever looks.',
    body:
      'Plan, do, check, act is the engine inside kata, genba walks and the five lean ' +
      'steps — the same loop at different scales. Every change is an experiment, so ' +
      'decide before you act which number should move, and then go and look at it.',
  },
  {
    id: 'five-whys', chapter: 'toolkit', anchor: 'five-whys', title: 'Five whys',
    claim: 'Machine stopped \u2192 fuse blew \u2192 bearing seized \u2192 no lubrication \u2192 no maintenance plan. Fixing the fuse cures today.',
    body:
      'Ask why five times to get behind the symptom. Fixing the plan cures the whole ' +
      'class of failures; fixing the fuse means meeting the same fault again next ' +
      'quarter, wearing a different mask.',
  },
  {
    id: 'pareto', chapter: 'toolkit', anchor: 'pareto', title: 'Pareto',
    claim: 'A few defect types cause most of your rework. Count first, then fix the tallest bar.',
    body:
      'The 80/20 rule holds on a shop floor as reliably as anywhere: a few products ' +
      'cause most changeovers, a few causes most scrap. Counting is cheap and it stops ' +
      'you improving the thing that happens to be annoying rather than expensive.',
  },
  {
    id: 'respect-for-people', chapter: 'toolkit', anchor: 'people',
    title: 'Respect for people',
    claim: 'Nobody knows a station\u2019s waste better than the person who runs it eight hours a day.',
    body:
      'Lean\u2019s second pillar, and the one most often skipped. Ask them first; write the ' +
      'standard with them; cross-train deliberately and keep the skill matrix visible. ' +
      'A five-minute daily huddle at the board beats an hour in a conference room.',
  },
]

export function conceptById(id: string): Concept | undefined {
  return CONCEPTS.find((c) => c.id === id)
}

/** The concept a manual section explains, if it is one of these eight. */
export function conceptForAnchor(anchor: string): Concept | undefined {
  return CONCEPTS.find((c) => c.anchor === anchor)
}
