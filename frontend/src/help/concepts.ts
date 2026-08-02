/**
 * The eight flow-science results, distilled to card size.
 *
 * This is NOT a second copy of the manual's Flow science chapter. The manual
 * explains; a card has to *land* on a stranger's phone in one glance, so each
 * entry here is the one claim the result makes, the number that makes it
 * uncomfortable, and a shape that can be animated. `anchor` points at the
 * chapter section that does the explaining, so the card is always an invitation
 * to the manual rather than a replacement for it.
 *
 * `id` is the public URL of the share card (`/i/<id>`) and is permanent.
 */

export type ConceptAnimation =
  | 'queue'        // a station filling as utilization rises
  | 'wip'          // lots on a line, halved, lead time halving with them
  | 'balance'      // work-content bars against the slowest
  | 'flow'         // a lead-time bar with a sliver of value-added
  | 'control'      // a run chart with limits, common vs special cause
  | 'matched'      // three feeds, an assembly waiting for the last
  | 'monument'     // small cells vs one big machine everything routes to
  | 'constraint'   // a chain, one weak link

export interface Concept {
  id: string
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
  animation: ConceptAnimation
}

export const CONCEPTS: Concept[] = [
  {
    id: 'littles-law',
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
    anchor: 'variability',
    title: 'Common cause and special cause',
    claim: 'Adjusting a process for every wobble makes it worse. Most "corrective action" is tampering.',
    body:
      'Shewhart\'s split: common-cause variation is inherent to the system and can only be reduced ' +
      'by changing the system; special-cause variation has a findable external origin. Inside the ' +
      'limits, do not react. A station bouncing between 58% and 66% OEE has a system to improve; ' +
      'one that drops to 30% on Tuesdays has an event to find.',
    animation: 'control',
  },
  {
    id: 'matched-sets',
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
]

export function conceptById(id: string): Concept | undefined {
  return CONCEPTS.find((c) => c.id === id)
}

/** The concept a manual section explains, if it is one of these eight. */
export function conceptForAnchor(anchor: string): Concept | undefined {
  return CONCEPTS.find((c) => c.anchor === anchor)
}
