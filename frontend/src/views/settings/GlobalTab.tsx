import React, { useEffect, useRef, useState } from 'react'
import { languageLabel, LANGUAGE_CODES } from '../../i18n/languages'
import { useGlobalSettingsStore } from '../../store/globalSettings.store'
import { COMMON_TIMEZONES, defaultWorkHours, FULL_HOUR } from '../../api/globalSettings.api'
import { color, font, size } from '../../theme/tokens'
import { FieldLabel, inputStyle, primaryBtn } from './shared'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function validGrid(g: number[][] | undefined): number[][] {
  return g && g.length === 7 && g.every((r) => r.length === 24) ? g.map((r) => [...r]) : defaultWorkHours()
}

export default function GlobalTab() {
  const { settings, loading, fetch, update } = useGlobalSettingsStore()
  const [timezone, setTimezone] = useState(settings.timezone)
  const [grid,     setGrid]     = useState<number[][]>(() => validGrid(settings.workHours))
  const [taktArc,  setCycleArc]  = useState(settings.showCycleArc)
  const [tracking, setTracking]  = useState(settings.orderTracking)
  const [trackSteps, setTrackSteps] = useState(settings.orderTrackingSteps)
  const [langs, setLangs] = useState<string[]>(settings.supportedLanguages ?? LANGUAGE_CODES)
  const [saved,    setSaved]    = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  useEffect(() => { fetch() }, [])
  useEffect(() => { setTimezone(settings.timezone) }, [settings.timezone])
  useEffect(() => { setGrid(validGrid(settings.workHours)) }, [settings.workHours])
  useEffect(() => { setCycleArc(settings.showCycleArc) }, [settings.showCycleArc])
  useEffect(() => { setTracking(settings.orderTracking) }, [settings.orderTracking])
  useEffect(() => { setTrackSteps(settings.orderTrackingSteps) }, [settings.orderTrackingSteps])
  useEffect(() => { setLangs(settings.supportedLanguages ?? LANGUAGE_CODES) }, [settings.supportedLanguages])

  const handleSave = async () => {
    setError(null); setSaved(false)
    try {
      await update({ timezone, workHours: grid, showCycleArc: taktArc,
                     orderTracking: tracking, orderTrackingSteps: trackSteps,
                     supportedLanguages: langs })
      setSaved(true); setTimeout(() => setSaved(false), 2000)
    } catch (e) { setError(String(e)) }
  }

  const openQuarters = grid.reduce((sum, row) => sum + row.reduce((a, c) => a + popcount(c), 0), 0)
  const openHours = openQuarters / 4
  const openHoursLabel = Number.isInteger(openHours) ? String(openHours) : openHours.toFixed(2)

  return (
    <div style={{ padding: size.sp6, overflow: 'auto', height: '100%', boxSizing: 'border-box' }}>
      <div style={{ marginBottom: size.sp6 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary, marginBottom: 4 }}>Global Settings</div>
        <div style={{ fontSize: 11, color: color.textDim }}>System-wide configuration for all users.</div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp6, maxWidth: 720 }}>
        {/* Timezone */}
        <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1, maxWidth: 360 }}>
          <FieldLabel>TIMEZONE</FieldLabel>
          <select value={timezone} onChange={(e) => setTimezone(e.target.value)} disabled={loading}
                  style={{ ...inputStyle, fontFamily: font.mono }}>
            {COMMON_TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
          </select>
          <span style={{ fontSize: 10, color: color.textDim, marginTop: 2 }}>
            Used for timestamps, statistics, and evaluating the work hours below. IANA timezone name.
          </span>
        </label>

        {/* Operator pace feedback — deliberately opt-in. */}
        <div>
          <FieldLabel>OPERATOR PACE FEEDBACK</FieldLabel>
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: size.sp3,
                          marginTop: 6, cursor: 'pointer', maxWidth: 620 }}>
            <input
              type="checkbox" checked={taktArc} disabled={loading}
              onChange={(e) => setCycleArc(e.target.checked)}
              style={{ marginTop: 2, width: 16, height: 16, flexShrink: 0, cursor: 'pointer' }}
            />
            <span style={{ fontSize: 11.5, color: color.textDim, lineHeight: 1.55 }}>
              Show a progress arc in the Operator view while a work session runs, filling
              against <b style={{ color: color.textSecondary }}>the station&rsquo;s</b> measured
              cycle time. Past 100% it turns amber.
              <br />
              <b style={{ color: color.textSecondary }}>Off by default, and station-level only</b> —
              never per operator, and nothing extra is recorded. Pace shown to the person doing the
              work is the line between useful feedback and monitoring, so switching it on is a
              deliberate local decision (in much of the EU, one for a works council). Stations with
              no measured cycle time show no arc.
            </span>
          </label>
        </div>

        {/* Customer order tracking — opt-in, because it publishes something. */}
        <div>
          <FieldLabel>CUSTOMER ORDER TRACKING</FieldLabel>
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: size.sp3,
                          marginTop: 6, cursor: 'pointer', maxWidth: 620 }}>
            <input
              type="checkbox" checked={tracking} disabled={loading}
              onChange={(e) => setTracking(e.target.checked)}
              style={{ marginTop: 2, width: 16, height: 16, flexShrink: 0, cursor: 'pointer' }}
            />
            <span style={{ fontSize: 11.5, color: color.textDim, lineHeight: 1.55 }}>
              Give every production order a <b style={{ color: color.textSecondary }}>read-only
              link</b> you can send to the customer who placed it. They see that order&rsquo;s
              progress — nothing else, no login, and no way to reach anything of yours.
              <br />
              <b style={{ color: color.textSecondary }}>Off by default.</b> The link is
              unguessable and switching this off stops every one of them immediately; switching
              it back on restores the same links, so a customer&rsquo;s bookmark keeps working.
              Copy a link from the order list in Settings &rarr; Integrations.
            </span>
          </label>

          <label style={{ display: 'flex', alignItems: 'flex-start', gap: size.sp3,
                          marginTop: size.sp3, marginLeft: size.sp6,
                          cursor: tracking ? 'pointer' : 'not-allowed',
                          opacity: tracking ? 1 : 0.5, maxWidth: 580 }}>
            <input
              type="checkbox" checked={trackSteps} disabled={loading || !tracking}
              onChange={(e) => setTrackSteps(e.target.checked)}
              style={{ marginTop: 2, width: 16, height: 16, flexShrink: 0 }}
            />
            <span style={{ fontSize: 11.5, color: color.textDim, lineHeight: 1.55 }}>
              Name the steps on that page (&ldquo;Saw, Weld, Paint, Pack — here now&rdquo;).
              Turn it off to show only a percentage: your process is your business, and plenty
              of shops will happily say &ldquo;60% done&rdquo; without telling a customer which
              operations they run and which they subcontract.
            </span>
          </label>
        </div>

        {/* Languages */}
        <div>
          <FieldLabel>LANGUAGES</FieldLabel>
          <p style={{ fontSize: 11.5, color: color.textDim, margin: '4px 0 10px', lineHeight: 1.5, maxWidth: 620 }}>
            The languages this company runs in. <b style={{ color: color.textSecondary }}>Operators
            you invite choose their language from this set</b> — offer only what your lot cards,
            station names and instructions actually make sense in. Everyone can change their own
            language later in their account.
          </p>
          <div style={{ display: 'flex', gap: size.sp4, flexWrap: 'wrap' }}>
            {LANGUAGE_CODES.map((code) => (
              <label key={code} style={{ display: 'flex', alignItems: 'center', gap: size.sp2,
                                         fontSize: 13, color: color.textPrimary, cursor: 'pointer' }}>
                <input
                  type="checkbox" disabled={loading}
                  checked={langs.includes(code)}
                  onChange={(e) => setLangs(e.target.checked
                    ? [...langs, code]
                    : langs.length > 1 ? langs.filter((l) => l !== code) : langs)}
                  style={{ width: 15, height: 15 }}
                />
                {languageLabel(code)}
              </label>
            ))}
          </div>
        </div>

        {/* Work hours */}
        <div>
          <FieldLabel>WORK HOURS</FieldLabel>
          <p style={{ fontSize: 11.5, color: color.textDim, margin: '4px 0 10px', lineHeight: 1.5, maxWidth: 620 }}>
            The hours your plant is meant to be running. <b style={{ color: color.textSecondary }}>OEE is measured
            against these</b> (working time ÷ open time), so nights and weekends don't count against you.
            <b style={{ color: color.textSecondary }}> Click a cell</b> to trim its open window in 15-minute steps —
            first the start (opens :15, :30, :45), then the end (closes :45, :30, :15) — for shifts that begin or
            end on the quarter-hour; <b style={{ color: color.textSecondary }}>drag</b> to fill a block open or closed.
          </p>
          <WorkHoursMatrix grid={grid} setGrid={setGrid} />
          <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3, marginTop: size.sp3, flexWrap: 'wrap' }}>
            <button style={miniBtn} onClick={() => setGrid(defaultWorkHours())}>Mon–Fri 9–5</button>
            <button style={miniBtn} onClick={() => setGrid(Array.from({ length: 7 }, () => Array(24).fill(FULL_HOUR)))}>24 / 7</button>
            <button style={miniBtn} onClick={() => setGrid(Array.from({ length: 7 }, () => Array(24).fill(0)))}>Clear</button>
            <span style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono, marginLeft: 'auto' }}>
              {openHoursLabel} open hours / week
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3 }}>
          <button onClick={handleSave} disabled={loading} style={primaryBtn(loading)}>Save</button>
          {saved && <span style={{ fontSize: 11, color: color.statusRunning, fontFamily: font.mono }}>✓ Saved</span>}
          {error && <span style={{ fontSize: 11, color: color.statusFault }}>{error}</span>}
        </div>
      </div>
    </div>
  )
}

// Each cell is a 4-bit quarter mask (bit i = the i-th 15-min quarter, bit 0 = :00–:15).
const OPEN_FILL   = '#2563EB'
const CLOSED_FILL = 'var(--tk-bg-elevated)'
const popcount = (m: number) => ((m >> 0) & 1) + ((m >> 1) & 1) + ((m >> 2) & 1) + ((m >> 3) & 1)

// Click cycle: full → trim the start (opens :15/:30/:45) → trim the end (closes :45/:30/:15) → closed → full.
const CYCLE = [0b1111, 0b1110, 0b1100, 0b1000, 0b0111, 0b0011, 0b0001, 0b0000]
const nextState = (v: number) => {
  const i = CYCLE.indexOf(v)
  return i === -1 ? 0b1110 : CYCLE[(i + 1) % CYCLE.length]
}

function WorkHoursMatrix({ grid, setGrid }: { grid: number[][]; setGrid: (g: number[][]) => void }) {
  // A click (no drag) cycles a cell's open window; a drag fills a rectangle fully
  // open/closed. The window mouseup commits whichever happened.
  const [drag, setDrag] = useState<{ aD: number; aH: number; cD: number; cH: number; val: number; moved: boolean } | null>(null)
  const dragRef = useRef(drag); dragRef.current = drag

  const inRect = (d: number, h: number, x = drag) =>
    !!x && d >= Math.min(x.aD, x.cD) && d <= Math.max(x.aD, x.cD) && h >= Math.min(x.aH, x.cH) && h <= Math.max(x.aH, x.cH)

  useEffect(() => {
    const up = () => {
      const x = dragRef.current
      if (!x) return
      if (x.moved) {
        setGrid(grid.map((row, d) => row.map((c, h) => (inRect(d, h, x) ? x.val : c))))
      } else {
        setGrid(grid.map((row, d) => row.map((c, h) => (d === x.aD && h === x.aH ? nextState(c) : c))))
      }
      setDrag(null)
    }
    window.addEventListener('mouseup', up)
    return () => window.removeEventListener('mouseup', up)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid])

  const CELL = 22
  const cellVal = (d: number, h: number) => (drag && drag.moved && inRect(d, h) ? drag.val : grid[d][h])
  // Describe a cell's open window from its quarter mask, e.g. "Mon 09:15–10:00 · 45 min".
  const tip = (day: string, h: number, mask: number) => {
    const clk = (m: number) => `${String(h + Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
    if (mask === 0) return `${day} ${clk(0)} · closed`
    if (mask === FULL_HOUR) return `${day} ${clk(0)}–${clk(60)} · open`
    const open = [0, 1, 2, 3].filter((i) => mask & (1 << i))
    return `${day} ${clk(open[0] * 15)}–${clk((open[open.length - 1] + 1) * 15)} · ${open.length * 15} min`
  }

  return (
    <div style={{ overflowX: 'auto', userSelect: 'none', border: `1px solid ${color.border}`,
                  borderRadius: size.radius, background: color.bgCard, padding: 10, width: 'fit-content', maxWidth: '100%' }}>
      <div style={{ display: 'grid', gridTemplateColumns: `44px repeat(24, ${CELL}px)`, gap: 2 }}>
        {/* Hour header */}
        <div />
        {Array.from({ length: 24 }, (_, h) => (
          <div key={h} style={{ fontSize: 9, color: color.textDim, textAlign: 'center', fontFamily: font.mono,
                                lineHeight: '14px', height: 14 }}>
            {h % 2 === 0 ? h : ''}
          </div>
        ))}
        {/* Day rows */}
        {DAYS.map((day, d) => (
          <React.Fragment key={day}>
            <div style={{ fontSize: 11, color: d >= 5 ? color.textDim : color.textSecondary, display: 'flex',
                          alignItems: 'center', fontFamily: font.mono, height: CELL }}>{day}</div>
            {Array.from({ length: 24 }, (_, h) => {
              const mask = Math.max(0, Math.min(15, cellVal(d, h)))
              const open = [0, 1, 2, 3].filter((i) => mask & (1 << i))
              const lo = open.length ? open[0] : 0
              const hi = open.length ? open[open.length - 1] + 1 : 0
              // Blue bar positioned over the open quarters (25% each), dark elsewhere.
              const bg = mask === 0
                ? CLOSED_FILL
                : `linear-gradient(90deg, ${CLOSED_FILL} 0 ${lo * 25}%, ${OPEN_FILL} ${lo * 25}% ${hi * 25}%, ${CLOSED_FILL} ${hi * 25}% 100%)`
              return (
                <div key={h}
                     onMouseDown={() => setDrag({ aD: d, aH: h, cD: d, cH: h, val: grid[d][h] === 0 ? FULL_HOUR : 0, moved: false })}
                     onMouseEnter={() => setDrag((x) => (x ? { ...x, cD: d, cH: h, moved: x.moved || d !== x.aD || h !== x.aH } : x))}
                     title={tip(day, h, mask)}
                     style={{ height: CELL, borderRadius: 3, cursor: 'pointer', background: bg,
                              border: `1px solid ${mask ? '#2A4E86' : color.border}`,
                              opacity: drag && drag.moved && inRect(d, h) ? 0.85 : 1 }} />
              )
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}

const miniBtn: React.CSSProperties = {
  background: 'transparent', border: `1px solid ${color.border}`, color: color.textSecondary,
  borderRadius: size.radius, padding: '5px 12px', fontSize: 12, cursor: 'pointer',
}
