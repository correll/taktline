import type { SessionStats } from '../api/sessions.api'

/** Turning measured takt times into a visible rhythm.
 *
 *  ── Why one shared divisor and not a per-station clamp ────────────────────
 *  Real takt times are tens to hundreds of seconds, so clamping each station
 *  independently into a 1.2–6s window would map *every* station to 6s: a line
 *  where one station takes twice as long as the next would pulse in perfect
 *  unison, which is precisely the opposite of what the display is for. The
 *  synchronicity of the line is carried by the *ratios* between periods, and
 *  only a single shared divisor preserves them.
 *
 *  So: pick one compression factor from the data, apply it to every station,
 *  and clamp only as a backstop for genuine outliers. A station at twice the
 *  takt of its neighbour then visibly pulses at half its rate — the bottleneck
 *  is the slow heartbeat, findable from across the shop floor without reading
 *  a number. The factor is reported so nobody mistakes 3 seconds for 3 seconds.
 *
 *  ── Never fake a period ───────────────────────────────────────────────────
 *  A station with too little timing data does not pulse. A still node means
 *  "not measured yet", which is honest and self-correcting; a node pulsing at
 *  an invented rate is a number someone will eventually plan against.
 */

/** Below this a "takt time" is one or two jobs and sampling noise, not a beat. */
const MIN_SESSIONS = 3
const MIN_UNITS    = 3

/** The comfortable range for a visible rhythm. Slower than ~6s stops reading
 *  as a pulse; faster than ~1.2s starts to feel like a warning light. */
export const MIN_PERIOD_MS = 1200
export const MAX_PERIOD_MS = 6000
/** Aim the middle of the line here, then let the spread fall where it falls. */
const TARGET_MID_MS = 3000

/** Round to something a human can hold: ×50, ×100, ×200 — never ×137. */
const NICE = [1, 2, 5, 10, 20, 30, 60, 100, 200, 300, 600, 1000, 2000, 5000, 10000]
function niceFactor(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 1
  for (const n of NICE) if (raw <= n) return n
  return NICE[NICE.length - 1]
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b)
  const m = s.length >> 1
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

export interface TaktPulses {
  /** stationId → pulse period in ms. Absent = not enough data, do not pulse. */
  periodMs:    Record<string, number>
  /** How much faster than reality, e.g. 100 → one pulse per 100 s of takt. */
  compression: number
  /** True when every measured station shares essentially one beat. */
  synchronous: boolean
  /** Stations whose true ratio could not be shown because they hit a bound. */
  clamped:     number
  /** How many stations are pulsing at all. */
  measured:    number
  /** Slowest measured station — the bottleneck, in real seconds. */
  slowestSec:  number | null
}

export const EMPTY_PULSES: TaktPulses = {
  periodMs: {}, compression: 1, synchronous: false, clamped: 0, measured: 0, slowestSec: null,
}

/** A line is "in step" when its stations hold the same beat. 15% covers
 *  ordinary measurement scatter without excusing a real imbalance. */
const SYNC_TOLERANCE = 1.15

export function computeTaktPulses(stats: SessionStats[]): TaktPulses {
  const usable = stats.filter((s) =>
    s.taktTimeSec != null && s.taktTimeSec > 0 &&
    s.sessionCount >= MIN_SESSIONS && s.totalUnits >= MIN_UNITS &&
    // A warehouse stores rather than works: its "takt" is how fast things were
    // put on a shelf, which is not a beat the line has to hold.
    !s.isWarehouse)

  if (usable.length === 0) return EMPTY_PULSES

  const takts = usable.map((s) => s.taktTimeSec as number)
  const compression = niceFactor(median(takts) * 1000 / TARGET_MID_MS)

  const periodMs: Record<string, number> = {}
  let clamped = 0
  for (const s of usable) {
    const raw = (s.taktTimeSec as number) * 1000 / compression
    const bounded = Math.min(MAX_PERIOD_MS, Math.max(MIN_PERIOD_MS, raw))
    if (Math.abs(bounded - raw) > 1) clamped++
    periodMs[s.stationId] = bounded
  }

  // Judge synchronicity on the *true* takts, not the clamped periods — the
  // clamp is a display bound and must never make a ragged line look tidy.
  const lo = Math.min(...takts), hi = Math.max(...takts)
  return {
    periodMs, compression,
    synchronous: usable.length > 1 && hi / lo <= SYNC_TOLERANCE,
    clamped, measured: usable.length,
    slowestSec: hi,
  }
}

/** Phase, so the pulses mean something next to each other.
 *
 *  CSS animations start when the element mounts, so stations that render a few
 *  hundred ms apart would drift out of step for no reason and a balanced line
 *  would look ragged. Anchoring the delay to the wall clock puts every station
 *  — and every tablet in the building — on one shared beat, which is what
 *  makes "are these in step?" a question the display can actually answer.
 */
export function pulseDelaySeconds(periodMs: number, now = Date.now()): number {
  return -((now % periodMs) / 1000)
}
