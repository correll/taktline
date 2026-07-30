import React, { useEffect, useState, useMemo } from 'react'
import { useStationsStore, useProcessesStore, useCardsStore, useMachinesStore } from '../../store'
import { statsApi } from '../../api/cards.api'
import { sessionsApi, type SessionStats } from '../../api/sessions.api'
import { color, font, size, shadow } from '../../theme/tokens'
import { STATUS_CSS } from '../../components/map/mapColors'
import type { MachineStatus } from '../../models'
import { formatDistanceToNow } from 'date-fns'
import { MetricInfo, METRICS } from '../../help/MetricInfo'

type Overview = Awaited<ReturnType<typeof statsApi.overview>>

// ─── Refresh interval ─────────────────────────────────────────────────────────
const REFRESH_MS = 15_000

export default function StatisticsView() {
  const [overview,      setOverview]      = useState<Overview | null>(null)
  const [sessionStats,  setSessionStats]  = useState<SessionStats[]>([])
  const [loading,       setLoading]       = useState(true)
  const [lastRefresh,   setLastRefresh]   = useState<Date>(new Date())

  const stations  = useStationsStore((s) => s.stations)
  const processes = useProcessesStore((s) => s.processes)
  const cards     = useCardsStore((s) => s.cards)
  const machines  = useMachinesStore((s) => s.states)

  const fetchOverview = async () => {
    try {
      const [data, stats] = await Promise.all([
        statsApi.overview(),
        sessionsApi.allStats(),
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
  }, [])

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
        <button
          onClick={fetchOverview}
          style={{
            marginLeft:   'auto',
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
          <Panel label="CYCLE TIME, LINE CYCLE TIME & OEE BY STATION" metric="cycleTable" wide>
            {stationList.length === 0 ? (
              <Empty />
            ) : (
              <CycleOeeTable stations={stationList} statsMap={sessionStatsMap} />
            )}
          </Panel>

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
}: {
  stations: import('../../models').Station[]
  statsMap: Record<string, SessionStats>
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
               ['Line cycle time', 'lineCycleTime'], ['OEE', 'oee']] as const).map(([h, metric]) => (
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
            const oeeColor = st?.isWarehouse ? color.textDim
              : st?.oee != null
              ? st.oee >= 0.8 ? color.statusRunning
              : st.oee >= 0.5 ? color.statusWarning
              : color.statusFault
              : color.textDim

            return (
              <tr key={s._id} style={{ borderBottom: `1px solid ${color.border}` }}>
                <td style={{ ...nameCol, display: 'flex', alignItems: 'center', gap: 6 }}>
                  {s.color && <span style={{ width: 8, height: 8, borderRadius: '50%', background: s.color, flexShrink: 0 }} />}
                  {s.name}
                </td>
                <td style={{ ...colStyle, color: color.textSecondary }}>{st?.sessionCount ?? '—'}</td>
                <td style={{ ...colStyle, color: color.textSecondary }}>{st?.totalUnits    ?? '—'}</td>
                <td style={{ ...colStyle, color: color.textSecondary }}>{workMin}</td>
                <td style={{ ...colStyle, color: color.textSecondary }}>{cycle}</td>
                <td style={{ ...colStyle, color: starved ? color.statusWarning : color.textSecondary }}
                    title={starved ? 'Pieces leave much slower than the work takes — waiting, not working'
                                   : undefined}>
                  {lineCycle}
                </td>
                <td style={{ ...colStyle, color: oeeColor, fontWeight: st?.oee != null ? 700 : 400 }}>{oee}</td>
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
