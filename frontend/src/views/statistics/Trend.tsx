import React from 'react'
import { color, font } from '../../theme/tokens'

/** Which way a measurement moved against the window before it.
 *
 *  `lowerIsBetter` decides the colour, and some measurements have no answer to
 *  that question: OEE is the standing example — a rising OEE can mean the
 *  station is working more, or that a bottleneck is queueing work in front of
 *  it, and the manual says in as many words not to optimise it. Where "better"
 *  is genuinely ambiguous the arrow is drawn in plain ink: the direction is a
 *  fact, the judgement is not.
 *
 *  A move under `deadband` reads as sideways. Without one, noise flips the
 *  arrow every refresh and it stops meaning anything.
 */
export function Trend({ now, before, lowerIsBetter, unit = '', deadband = 0.05, windowLabel }: {
  now: number | null | undefined
  before: number | null | undefined
  lowerIsBetter?: boolean
  unit?: string
  deadband?: number
  /** e.g. "past day" — named so the "nothing to compare with" marker can say
   *  which window came up empty. */
  windowLabel?: string
}) {
  // A missing comparison is *said*, not left blank. Rendering nothing looked
  // exactly like the feature being broken: you pick a window, the table does
  // not visibly change, and there is no way to tell whether the line was
  // steady or simply idle in the window before.
  if (now == null || before == null || before === 0) {
    if (now == null) return null           // nothing measured here at all
    return (
      <span
        title={`No history from the ${windowLabel ? windowLabel.replace('past', 'previous') : 'previous window'} to compare with`}
        style={{ marginLeft: 5, color: color.textDim, fontFamily: font.mono,
                 fontSize: 11, cursor: 'help', opacity: 0.6 }}
      >
        ·
      </span>
    )
  }
  const change = (now - before) / Math.abs(before)
  const flat = Math.abs(change) < deadband
  const up = change > 0

  const glyph = flat ? '→' : up ? '↑' : '↓'
  const tint = flat || lowerIsBetter === undefined
    ? color.textDim
    : (up === !lowerIsBetter) ? color.statusRunning : color.statusWarning

  const pct = `${change > 0 ? '+' : ''}${(change * 100).toFixed(0)}%`
  const was = unit === '%' ? `${(before * 100).toFixed(1)}%`
            : before >= 60 ? `${(before / 60).toFixed(1)} min`
            : `${before.toFixed(1)}${unit || ' s'}`

  return (
    <span
      title={flat ? `Unchanged (${pct}) — was ${was}` : `${pct} — was ${was}`}
      style={{ marginLeft: 5, color: tint, fontFamily: font.mono, fontSize: 11, cursor: 'help' }}
    >
      {glyph}
    </span>
  )
}
