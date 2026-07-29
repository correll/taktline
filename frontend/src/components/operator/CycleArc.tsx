import React from 'react'
import { color, font, size } from '../../theme/tokens'

/** Pace against the station's expected cycle time, for the operator.
 *
 *  ── The constraint that shapes this ───────────────────────────────────────
 *  The target is the **station's** cycle time, never the individual's. Two things
 *  follow, and both are deliberate:
 *
 *  - It is off unless a company switches it on (`globalSettings.showCycleArc`,
 *    default false). Pace feedback shown to the person doing the work is the
 *    line between a useful signal and surveillance, and where that line sits
 *    is a local decision — in much of the EU, one a works council has to be
 *    able to make.
 *  - Nothing here is recorded or compared per operator. The arc is a live
 *    read-out that disappears when the session ends.
 *
 *  Past 100% it turns to the starved colour rather than an alarm red: running
 *  over the station's own cycle time is information about the *line*, most often that this station is
 *  the constraint. It is not an accusation, and it must not look like one.
 *
 *  A station with no measured cycle time shows no arc. There is no target to be
 *  behind, and inventing one would be the worst version of this feature.
 */

const W   = 232
const PAD = 6
const SW  = 7
const R   = (W - PAD * 2 - SW) / 2
const H   = R + SW + 2

export function CycleArc({ elapsedSec, expectedSec }: {
  elapsedSec:  number
  /** Station cycle time × units in this session. */
  expectedSec: number
}) {
  if (!(expectedSec > 0)) return null

  const ratio = elapsedSec / expectedSec
  const over  = ratio > 1
  // The arc itself stops at full; the number carries the overage, because a
  // ring that keeps going has nowhere to go and stops meaning anything.
  const shown = Math.min(1, Math.max(0, ratio))
  // #EF9F27 — the design system's starved step (tokens.ts calls it that).
  const stroke = over ? color.statusWarning : color.statusRunning

  const y  = H - SW / 2 - 1
  const d  = `M ${PAD + SW / 2} ${y} A ${R} ${R} 0 0 1 ${W - PAD - SW / 2} ${y}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <svg width={W} height={H} style={{ display: 'block', overflow: 'visible' }}
           role="img"
           aria-label={`${Math.round(ratio * 100)} percent of the expected time for this station`}>
        <path d={d} fill="none" stroke={color.border} strokeWidth={SW} strokeLinecap="round" />
        <path
          d={d} fill="none" stroke={stroke} strokeWidth={SW} strokeLinecap="round"
          pathLength={100}
          strokeDasharray={`${shown * 100} 100`}
          style={{ transition: 'stroke-dasharray 0.9s linear, stroke 0.3s ease' }}
        />
      </svg>
      <div style={{
        fontFamily: font.mono, fontSize: 10, letterSpacing: '0.1em',
        color: over ? color.statusWarning : color.textDim, marginTop: -2,
      }}>
        {Math.round(ratio * 100)}% OF STATION CYCLE TIME
      </div>
      {over && (
        <div style={{ fontSize: 10.5, color: color.textDim, marginTop: 3, textAlign: 'center',
                      maxWidth: W, lineHeight: 1.45 }}>
          Over the station&rsquo;s usual pace — often the sign of a constraint here.
        </div>
      )}
    </div>
  )
}

export default CycleArc
