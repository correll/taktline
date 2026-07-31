import React, { useEffect, useState } from 'react'
import FlowScene, { useFlowSimulation } from '../../components/demo/FlowScene'
import { DEMO_LINES, makeStep, type DemoLine } from './demoLines'
import { color, font, size } from '../../theme/tokens'

/** The landing hero: three real lines, rotating.
 *
 *  One would have been enough to show flow. Three make the point the single
 *  scene could not: a battery teardown, a lay of fleece and a mitred window
 *  frame are the same graph. Whatever you build, the thing that is hard is one
 *  lot becoming several, worked in parallel, and coming back together — and
 *  that is what this draws, three times, in three trades.
 */

const DWELL_MS = 11_000       // long enough to watch a cycle breathe
const FADE_MS = 550

function useIsNarrow(breakpoint = 720): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < breakpoint)
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < breakpoint)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [breakpoint])
  return narrow
}

/** One line, simulated. Mounted under a key so switching lines restarts its
 *  own simulation from its own initial stock rather than inheriting the
 *  previous trade's half-finished work. */
function OneLine({ line, narrow }: { line: DemoLine; narrow: boolean }) {
  const wip = useFlowSimulation(line.initial, makeStep(line), 650)
  return narrow
    ? <FlowScene stations={line.compact} edges={line.compactEdges} wip={wip}
                 worldW={644} worldH={400} node={92} maxWip={9}
                 processNames={line.processNames} />
    : <FlowScene stations={line.stations} edges={line.edges} wip={wip}
                 worldW={1180} worldH={440} node={92} maxWip={9}
                 processNames={line.processNames} />
}

export default function LiveLineDemo() {
  const narrow = useIsNarrow()
  const [i, setI] = useState(0)
  const [visible, setVisible] = useState(true)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    if (paused) return
    const hold = setTimeout(() => {
      setVisible(false)                                    // fade out…
      const swap = setTimeout(() => {
        setI((n) => (n + 1) % DEMO_LINES.length)           // …swap…
        setVisible(true)                                   // …fade in
      }, FADE_MS)
      return () => clearTimeout(swap)
    }, DWELL_MS)
    return () => clearTimeout(hold)
  }, [i, paused])

  const line = DEMO_LINES[i]
  const show = (n: number) => { setVisible(false); setTimeout(() => { setI(n); setVisible(true) }, FADE_MS / 2) }

  return (
    <div
      style={{ position: 'relative' }}
      onMouseEnter={() => setPaused(true)}    // let someone read it
      onMouseLeave={() => setPaused(false)}
    >
      <div style={{ opacity: visible ? 1 : 0, transition: `opacity ${FADE_MS}ms ease` }}>
        <OneLine key={line.id} line={line} narrow={narrow} />
      </div>

      {/* Which trade this is, and how to reach the others. Named rather than
          left to the station labels: the whole point is that three different
          industries are the same graph, which only lands if the industries are
          said out loud. */}
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0,
        display: 'flex', alignItems: 'center', gap: size.sp3,
        padding: `${size.sp2} ${size.sp4}`, pointerEvents: 'none',
      }}>
        <span style={{
          fontSize: 11.5, fontFamily: font.mono, color: color.textSecondary,
          opacity: visible ? 1 : 0, transition: `opacity ${FADE_MS}ms ease`,
        }}>
          {line.label}
          <span style={{ color: color.textDim }}> · {line.blurb}</span>
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, pointerEvents: 'auto' }}>
          {DEMO_LINES.map((l, n) => (
            <button
              key={l.id}
              onClick={() => show(n)}
              aria-label={l.label}
              aria-current={n === i}
              style={{
                width: n === i ? 16 : 7, height: 7, borderRadius: 4, padding: 0,
                border: 'none', cursor: 'pointer',
                background: n === i ? color.bluePrimary : color.border,
                transition: 'width 0.3s ease, background 0.3s ease',
              }}
            />
          ))}
        </span>
      </div>
    </div>
  )
}
