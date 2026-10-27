import React, { useEffect, useState } from 'react'
import { client } from '../../api/client'
import { TREND_WINDOWS, type TrendWindow } from '../../api/sessions.api'
import { color, font, size, shadow } from '../../theme/tokens'

/** What is behind one number on the statistics table.
 *
 *  An average hides the thing you most need to see. A bench on the simulated
 *  line averaged 30 s per piece: sixteen sessions near 4 s and one 80 s stall.
 *  "Slow station" and "usually quick but occasionally jams" are different
 *  problems with different fixes, and only the distribution tells them apart.
 *
 *  Which view opens depends on which number was clicked, because the same
 *  chart does not suit every measurement:
 *
 *    cycle time        → distribution. The mean lies here most.
 *    line cycle time   → run chart. It IS a temporal quantity.
 *    sessions / units  → by hour of day, against the configured work hours.
 *    utilisation       → the same by-hour view: utilisation is working time over OPEN
 *                        time, so where the work fell relative to the schedule
 *                        is the explanation, not a second ratio.
 */
export type DetailMetric = 'cycle' | 'lineCycle' | 'activity'

interface Sample { t: string; secPerPiece: number; units?: number }
interface Detail {
  stationName: string
  cycleSamples: Sample[]
  departureSamples: Sample[]
  byHour: { hour: number; sessions: number; units: number }[]
  openHours: number[]
  timezone: string
}

const TITLES: Record<DetailMetric, string> = {
  cycle: 'Cycle time — how long the work takes',
  lineCycle: 'Line cycle time — how often a piece leaves',
  activity: 'Activity by hour of day',
}

export function StationDetail({ stationId, metric, window: win, onClose }: {
  stationId: string
  metric: DetailMetric
  window: TrendWindow | null
  onClose: () => void
}) {
  const [data, setData] = useState<Detail | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    client.get(`/sessions/stats/${stationId}/detail`,
               win ? { params: { window: win } } : undefined)
      .then((d) => setData(d as unknown as Detail))
      .catch((e) => setErr(String(e)))
  }, [stationId, win])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const samples = metric === 'cycle' ? data?.cycleSamples
                : metric === 'lineCycle' ? data?.departureSamples : undefined

  return (
    <div onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
         style={{ position: 'fixed', inset: 0, zIndex: 1200, background: color.backdrop,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  padding: size.sp6 }}>
      <div style={{ background: color.bgPanel, border: `1px solid ${color.border}`,
                    borderRadius: size.radiusLg, boxShadow: shadow.lg,
                    width: 720, maxWidth: '100%', maxHeight: '86vh', overflowY: 'auto',
                    padding: size.sp6, display: 'flex', flexDirection: 'column',
                    gap: size.sp4 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp3 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: color.textPrimary }}>
            {data?.stationName ?? '…'}
          </span>
          <span style={{ fontSize: 12.5, color: color.textSecondary }}>{TITLES[metric]}</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, fontFamily: font.mono,
                         color: color.textDim }}>
            {win ? TREND_WINDOWS[win].toUpperCase() : 'ALL TIME'}
          </span>
          <button onClick={onClose} style={{ background: 'none', border: 'none',
                  color: color.textDim, fontSize: 20, cursor: 'pointer', lineHeight: 1 }}>×</button>
        </div>

        {err && <div style={{ fontSize: 12.5, color: color.statusFault }}>{err}</div>}
        {!data && !err && <div style={{ fontSize: 12.5, color: color.textDim }}>Loading…</div>}

        {data && metric === 'cycle' && <Distribution samples={samples ?? []} />}
        {data && metric === 'lineCycle' && <RunChart samples={samples ?? []} />}
        {data && metric === 'activity' && (
          <ByHour rows={data.byHour} open={data.openHours} tz={data.timezone} />
        )}
      </div>
    </div>
  )
}

// ─── Distribution ────────────────────────────────────────────────────────────

/** Below this many samples a histogram invents a shape the data cannot
 *  support, so the individual values are drawn instead and the count is said
 *  plainly. Twenty sessions binned into eight buckets is noise wearing the
 *  costume of a distribution. */
const MIN_FOR_BINS = 20

function Distribution({ samples }: { samples: Sample[] }) {
  const xs = samples.map((s) => s.secPerPiece).sort((a, b) => a - b)
  if (xs.length === 0) return <Empty>No completed work sessions in this window.</Empty>

  const pct = (p: number) => xs[Math.min(xs.length - 1, Math.floor(p * xs.length))]
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length
  const stats = [
    ['median', pct(0.5)], ['p90', pct(0.9)], ['mean', mean],
    ['fastest', xs[0]], ['slowest', xs[xs.length - 1]],
  ] as const

  return (
    <>
      <Numbers rows={stats.map(([k, v]) => [k, fmt(v)])} n={xs.length} />
      {/* The mean is shown beside the median deliberately: when they diverge,
          the gap IS the finding — a tail is dragging the average. */}
      {mean > pct(0.5) * 1.5 && (
        <Note>
          The mean is {(mean / pct(0.5)).toFixed(1)}× the median — a few long cycles are
          dragging the average. That is a stability problem (a jam, a missing part, a
          question), not a slow method.
        </Note>
      )}
      {xs.length < MIN_FOR_BINS
        ? <><Strip xs={xs} /><Note>
            Only {xs.length} session{xs.length === 1 ? '' : 's'} — too few to bin, so each
            one is drawn. Treat any shape here as a coincidence.
          </Note></>
        : <Histogram xs={xs} />}
    </>
  )
}

function Histogram({ xs }: { xs: number[] }) {
  const lo = xs[0], hi = xs[xs.length - 1]
  const bins = Math.min(14, Math.max(6, Math.round(Math.sqrt(xs.length))))
  const w = (hi - lo) / bins || 1
  const counts = new Array(bins).fill(0)
  for (const x of xs) counts[Math.min(bins - 1, Math.floor((x - lo) / w))]++
  const peak = Math.max(...counts)
  const H = 150, W = 660

  return (
    <svg viewBox={`0 0 ${W} ${H + 30}`} style={{ width: '100%' }}>
      {counts.map((c, i) => {
        const bw = W / bins
        const h = (c / peak) * H
        return (
          <g key={i}>
            <rect x={i * bw + 1.5} y={H - h} width={bw - 3} height={h}
                  rx={2} fill={color.bluePrimary} opacity={0.85}>
              <title>{`${c} session${c === 1 ? '' : 's'} between ${fmt(lo + i * w)} and ${fmt(lo + (i + 1) * w)}`}</title>
            </rect>
            {c > 0 && (
              <text x={i * bw + bw / 2} y={H - h - 4} textAnchor="middle"
                    fontSize={9} fill={color.textDim} fontFamily={font.mono}>{c}</text>
            )}
          </g>
        )
      })}
      <line x1={0} y1={H} x2={W} y2={H} stroke={color.border} />
      <text x={0} y={H + 16} fontSize={10} fill={color.textDim} fontFamily={font.mono}>{fmt(lo)}</text>
      <text x={W} y={H + 16} textAnchor="end" fontSize={10} fill={color.textDim}
            fontFamily={font.mono}>{fmt(hi)}</text>
      <text x={W / 2} y={H + 27} textAnchor="middle" fontSize={10} fill={color.textDim}>
        seconds per piece
      </text>
    </svg>
  )
}

function Strip({ xs }: { xs: number[] }) {
  const lo = xs[0], hi = xs[xs.length - 1] || 1
  const W = 660, H = 54
  const at = (x: number) => hi === lo ? W / 2 : ((x - lo) / (hi - lo)) * (W - 20) + 10
  return (
    <svg viewBox={`0 0 ${W} ${H + 22}`} style={{ width: '100%' }}>
      <line x1={10} y1={H / 2} x2={W - 10} y2={H / 2} stroke={color.border} />
      {xs.map((x, i) => (
        <circle key={i} cx={at(x)} cy={H / 2} r={5} fill={color.bluePrimary} opacity={0.55}>
          <title>{fmt(x)} per piece</title>
        </circle>
      ))}
      <text x={10} y={H + 16} fontSize={10} fill={color.textDim} fontFamily={font.mono}>{fmt(lo)}</text>
      <text x={W - 10} y={H + 16} textAnchor="end" fontSize={10} fill={color.textDim}
            fontFamily={font.mono}>{fmt(hi)}</text>
    </svg>
  )
}

// ─── Run chart ───────────────────────────────────────────────────────────────

function RunChart({ samples }: { samples: Sample[] }) {
  if (samples.length === 0) return <Empty>No departures recorded in this window.</Empty>
  const ys = samples.map((s) => s.secPerPiece)
  const ts = samples.map((s) => new Date(s.t).getTime())
  const sorted = [...ys].sort((a, b) => a - b)
  const median = sorted[Math.floor(sorted.length / 2)]
  const hi = Math.max(...ys), t0 = ts[0], t1 = ts[ts.length - 1] || t0 + 1
  const W = 660, H = 170
  const x = (t: number) => t1 === t0 ? W / 2 : ((t - t0) / (t1 - t0)) * (W - 20) + 10
  const y = (v: number) => H - (v / (hi || 1)) * (H - 14)

  return (
    <>
      <Numbers n={ys.length} rows={[
        ['median', fmt(median)],
        ['fastest', fmt(sorted[0])],
        ['slowest', fmt(hi)],
        ['span', `${Math.round((t1 - t0) / 60000)} min`],
      ]} />
      <svg viewBox={`0 0 ${W} ${H + 26}`} style={{ width: '100%' }}>
        {/* The median as a reference line: the run chart's question is
            "is it drifting", which needs a level to drift from. */}
        <line x1={10} y1={y(median)} x2={W - 10} y2={y(median)}
              stroke={color.textDim} strokeDasharray="3 3" opacity={0.7} />
        <text x={W - 10} y={y(median) - 4} textAnchor="end" fontSize={9}
              fill={color.textDim} fontFamily={font.mono}>median {fmt(median)}</text>
        <polyline
          points={samples.map((s, i) => `${x(ts[i])},${y(ys[i])}`).join(' ')}
          fill="none" stroke={color.bluePrimary} strokeWidth={2}
          strokeLinejoin="round" strokeLinecap="round" opacity={0.85} />
        {samples.map((s, i) => (
          <circle key={i} cx={x(ts[i])} cy={y(ys[i])} r={2.5} fill={color.bluePrimary}>
            <title>{`${fmt(ys[i])} per piece · ${new Date(s.t).toLocaleTimeString()}`}</title>
          </circle>
        ))}
        <line x1={10} y1={H} x2={W - 10} y2={H} stroke={color.border} />
        <text x={10} y={H + 16} fontSize={10} fill={color.textDim} fontFamily={font.mono}>
          {new Date(t0).toLocaleTimeString()}
        </text>
        <text x={W - 10} y={H + 16} textAnchor="end" fontSize={10} fill={color.textDim}
              fontFamily={font.mono}>{new Date(t1).toLocaleTimeString()}</text>
      </svg>
    </>
  )
}

// ─── Activity by hour ────────────────────────────────────────────────────────

function ByHour({ rows, open, tz }: {
  rows: { hour: number; sessions: number; units: number }[]
  open: number[]
  tz: string
}) {
  const peak = Math.max(1, ...rows.map((r) => r.units))
  const total = rows.reduce((a, r) => a + r.sessions, 0)
  if (total === 0) return <Empty>No work sessions in this window.</Empty>
  const openSet = new Set(open)
  const outside = rows.filter((r) => r.sessions > 0 && !openSet.has(r.hour))
  const outsideUnits = outside.reduce((a, r) => a + r.units, 0)
  const W = 660, H = 150

  return (
    <>
      <Numbers n={total} rows={[
        ['busiest hour', `${rows.reduce((a, b) => b.units > a.units ? b : a).hour}:00`],
        ['hours worked', String(rows.filter((r) => r.sessions).length)],
        ['outside schedule', outsideUnits ? `${outsideUnits} units` : 'none'],
      ]} />
      {outsideUnits > 0 && (
        <Note>
          {outsideUnits} unit{outsideUnits === 1 ? ' was' : 's were'} worked outside the hours
          this company is configured as open ({open.length ? `${open[0]}:00–${open[open.length - 1] + 1}:00` : 'none set'}).
          Utilisation divides working time by OPEN time, so work in the shaded hours does not count
          towards it — either the schedule is wrong or the shift is.
        </Note>
      )}
      <svg viewBox={`0 0 ${W} ${H + 32}`} style={{ width: '100%' }}>
        {rows.map((r) => {
          const bw = W / 24
          const h = (r.units / peak) * H
          const isOpen = openSet.has(r.hour)
          return (
            <g key={r.hour}>
              {!isOpen && (
                <rect x={r.hour * bw} y={0} width={bw} height={H}
                      fill={color.textDim} opacity={0.07} />
              )}
              <rect x={r.hour * bw + 1.5} y={H - h} width={bw - 3} height={h} rx={2}
                    fill={isOpen ? color.bluePrimary : color.statusWarning} opacity={0.85}>
                <title>{`${r.hour}:00 — ${r.units} units over ${r.sessions} sessions`
                        + (isOpen ? '' : ' (outside configured work hours)')}</title>
              </rect>
              {r.hour % 3 === 0 && (
                <text x={r.hour * bw + bw / 2} y={H + 14} textAnchor="middle" fontSize={9}
                      fill={color.textDim} fontFamily={font.mono}>{r.hour}</text>
              )}
            </g>
          )
        })}
        <line x1={0} y1={H} x2={W} y2={H} stroke={color.border} />
        <text x={W / 2} y={H + 29} textAnchor="middle" fontSize={10} fill={color.textDim}>
          units worked, by hour of day ({tz}) — shaded hours are outside the work schedule
        </text>
      </svg>
    </>
  )
}

// ─── Small shared pieces ─────────────────────────────────────────────────────

function fmt(s: number): string {
  return s >= 60 ? `${(s / 60).toFixed(1)} min` : `${s.toFixed(s < 10 ? 1 : 0)} s`
}

function Numbers({ rows, n }: { rows: readonly (readonly [string, string])[]; n: number }) {
  return (
    <div style={{ display: 'flex', gap: size.sp5, flexWrap: 'wrap',
                  borderBottom: `1px solid ${color.border}`, paddingBottom: size.sp3 }}>
      {rows.map(([k, v]) => (
        <div key={k}>
          <div style={{ fontSize: 9.5, fontFamily: font.mono, letterSpacing: '0.08em',
                        color: color.textDim, textTransform: 'uppercase' }}>{k}</div>
          <div style={{ fontSize: 15, color: color.textPrimary, fontFamily: font.mono }}>{v}</div>
        </div>
      ))}
      <div style={{ marginLeft: 'auto', alignSelf: 'flex-end', fontSize: 11,
                    color: color.textDim, fontFamily: font.mono }}>n = {n}</div>
    </div>
  )
}

const Note: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ fontSize: 11.5, color: color.textSecondary, lineHeight: 1.55,
                borderLeft: `2px solid ${color.bluePrimary}66`, paddingLeft: size.sp3 }}>
    {children}
  </div>
)

const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ fontSize: 12.5, color: color.textDim, padding: `${size.sp6} 0`,
                textAlign: 'center' }}>{children}</div>
)
