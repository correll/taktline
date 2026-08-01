import { useEffect, useState } from 'react'
import { color, font, shadow, size } from '../../theme/tokens'

/**
 * The line doctor, shown reading a line rather than described.
 *
 * The findings here are verbatim what `core/analysis.py` produces for a line
 * of this shape — same phrasing, same arithmetic, same TIMWOOD labels. A
 * marketing page that paraphrases its own product's output ends up promising
 * something warmer and vaguer than what arrives, and the first real report
 * then reads as a let-down. If the copy here ever drifts from the engine, the
 * engine is right and this is wrong.
 *
 * The bulb lights on a loop because that is the moment worth showing: it is
 * dark until the line has been running long enough to say something about
 * pace, then it comes on by itself.
 */

type Finding = {
  severity: 'critical' | 'warning' | 'insight'
  waste?: string
  title: string
  detail: string
}

// A garment line: the four cut branches feed one sewing bench, and the bench
// is paced by whichever panel arrives last.
const FINDINGS: Finding[] = [
  {
    severity: 'warning',
    waste: 'Waiting',
    title: 'Sewing line is the constraint',
    detail:
      'A finished unit’s worth of work leaves it every 9m 40s, against 3m 12s elsewhere on ' +
      'Crew neck. That is the pace of the whole line, whatever the other stations manage — an ' +
      'hour lost here is an hour lost for everything, and an hour saved anywhere else is a ' +
      'mirage. More signs point the same way: nine units are queued at it, and Print & pack ' +
      'downstream is idle waiting for it.',
  },
  {
    severity: 'warning',
    waste: 'Overproduction',
    title: 'Work piles up at Ribbing',
    detail:
      'Every cycle delivers six units into Ribbing on Crew neck while the next step consumes ' +
      'one — a surplus of five per cycle, built into the weights rather than caused by anyone’s ' +
      'pace. It will grow for as long as the line runs. Route the surplus to a storage ' +
      'location, or correct the ratio.',
  },
  {
    severity: 'insight',
    waste: 'Inventory',
    title: 'A unit crosses Crew neck in 4.1h; only 6% of that is work',
    detail:
      'By Little’s law — lead time is WIP divided by throughput — the twenty-two units on the ' +
      'floor at today’s exit rate mean about 4.1h from release to finish, of which the work ' +
      'itself is 15m 20s. The other 94% is waiting. Most job shops live in single digits here, ' +
      'so this is not an accusation — it is the largest lever on the board.',
  },
]

const TONE: Record<Finding['severity'], { fg: string; label: string }> = {
  critical: { fg: '#E24B4A', label: 'Stops the line' },
  warning: { fg: '#EF9F27', label: 'Costs you every cycle' },
  insight: { fg: '#888780', label: 'Worth knowing' },
}

export default function DoctorDemo() {
  const [lit, setLit] = useState(false)
  const [still, setStill] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const apply = () => setStill(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    if (still) { setLit(true); return }
    const t = setInterval(() => setLit((v) => !v), 2600)
    return () => clearInterval(t)
  }, [still])

  const on = still || lit

  return (
    <div style={{
      border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
      background: color.bgPanel, boxShadow: shadow.lg, overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, padding: '10px 14px',
        borderBottom: `1px solid ${color.border}`,
      }}>
        {[0, 1, 2].map((n) => (
          <span key={n} style={{ width: 10, height: 10, borderRadius: '50%', background: color.border }} />
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 11, fontFamily: font.mono, color: color.textDim }}>
          line doctor · computed on your own server
        </span>
      </div>

      <div style={{ display: 'flex', gap: size.sp5, padding: size.sp5,
                    background: color.bgDeep, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {/* The bulb, doing the one thing it does: coming on. */}
        <div aria-hidden="true" style={{
          width: 84, height: 84, borderRadius: '50%', flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          border: `1px solid ${on ? '#EF9F2766' : color.border}`,
          background: on ? '#EF9F2714' : 'transparent',
          color: on ? '#EF9F27' : color.textDim,
          opacity: on ? 1 : 0.45,
          boxShadow: on ? '0 0 30px #EF9F2744' : 'none',
          transition: 'all 700ms ease',
        }}>
          <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            {on && <circle cx="12" cy="9" r="5.4" fill="currentColor" opacity="0.22" />}
            <path d="M9 18h6M10 21h4" />
            <path d="M12 3a6 6 0 0 0-3.6 10.8c.5.4.8.9.9 1.5l.1.7h5.2l.1-.7c.1-.6.4-1.1.9-1.5A6 6 0 0 0 12 3Z" />
          </svg>
        </div>

        <div style={{ flex: 1, minWidth: 280 }}>
          <div style={{ fontSize: 16, fontWeight: 500, color: color.textPrimary }}>
            Sewing line is the constraint
          </div>
          <p style={{ margin: `${size.sp2} 0 0`, fontSize: 13, lineHeight: 1.6, color: color.textSecondary }}>
            Your line has nine work stations, two processes, one merge and one split. Two problems
            are costing you time or material every cycle.
          </p>

          <div style={{ marginTop: size.sp4, display: 'flex', flexDirection: 'column', gap: size.sp3 }}>
            {FINDINGS.map((f) => {
              const tone = TONE[f.severity]
              return (
                <div key={f.title} style={{
                  borderLeft: `3px solid ${tone.fg}`, background: color.bgCard,
                  borderRadius: size.radius, padding: size.sp3,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: size.sp2, flexWrap: 'wrap' }}>
                    <span style={{
                      fontSize: 9, fontFamily: font.mono, letterSpacing: '0.08em',
                      textTransform: 'uppercase', color: tone.fg,
                    }}>
                      {tone.label}
                    </span>
                    {f.waste && (
                      <span style={{
                        fontSize: 9, fontFamily: font.mono, color: color.textDim,
                        border: `1px solid ${color.border}`, borderRadius: size.radiusFull,
                        padding: '0 6px',
                      }}>
                        {f.waste}
                      </span>
                    )}
                  </div>
                  <div style={{ marginTop: 4, fontSize: 13, fontWeight: 500, color: color.textPrimary }}>
                    {f.title}
                  </div>
                  <p style={{ margin: '4px 0 0', fontSize: 12.5, lineHeight: 1.55, color: color.textSecondary }}>
                    {f.detail}
                  </p>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
