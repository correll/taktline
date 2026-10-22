import React, { useEffect, useState, useMemo } from 'react'
import { useStationsStore, useProcessesStore, useCardsStore, useMachinesStore } from '../../store'
import { statsApi } from '../../api/cards.api'
import { sessionsApi, TREND_WINDOWS, type SessionStats, type TrendWindow } from '../../api/sessions.api'
import { Trend } from './Trend'
import { WhatIf } from './WhatIf'
import { usePlan } from '../../auth/usePlan'
import { StationDetail, type DetailMetric } from './StationDetail'
import { client } from '../../api/client'
import { useRole } from '../../auth/useRole'
import { color, font, size, shadow } from '../../theme/tokens'
import { STATUS_CSS } from '../../components/map/mapColors'
import type { MachineStatus } from '../../models'
import { formatDistanceToNow } from 'date-fns'
import { MetricInfo, METRICS } from '../../help/MetricInfo'

type Overview = Awaited<ReturnType<typeof statsApi.overview>>

// ─── Refresh interval ─────────────────────────────────────────────────────────
const REFRESH_MS = 15_000

export default function StatisticsView() {
  const { lineDoctor } = usePlan()
  const [overview,      setOverview]      = useState<Overview | null>(null)
  const [sessionStats,  setSessionStats]  = useState<SessionStats[]>([])
  const [loading,       setLoading]       = useState(true)
  const [lastRefresh,   setLastRefresh]   = useState<Date>(new Date())
  // Off by default: with no window these are the all-time numbers the page
  // has always shown. Picking one narrows them AND adds the comparison.
  // Which station + view the detail window is showing, if any.
  const [drill, setDrill] = useState<{ id: string; metric: DetailMetric } | null>(null)
  const [trendWindow,   setTrendWindow]   = useState<TrendWindow | null>(() => {
    const v = localStorage.getItem('taktline.stats.window')
    return v && v in TREND_WINDOWS ? (v as TrendWindow) : null
  })

  const stations  = useStationsStore((s) => s.stations)
  const processes = useProcessesStore((s) => s.processes)
  const cards     = useCardsStore((s) => s.cards)
  const machines  = useMachinesStore((s) => s.states)

  const fetchOverview = async () => {
    try {
      const [data, stats] = await Promise.all([
        statsApi.overview(),
        sessionsApi.allStats(trendWindow ?? undefined),
      ])
      setOverview(data)
      setSessionStats(stats)
      setLastRefresh(new Date())
    } catch { /* server may not be running yet */ }
    setLoading(false)
  }

  useEffect(() => {
    fetchOverview()
    const timer = setInterval(fetchOverview, REFRESH_MS)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trendWindow])

  // Keyed session stats for fast lookup
  const sessionStatsMap = useMemo(() => {
    const m: Record<string, SessionStats> = {}
    for (const s of sessionStats) m[s.stationId] = s
    return m
  }, [sessionStats])

  // Live stats derived from store (always up-to-date without polling)
  const liveStats = useMemo(() => {
    const cardList = Object.values(cards)
    const totalLots  = cardList.length
    const flagged    = cardList.filter((c) => c.flagged).length
    const totalUnits = cardList.reduce((s, c) =>
      s + Object.values(c.bins).reduce((b, bin) => b + bin.count, 0), 0)

    const statusCounts: Record<string, number> = {}
    for (const ms of Object.values(machines)) {
      statusCounts[ms.status] = (statusCounts[ms.status] ?? 0) + 1
    }

    return { totalLots, flagged, totalUnits, statusCounts }
  }, [cards, machines])

  // Lots per station derived live from cards store
  const lotsPerStation = useMemo(() => {
    const m: Record<string, number> = {}
    for (const c of Object.values(cards)) {
      for (const [sid, bin] of Object.entries(c.bins)) {
        if (bin.count > 0) m[sid] = (m[sid] ?? 0) + 1
      }
    }
    return m
  }, [cards])

  const stationList = Object.values(stations).sort((a, b) =>
    (lotsPerStation[b._id] ?? 0) - (lotsPerStation[a._id] ?? 0)
  )
  const maxLotsAtStation = Math.max(1, ...stationList.map((s) => lotsPerStation[s._id] ?? 0))

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding:      `${size.sp3} ${size.sp6}`,
        borderBottom: `1px solid ${color.border}`,
        display:      'flex',
        alignItems:   'center',
        gap:          size.sp4,
        flexShrink:   0,
      }}>
        <span style={{ fontSize: 12, fontFamily: font.mono, color: color.textSecondary, letterSpacing: '0.1em' }}>
          STATISTICS
        </span>
        <span style={{ fontSize: 11, color: color.textDim }}>
          refreshes every 15s · last {formatDistanceToNow(lastRefresh, { addSuffix: true })}
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 10, fontFamily: font.mono, color: color.textDim,
                         letterSpacing: '0.08em', marginRight: 2,
                         display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            TREND <MetricInfo metric="trend" />
          </span>
          {([null, '1h', '1d', '1w', '1m'] as const).map((w) => (
            <button
              key={w ?? 'off'}
              onClick={() => {
                setTrendWindow(w)
                if (w) localStorage.setItem('taktline.stats.window', w)
                else localStorage.removeItem('taktline.stats.window')
              }}
              title={w ? `Compare the ${TREND_WINDOWS[w]} against the ${TREND_WINDOWS[w].replace('past', 'previous')}`
                       : 'No comparison — every session on record'}
              style={{
                background:   trendWindow === w ? `${color.bluePrimary}22` : 'transparent',
                border:       `1px solid ${trendWindow === w ? color.bluePrimary : color.border}`,
                borderRadius: size.radius,
                color:        trendWindow === w ? color.textPrimary : color.textSecondary,
                cursor: 'pointer', fontSize: 10.5, fontFamily: font.mono, padding: '3px 8px',
              }}
            >
              {w ?? 'off'}
            </button>
          ))}
        </span>
        <StatsFileMenu window={trendWindow} onWiped={fetchOverview} />
        <button
          onClick={fetchOverview}
          style={{
            background:   'none',
            border:       `1px solid ${color.border}`,
            borderRadius: size.radius,
            color:        color.textSecondary,
            cursor:       'pointer',
            fontSize:     11,
            padding:      '3px 10px',
          }}
        >
          ↻ Refresh
        </button>
      </div>

      {drill && (
        <StationDetail stationId={drill.id} metric={drill.metric} window={trendWindow}
                       onClose={() => setDrill(null)} />
      )}

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: size.sp6 }}>
        {/* KPI tiles */}
        <div style={{
          display:             'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
          gap:                 size.sp4,
          marginBottom:        size.sp6,
        }}>
          <KpiTile label="Total Lots"  metric="totalLots"  value={liveStats.totalLots}  />
          <KpiTile label="Total Units" metric="totalUnits" value={liveStats.totalUnits} />
          <KpiTile label="Flagged"     metric="flagged"    value={liveStats.flagged}    accent={liveStats.flagged > 0 ? color.statusWarning : undefined} />
          <KpiTile label="Stations"    metric="stations"   value={stationList.length}   />
          <KpiTile label="Processes"   metric="processes"  value={Object.values(processes).length} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: size.sp6 }}>

          {/* Station queue depth */}
          <Panel label="LOTS BY STATION" metric="lotsByStation">
            {stationList.length === 0 ? (
              <Empty />
            ) : (
              stationList.slice(0, 12).map((s) => {
                const cnt = lotsPerStation[s._id] ?? 0
                const pct = cnt / maxLotsAtStation
                const ms  = machines[s._id]
                const st  = (ms?.status ?? 'offline') as MachineStatus
                return (
                  <div key={s._id} style={{ marginBottom: 10 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                      <span style={{ fontSize: 12, color: color.textPrimary }}>{s.name}</span>
                      <span style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono }}>
                        {cnt} lot{cnt !== 1 ? 's' : ''}
                      </span>
                    </div>
                    <div style={{ background: color.bgCard, borderRadius: size.radiusFull, height: 6, overflow: 'hidden' }}>
                      <div style={{
                        width:        `${pct * 100}%`,
                        height:       '100%',
                        background:   s.color ?? STATUS_CSS[st] ?? color.bluePrimary,
                        borderRadius: size.radiusFull,
                        transition:   'width 0.4s ease',
                      }} />
                    </div>
                  </div>
                )
              })
            )}
          </Panel>

          {/* Machine status summary */}
          <Panel label="STATION STATUS" metric="stationStatus">
            {Object.values(machines).length === 0 ? (
              <Empty msg="No machines with adapters" />
            ) : (
              <MachineStatusGrid machines={machines} />
            )}
          </Panel>

          {/* Moves over time (last 24h) — only shown after stats load */}
          {overview && (
            <Panel label="MOVES — LAST 24 HOURS" metric="moves24h" wide>
              <SparklineChart
                data={overview.movesPerHour.map((d) => d.moves)}
                labels={overview.movesPerHour.map((d) =>
                  d.hoursAgo === 0 ? 'now' : d.hoursAgo === 1 ? '1h' : `${d.hoursAgo}h`
                )}
              />
            </Panel>
          )}

          {/* Lots per process */}
          <Panel label="LOTS BY PROCESS" metric="lotsByProcess">
            {Object.values(processes).length === 0 ? (
              <Empty />
            ) : (
              Object.values(processes)
                .map((p) => ({ p, count: overview?.lotsPerProcess?.[p._id] ?? 0 }))
                .sort((a, b) => b.count - a.count)
                .map(({ p, count }) => (
                  <div key={p._id} style={{
                    display:        'flex',
                    justifyContent: 'space-between',
                    padding:        `${size.sp2} 0`,
                    borderBottom:   `1px solid ${color.border}`,
                    fontSize:       12,
                  }}>
                    <span style={{ color: color.textPrimary }}>{p.name}</span>
                    <span style={{ color: color.textDim, fontFamily: font.mono }}>{count}</span>
                  </div>
                ))
            )}
          </Panel>

          {/* Cycle-time / OEE by station */}
          <Panel label={trendWindow
                  ? `CYCLE TIME, LINE CYCLE TIME & OEE — ${TREND_WINDOWS[trendWindow].toUpperCase()}`
                  : 'CYCLE TIME, LINE CYCLE TIME & OEE BY STATION'} metric="cycleTable" wide>
            {stationList.length === 0 ? (
              <Empty />
            ) : (
              <CycleOeeTable stations={stationList} statsMap={sessionStatsMap} window={trendWindow}
                             onDrill={(id, m) => setDrill({ id, metric: m })} />
            )}
          </Panel>

          {/* Same plan gate as the line doctor: absent rather than refused, so
              no 403 raises the upgrade dialog unprompted. */}
          {lineDoctor && (
            <Panel label="WHAT IF? WHERE WOULD A MACHINE HELP MOST" wide>
              <WhatIf stations={stationList} />
            </Panel>
          )}

        </div>
      </div>
    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function KpiTile({ label, value, accent, metric }: {
  label: string; value: number; accent?: string; metric?: keyof typeof METRICS
}) {
  return (
    <div style={{
      background:   color.bgCard,
      border:       `1px solid ${color.border}`,
      borderRadius: size.radiusMd,
      padding:      `${size.sp4} ${size.sp5}`,
      boxShadow:    shadow.sm,
    }}>
      <div style={{ fontSize: 10, color: color.textDim, fontFamily: font.mono, letterSpacing: '0.1em',
                    marginBottom: 6, display: 'flex', alignItems: 'center', gap: 5 }}>
        {label}{metric && <MetricInfo metric={metric} />}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, fontFamily: font.mono, color: accent ?? color.textPrimary }}>
        {value.toLocaleString()}
      </div>
    </div>
  )
}

function Panel({ label, children, wide, metric }: {
  label: string; children: React.ReactNode; wide?: boolean; metric?: keyof typeof METRICS
}) {
  return (
    <div style={{
      background:   color.bgCard,
      border:       `1px solid ${color.border}`,
      borderRadius: size.radiusMd,
      padding:      size.sp5,
      boxShadow:    shadow.sm,
      gridColumn:   wide ? '1 / -1' : undefined,
    }}>
      <div style={{
        fontSize:      9,
        fontFamily:    font.mono,
        letterSpacing: '0.14em',
        color:         color.textDim,
        marginBottom:  size.sp4,
        display:       'flex',
        alignItems:    'center',
        gap:           6,
      }}>
        {label}{metric && <MetricInfo metric={metric} />}
      </div>
      {children}
    </div>
  )
}

function Empty({ msg = 'No data' }: { msg?: string }) {
  return (
    <div style={{ fontSize: 11, color: color.textDim, padding: `${size.sp4} 0`, textAlign: 'center' }}>
      {msg}
    </div>
  )
}

function MachineStatusGrid({ machines }: { machines: Record<string, import('../../models').MachineState> }) {
  const STATUS_LABELS: Record<string, string> = {
    running: 'Running', idle: 'Idle', warning: 'Warning', fault: 'Fault', offline: 'Offline',
  }
  const counts: Record<string, number> = {}
  for (const ms of Object.values(machines)) {
    counts[ms.status] = (counts[ms.status] ?? 0) + 1
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp3 }}>
      {Object.entries(STATUS_LABELS).map(([st, label]) => {
        const n = counts[st] ?? 0
        return (
          <div key={st} style={{ display: 'flex', alignItems: 'center', gap: size.sp3 }}>
            <span className="status-dot" style={{ background: STATUS_CSS[st as MachineStatus] }} />
            <span style={{ flex: 1, fontSize: 12, color: n > 0 ? color.textPrimary : color.textDim }}>{label}</span>
            <span style={{ fontSize: 13, fontFamily: font.mono, color: n > 0 ? STATUS_CSS[st as MachineStatus] : color.textDim, fontWeight: 600 }}>
              {n}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function CycleOeeTable({
  stations,
  statsMap,
  window: trendWindow,
  onDrill,
}: {
  stations: import('../../models').Station[]
  statsMap: Record<string, SessionStats>
  window:   TrendWindow | null
  onDrill:  (stationId: string, metric: DetailMetric) => void
}) {
  const colStyle: React.CSSProperties = {
    padding:      `${size.sp2} ${size.sp3}`,
    fontSize:     12,
    fontFamily:   font.mono,
    textAlign:    'right',
    whiteSpace:   'nowrap',
  }
  const nameCol: React.CSSProperties = {
    padding:    `${size.sp2} ${size.sp3}`,
    fontSize:   12,
    color:      color.textPrimary,
    fontFamily: font.sans,
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${color.border}` }}>
            {([['Station', undefined], ['Sessions', 'sessions'], ['Units', 'units'],
               ['Working time', 'workingTime'], ['Cycle time', 'cycleTime'],
               ['Line cycle time', 'lineCycleTime'], ['OEE', 'oee'], ['Uptime', undefined],
               ['Avg WIP', undefined]] as const).map(([h, metric]) => (
              <th key={h} style={{
                ...colStyle,
                textAlign:     h === 'Station' ? 'left' : 'right',
                fontSize:      9,
                letterSpacing: '0.1em',
                color:         color.textDim,
                paddingBottom: size.sp3,
              }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  {h}
                  {/* Right-aligned columns would push the card off the table's
                      right edge, so those open leftwards. */}
                  {metric && <MetricInfo metric={metric} />}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stations.map((s) => {
            const st = statsMap[s._id]
            const cycle = st?.cycleTimeSec != null
              ? st.cycleTimeSec >= 60
                ? `${(st.cycleTimeSec / 60).toFixed(1)} min`
                : `${st.cycleTimeSec.toFixed(1)} s`
              : '—'
            // A warehouse stores rather than runs, so it reports no OEE by
            // design — say so instead of showing a bare dash.
            const oee = st?.isWarehouse
              ? 'warehouse'
              : st?.oee != null
                ? `${(st.oee * 100).toFixed(1)}%`
                : '—'
            // The actual exit rate: how often a piece really leaves. Cycle time
            // is how long the work takes; the gap between them is the waiting.
            const lineCycle = st?.lineCycleTimeSec != null
              ? st.lineCycleTimeSec >= 60
                ? `${(st.lineCycleTimeSec / 60).toFixed(1)} min`
                : `${st.lineCycleTimeSec.toFixed(1)} s`
              : '—'
            // Flagged only when the line rate is materially slower than the work
            // itself — that difference is queueing, blocking or transport, and
            // it is the number worth chasing.
            const starved = st?.lineCycleTimeSec != null && st?.cycleTimeSec != null
              && st.cycleTimeSec > 0 && st.lineCycleTimeSec > st.cycleTimeSec * 1.5
            const workMin = st ? `${(st.totalWorkingSec / 60).toFixed(0)} min` : '—'
            // OEE is never tinted good or bad, because it is neither. A high
            // OEE usually means a bottleneck with work queueing in front of
            // it; a low one means the station is starved from upstream. Only
            // the constraint's OEE is worth raising, and a colour cannot know
            // which station that is — so it reads as plain ink and the
            // tooltip carries the judgement.
            const oeeColor = st?.oee != null ? color.textPrimary : color.textDim

            return (
              <tr key={s._id} style={{ borderBottom: `1px solid ${color.border}` }}>
                <td style={{ ...nameCol, display: 'flex', alignItems: 'center', gap: 6 }}>
                  {s.color && <span style={{ width: 8, height: 8, borderRadius: '50%', background: s.color, flexShrink: 0 }} />}
                  {s.name}
                </td>
                <td style={colStyle}>
                  <Drill on={!!st?.sessionCount} onClick={() => onDrill(s._id, 'activity')}>
                    {st?.sessionCount ?? '—'}
                  </Drill>
                </td>
                <td style={colStyle}>
                  <Drill on={!!st?.totalUnits} onClick={() => onDrill(s._id, 'activity')}>
                    {st?.totalUnits ?? '—'}
                  </Drill>
                </td>
                <td style={{ ...colStyle, color: color.textSecondary }}>{workMin}</td>
                <td style={colStyle}>
                  <Drill on={st?.cycleTimeSec != null} onClick={() => onDrill(s._id, 'cycle')}>
                    {cycle}
                  </Drill>
                  {/* Faster work is plainly better, so the arrow may judge. */}
                  {trendWindow && <Trend now={st?.cycleTimeSec} before={st?.previous?.cycleTimeSec}
                                         lowerIsBetter windowLabel={TREND_WINDOWS[trendWindow]} />}
                </td>
                <td style={{ ...colStyle, color: starved ? color.statusWarning : color.textSecondary }}
                    title={starved ? 'Pieces leave much slower than the work takes — waiting, not working'
                                   : undefined}>
                  <Drill on={st?.lineCycleTimeSec != null}
                         onClick={() => onDrill(s._id, 'lineCycle')}>{lineCycle}</Drill>
                  {trendWindow && <Trend now={st?.lineCycleTimeSec}
                                         before={st?.previous?.lineCycleTimeSec} lowerIsBetter
                                         windowLabel={TREND_WINDOWS[trendWindow]} />}
                </td>
                <td style={{ ...colStyle, color: oeeColor, fontWeight: st?.oee != null ? 700 : 400 }}>
                  <Drill on={st?.oee != null} onClick={() => onDrill(s._id, 'activity')}>
                    {oee}
                  </Drill>
                  {/* No lowerIsBetter: a rising OEE can be a station working
                      more OR a bottleneck queueing work in front of it, so the
                      arrow states the direction and passes on the verdict. */}
                  {trendWindow && !st?.isWarehouse
                    && <Trend now={st?.oee} before={st?.previous?.oee} unit="%"
                              windowLabel={TREND_WINDOWS[trendWindow]} />}
                </td>
                {/* Uptime is what the data box asks for and a timer cannot give:
                    it comes from Pauses marked as breakdowns. Shown with the
                    downtime behind it, so 100% with nothing recorded is not
                    mistaken for a station that never stops. */}
                <td style={{ ...colStyle, color: color.textSecondary }}
                    title={st?.downtimeSec ? `${(st.downtimeSec / 60).toFixed(0)} min down in ${st.breakdowns} breakdown(s)`
                                           : 'No breakdowns recorded'}>
                  {st?.uptime != null && st.downtimeSec ? `${(st.uptime * 100).toFixed(1)}%` : '—'}
                </td>
                {/* The average over the window, from the lot history — not the
                    count on the board right now, which swings through the day. */}
                <td style={{ ...colStyle, color: color.textSecondary }}>
                  {st?.wipAvg != null ? st.wipAvg.toFixed(st.wipAvg < 10 ? 1 : 0) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function SparklineChart({ data, labels }: { data: number[]; labels: string[] }) {
  const h       = 80
  const w       = 600
  const max     = Math.max(1, ...data)
  const barW    = w / data.length

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${w} ${h + 24}`} style={{ width: '100%', minWidth: 300, display: 'block' }}>
        {data.map((v, i) => {
          const bh   = (v / max) * h
          const x    = i * barW
          const fill = v > 0 ? color.bluePrimary : color.bgElevated
          return (
            <g key={i}>
              <rect
                x={x + 2} y={h - bh}
                width={barW - 4} height={Math.max(2, bh)}
                rx={2} fill={fill} opacity={0.85}
              />
              {(i % 4 === 0 || i === data.length - 1) && (
                <text
                  x={x + barW / 2} y={h + 16}
                  textAnchor="middle"
                  fontSize={8}
                  fill={color.textDim}
                  fontFamily={font.mono}
                >
                  {labels[i]}
                </text>
              )}
              {v > 0 && (
                <text
                  x={x + barW / 2} y={h - bh - 4}
                  textAnchor="middle"
                  fontSize={7}
                  fill={color.textSecondary}
                  fontFamily={font.mono}
                >
                  {v}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}


/** Take the statistics away as a spreadsheet, or clear them and start again.
 *
 *  Behind the same file icon the floor plan uses for the line document — the
 *  two are the same gesture ("this page, as a file") and should not look like
 *  different features.
 */
function StatsFileMenu({ window: trendWindow, onWiped }: {
  window: TrendWindow | null
  onWiped: () => void
}) {
  const { isSuperAdmin } = useRole()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  const doExport = async () => {
    setBusy('export')
    try {
      const blob = await client.get('/reports/export.xlsx', {
        responseType: 'blob',
        params: trendWindow ? { window: trendWindow } : undefined,
      }) as unknown as Blob
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `taktline-statistics-${new Date().toISOString().slice(0, 10)}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
      setOpen(false)
    } catch (e) { setNote(String(e)) } finally { setBusy(null) }
  }

  const doWipe = async () => {
    setBusy('wipe')
    try {
      const r = await client.post('/admin/reset-statistics', {}) as
        { workSessionsDeleted: number; cardEventsDeleted: number }
      setNote(`Cleared ${r.workSessionsDeleted} work session${r.workSessionsDeleted === 1 ? '' : 's'}`
              + ` and ${r.cardEventsDeleted} lot event${r.cardEventsDeleted === 1 ? '' : 's'}.`)
      setConfirming(false)
      setOpen(false)
      onWiped()
    } catch (e) { setNote(String(e)) } finally { setBusy(null) }
  }

  const item: React.CSSProperties = {
    display: 'block', width: '100%', textAlign: 'left', background: 'transparent',
    border: 'none', color: color.textPrimary, padding: '7px 10px', fontSize: 12.5,
    cursor: 'pointer', borderRadius: 4, fontFamily: font.sans,
  }

  return (
    <div style={{ position: 'relative', display: 'inline-flex' }}>
      {open && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 60 }} onClick={() => setOpen(false)} />
          <div style={{
            position: 'absolute', top: 34, right: 0, zIndex: 61, width: 250,
            background: color.bgPanel, border: `1px solid ${color.border}`,
            borderRadius: size.radiusMd, boxShadow: shadow.lg, padding: 5,
          }}>
            <button style={item} disabled={busy !== null} onClick={doExport}>
              ⬇ {busy === 'export' ? 'Building…' : 'Export spreadsheet (.xlsx)'}
              <div style={{ fontSize: 11, color: color.textDim, marginTop: 2, lineHeight: 1.45 }}>
                Stations, sessions, lot history, lots and orders — one sheet each.
                {trendWindow && ` Stations cover the ${TREND_WINDOWS[trendWindow]}.`}
              </div>
            </button>
            {isSuperAdmin && (
              <button style={{ ...item, color: color.statusFault }}
                      onClick={() => setConfirming(true)}>
                ⌫ Clear all statistics
                <div style={{ fontSize: 11, color: color.textDim, marginTop: 2, lineHeight: 1.45 }}>
                  Deletes the measured history. The line and its lots stay.
                </div>
              </button>
            )}
          </div>
        </>
      )}

      {confirming && (
        <div onClick={(e) => { if (e.target === e.currentTarget) setConfirming(false) }}
             style={{ position: 'fixed', inset: 0, zIndex: 1000, background: color.backdrop,
                      display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: color.bgPanel, border: `1px solid ${color.border}`,
                        borderRadius: size.radiusMd, padding: size.sp6, width: 420,
                        boxShadow: shadow.lg, display: 'flex', flexDirection: 'column',
                        gap: size.sp4 }}>
            <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>
              Clear all statistics?
            </div>
            <div style={{ fontSize: 12.5, color: color.textSecondary, lineHeight: 1.6 }}>
              This deletes every <b>work session</b> and every <b>lot movement</b> ever
              recorded — so cycle time, line cycle time, OEE and each lot’s history start
              from nothing. It cannot be undone.
              <br /><br />
              Your stations, routes, products, the lots on the floor and your production
              orders are <b>not</b> touched. Export first if you want to keep the numbers.
            </div>
            <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end' }}>
              <button onClick={() => setConfirming(false)}
                      style={{ padding: '6px 14px', background: 'transparent',
                               border: `1px solid ${color.border}`, borderRadius: size.radius,
                               color: color.textSecondary, cursor: 'pointer', fontSize: 12 }}>
                Cancel
              </button>
              <button onClick={doWipe} disabled={busy === 'wipe'}
                      style={{ padding: '6px 14px', background: color.statusFault,
                               border: 'none', borderRadius: size.radius, color: '#fff',
                               cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
                {busy === 'wipe' ? 'Clearing…' : 'Clear statistics'}
              </button>
            </div>
          </div>
        </div>
      )}

      <button
        onClick={() => { setNote(null); setOpen((v) => !v) }}
        title="Export or clear the statistics"
        style={{
          width: 26, height: 24, background: 'none',
          border: `1px solid ${color.border}`, borderRadius: size.radius,
          color: color.textSecondary, cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        {/* The same document mark the floor plan uses for its line file. */}
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
      </button>

      {note && (
        <span style={{ position: 'absolute', top: 30, right: 0, whiteSpace: 'nowrap',
                       fontSize: 11, color: color.textSecondary, background: color.bgPanel,
                       border: `1px solid ${color.border}`, borderRadius: size.radius,
                       padding: '4px 8px', zIndex: 61 }}
              onClick={() => setNote(null)}>
          {note}
        </span>
      )}
    </div>
  )
}


/** A number you can open. Underlined on hover rather than always, so the table
 *  still reads as a table — but the cursor changes on the whole cell, which is
 *  what makes the affordance findable without decorating every figure. */
function Drill({ on, onClick, children }: {
  on: boolean; onClick: () => void; children: React.ReactNode
}) {
  const [hover, setHover] = useState(false)
  if (!on) return <span style={{ color: color.textSecondary }}>{children}</span>
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title="Show the numbers behind this"
      style={{
        background: 'none', border: 'none', padding: 0, font: 'inherit',
        color: hover ? color.blueBright : color.textSecondary,
        textDecoration: hover ? 'underline' : 'none',
        cursor: 'pointer',
      }}
    >
      {children}
    </button>
  )
}
