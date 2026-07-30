import React, { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useHelpStore } from './helpStore'
import { color, font, size, shadow } from '../theme/tokens'

/** What every number on the Statistics page means, in one place.
 *
 *  A measurement nobody can define is a measurement nobody should act on —
 *  and these are exactly the ones that get acted on wrongly (chasing OEE,
 *  reading cycle time as takt). Each entry says what it IS, how it is
 *  computed, and — the part a bare definition leaves out — how to READ it:
 *  what a high or low value should make you do.
 *
 *  `section` deep-links into the user manual, which carries the long form.
 */
export interface MetricDef {
  title:   string
  what:    string
  how?:    string
  read?:   string
  section?: string     // heading id in UserManual
}

export const METRICS: Record<string, MetricDef> = {
  totalLots: {
    title: 'Total lots',
    what: 'How many lot cards exist right now, anywhere on the line.',
    how: 'One card can carry many units, so this counts cards, not pieces.',
    read: 'Rising while output is flat means work is piling up between stations.',
    section: 'concepts',
  },
  totalUnits: {
    title: 'Total units',
    what: 'Every physical piece currently on the line, across all lot cards.',
    how: 'The sum of all bins on all cards — your work in process (WIP).',
    read: 'WIP is inventory: it costs money, hides defects and lengthens lead '
        + 'time. Less WIP at the same output is always better.',
    section: 'waste',
  },
  flagged: {
    title: 'Flagged lots',
    what: 'Lots someone marked as needing attention.',
    read: 'A flag is a question a worker could not answer alone. Clear them '
        + 'daily — an old flag stops being a signal.',
  },
  stations: {
    title: 'Stations',
    what: 'Places where work happens, including queues, warehouses and the '
        + 'integration nodes your ERP connects to.',
    section: 'concepts',
  },
  processes: {
    title: 'Processes',
    what: 'Value streams drawn on the same floor. Each has its own routes, '
        + 'products and weights.',
    how: 'Alternative routing is modelled as a separate process, so branches '
        + 'and merges are only ever judged inside one.',
    section: 'concepts',
  },
  lotsByStation: {
    title: 'Lots by station',
    what: 'How many lot cards are waiting at each station right now.',
    read: 'The tallest bar is where work queues. That is your constraint — or '
        + 'the station right after one.',
    section: 'statistics',
  },
  stationStatus: {
    title: 'Station status',
    what: 'Live state reported by stations that have a machine adapter '
        + 'configured (running, idle, fault, offline).',
    read: 'Stations without an adapter are not shown — this is machine '
        + 'telemetry, not work-session data.',
  },
  moves24h: {
    title: 'Moves — last 24 hours',
    what: 'How many times a lot moved between stations, by hour.',
    how: 'Every transport is counted, whether one piece or a hundred.',
    read: 'Transport is one of the seven wastes: it adds cost and risk but no '
        + 'value. A tall bar every hour means material is travelling a lot — '
        + 'look for stations that could sit closer together.',
    section: 'waste',
  },
  lotsByProcess: {
    title: 'Lots by process',
    what: 'How the lot cards on the floor divide between your value streams.',
    read: 'Useful when several products share the same stations: it shows '
        + 'which line is actually occupying the floor.',
  },
  cycleTable: {
    title: 'Cycle time, line cycle time & OEE',
    what: 'The timing table. Each row is a station; the gap between cycle time '
        + 'and line cycle time is where the waste is.',
    read: 'Work that takes 2 minutes but only ships every 9 is queueing, '
        + 'blocking or transport — speeding up the operator wins nothing.',
    section: 'timing',
  },
  sessions: {
    title: 'Sessions',
    what: 'Completed work sessions at this station in the last 30 days.',
    how: 'One session is one operator pressing Start, working, then Done.',
    read: 'A station with very few sessions has no reliable timing yet — read '
        + 'its other numbers with suspicion.',
  },
  units: {
    title: 'Units',
    what: 'Pieces worked at this station across those sessions.',
    how: 'The operator sets the count when starting, so a lot of ten counts ten.',
  },
  workingTime: {
    title: 'Working time',
    what: 'Total time the timer ran at this station.',
    how: 'The sum of every session duration — the numerator of OEE.',
  },
  cycleTime: {
    title: 'Cycle time',
    what: 'How long the work actually takes, per piece.',
    how: 'Recorded working time ÷ units worked. Measured, never a target.',
    read: 'This is what you improve by changing the work itself: fixtures, '
        + 'layout, batch size. It is NOT takt time — takt is the beat you '
        + 'need, which you set per process in Settings.',
    section: 'timing',
  },
  lineCycleTime: {
    title: 'Line cycle time',
    what: 'How often a piece actually leaves this station — the real exit rate.',
    how: 'The interval between departures, per piece, re-anchored at every '
        + 'shift opening so a lot finished after hours is charged to the next '
        + 'shift rather than to the night.',
    read: 'Compare it with cycle time: the difference is waiting, not working. '
        + 'Amber means pieces leave more than 50% slower than the work takes — '
        + 'the station is starved, blocked, or its output is sitting in a queue.',
    section: 'timing',
  },
  oee: {
    title: 'OEE',
    what: 'Overall equipment effectiveness: the share of open work time this '
        + 'station was actually running.',
    how: 'Working time ÷ scheduled work time, using the work hours you '
        + 'configured — so nights and weekends do not distort it. Warehouses '
        + 'report none: shelf time is not utilisation.',
    read: 'Never optimise OEE for its own sake. A very high OEE usually means '
        + 'a bottleneck with work queueing in front of it; a very low one '
        + 'means the station is starved by a constraint upstream. Only the '
        + 'bottleneck’s OEE is worth raising.',
    section: 'statistics',
  },
}

/** A hoverable "?" that explains one measurement and can open the manual at
 *  the long version. Keyboard reachable (it is a real button), and it opens on
 *  focus and on tap, so it works on the tablets this app runs on.
 *
 *  The card is portalled to the body and positioned fixed: the timing table
 *  scrolls horizontally and the panels clip, so an absolutely-positioned card
 *  lost its right-hand half inside them. Portalling also escapes the inherited
 *  mono/letter-spaced header type, which is why the styles below are absolute
 *  rather than relative to the trigger. */
export function MetricInfo({ metric }: { metric: keyof typeof METRICS }) {
  const def = METRICS[metric]
  const openManual = useHelpStore((s) => s.openManual)
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const wrap = useRef<HTMLSpanElement>(null)
  // The card is portalled out of `wrap`, so 'outside' has to mean outside
  // BOTH — otherwise the pointerdown that presses 'Read more' closes the
  // card before its click can land.
  const card = useRef<HTMLSpanElement>(null)

  const CARD_W = 290
  const place = () => {
    const r = wrap.current?.getBoundingClientRect()
    if (!r) return
    const margin = 8
    const left = Math.min(Math.max(margin, r.left), window.innerWidth - CARD_W - margin)
    // Below by default; above when the bottom of the window is closer than the
    // card is tall (the last table rows sit near it).
    const below = r.bottom + 6
    const top = below + 210 > window.innerHeight && r.top > 220 ? r.top - 6 - 210 : below
    setPos({ left, top })
  }
  const show = () => { place(); setOpen(true) }

  // A tap outside closes it — on a touch screen there is no mouseleave.
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node
      if (!wrap.current?.contains(t) && !card.current?.contains(t)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const away = () => setOpen(false)
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', away, true)
    window.addEventListener('resize', away)
    return () => {
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', away, true)
      window.removeEventListener('resize', away)
    }
  }, [open])

  if (!def) return null

  return (
    <span
      ref={wrap}
      style={{ position: 'relative', display: 'inline-flex', verticalAlign: 'middle' }}
      onMouseEnter={show}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={`What is ${def.title}?`}
        aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); if (open) setOpen(false); else show() }}
        onFocus={show}
        onBlur={(e) => {
          const next = e.relatedTarget as Node | null
          if (!wrap.current?.contains(next) && !card.current?.contains(next)) setOpen(false)
        }}
        style={{
          width: 13, height: 13, borderRadius: '50%', flexShrink: 0,
          border: `1px solid ${color.border}`, background: 'transparent',
          color: color.textDim, fontSize: 9, lineHeight: 1, fontFamily: font.sans,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'help', padding: 0,
        }}
      >
        ?
      </button>

      {open && pos && createPortal(
        <span
          ref={card}
          role="tooltip"
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          style={{
            position: 'fixed', left: pos.left, top: pos.top, zIndex: 10500,
            width: CARD_W, textAlign: 'left',
            background: color.bgPanel, border: `1px solid ${color.border}`,
            borderRadius: size.radiusMd, boxShadow: shadow.lg,
            padding: `${size.sp3} ${size.sp4}`,
            fontFamily: font.sans, cursor: 'default',
            fontWeight: 400, letterSpacing: 'normal', textTransform: 'none',
            display: 'flex', flexDirection: 'column', gap: 6,
          }}
        >
          <span style={{ fontSize: 12.5, fontWeight: 600, color: color.textPrimary }}>
            {def.title}
          </span>
          <span style={{ fontSize: 11.5, color: color.textSecondary, lineHeight: 1.55 }}>
            {def.what}
          </span>
          {def.how && (
            <span style={{ fontSize: 11.5, color: color.textDim, lineHeight: 1.55 }}>
              {def.how}
            </span>
          )}
          {def.read && (
            <span style={{
              fontSize: 11.5, color: color.textSecondary, lineHeight: 1.55,
              borderLeft: `2px solid ${color.bluePrimary}66`, paddingLeft: size.sp3,
            }}>
              {def.read}
            </span>
          )}
          {def.section && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setOpen(false); openManual(def.section) }}
              style={{
                alignSelf: 'flex-start', background: 'none', border: 'none', padding: 0,
                color: color.blueBright, fontSize: 11.5, cursor: 'pointer',
                fontFamily: font.sans, textDecoration: 'underline',
              }}
            >
              Read more in the manual →
            </button>
          )}
        </span>,
        document.body,
      )}
    </span>
  )
}
