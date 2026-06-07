import React, { useMemo, useState } from 'react'
import { useCardsStore, useStationsStore, useProcessesStore } from '../../store'
import { color, font, size } from '../../theme/tokens'
import LotCard from '../../components/lots/LotCard'
import CreateLotModal from '../../components/lots/CreateLotModal'
import MoveLotModal from '../../components/lots/MoveLotModal'
import LotDetailModal from '../../components/lots/LotDetailModal'
import type { Card, Route } from '../../models'

interface ActiveMove   { card: Card; fromStationId: string }
interface ActiveDetail { card: Card; stationId: string }

// ─── Routing helper ───────────────────────────────────────────────────────────
// Returns all station IDs reachable forward from `fromStationId`,
// up to and including the next merge point (node with >1 incoming routes).
export function getValidDestinations(
  fromStationId: string,
  routes: Record<string, Route>,
): string[] {
  const outgoing: Record<string, string[]> = {}
  const inDegree: Record<string, number>   = {}

  for (const r of Object.values(routes)) {
    if (!outgoing[r.load]) outgoing[r.load] = []
    outgoing[r.load].push(r.unload)
    inDegree[r.unload] = (inDegree[r.unload] ?? 0) + 1
  }

  const valid   = new Set<string>()
  const visited = new Set<string>([fromStationId])
  const queue   = [...(outgoing[fromStationId] ?? [])]

  while (queue.length > 0) {
    const sid = queue.shift()!
    if (visited.has(sid)) continue
    visited.add(sid)
    valid.add(sid)
    // Don't expand past merge nodes (they're valid targets, but paths stop there)
    if ((inDegree[sid] ?? 0) > 1) continue
    for (const next of outgoing[sid] ?? []) {
      if (!visited.has(next)) queue.push(next)
    }
  }

  return [...valid]
}

// ─── View ─────────────────────────────────────────────────────────────────────

export default function LotsView() {
  const cards     = useCardsStore((s) => s.cards)
  const stations  = useStationsStore((s) => s.stations)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const routes    = useProcessesStore((s) => s.routes)

  const [createStation, setCreateStation] = useState<string | null>(null)
  const [activeMove,    setActiveMove]    = useState<ActiveMove | null>(null)
  const [activeDetail,  setActiveDetail]  = useState<ActiveDetail | null>(null)

  // Topological order: process start → end (left to right)
  const topoOrder = useMemo(() => {
    const outgoing: Record<string, string[]> = {}
    const inDeg: Record<string, number> = {}
    for (const s of Object.values(stations)) { outgoing[s._id] = []; inDeg[s._id] = 0 }
    for (const r of Object.values(routes)) {
      outgoing[r.load]?.push(r.unload)
      inDeg[r.unload] = (inDeg[r.unload] ?? 0) + 1
    }
    const queue = Object.keys(inDeg).filter((id) => inDeg[id] === 0)
    const order: string[] = []
    while (queue.length > 0) {
      const id = queue.shift()!
      order.push(id)
      for (const next of outgoing[id] ?? []) {
        inDeg[next]--
        if (inDeg[next] === 0) queue.push(next)
      }
    }
    // Append any remaining (e.g. disconnected nodes)
    for (const id of Object.keys(stations)) {
      if (!order.includes(id)) order.push(id)
    }
    return order
  }, [stations, routes])

  // All stations as columns (including empty ones)
  const columns = useMemo(() => {
    const cardList = Object.values(cards)
    return topoOrder
      .map((id) => stations[id])
      .filter(Boolean)
      .map((station) => ({
        stationId: station._id,
        station,
        lots: cardList.filter((c) => (c.bins[station._id]?.count ?? 0) > 0),
      }))
  }, [cards, stations, topoOrder])

  const totalCards = Object.values(cards).length

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Toolbar */}
      <div style={{
        padding:      `${size.sp3} ${size.sp6}`,
        borderBottom: `1px solid ${color.border}`,
        display:      'flex',
        alignItems:   'center',
        gap:          size.sp4,
        flexShrink:   0,
      }}>
        <span style={{ fontSize: 12, fontFamily: font.mono, color: color.textSecondary, letterSpacing: '0.1em' }}>
          LOTS
        </span>
        <span style={{ fontSize: 11, color: color.textDim }}>
          {totalCards} lot{totalCards !== 1 ? 's' : ''} · {columns.length} location{columns.length !== 1 ? 's' : ''}
        </span>
      </div>

      {columns.length === 0 ? (
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 12,
        }}>
          <span style={{ fontSize: 36, opacity: 0.15 }}>▤</span>
          <span style={{ fontFamily: font.mono, fontSize: 12, color: color.textDim, letterSpacing: '0.1em' }}>
            NO LOCATIONS YET
          </span>
          <span style={{ fontSize: 11, color: color.textDim }}>Add locations in Settings</span>
        </div>
      ) : (
        <div style={{
          flex:       1,
          display:    'flex',
          overflowX:  'auto',
          overflowY:  'hidden',
          padding:    size.sp4,
          gap:        size.sp4,
          alignItems: 'flex-start',
        }}>
          {columns.map(({ stationId, station, lots }) => (
            <KanbanColumn
              key={stationId}
              stationId={stationId}
              station={station}
              lots={lots}
              templates={templates}
              routes={routes}
              onCreateLot={() => setCreateStation(stationId)}
              onOpenDetail={(card) => setActiveDetail({ card, stationId })}
              onMoveLot={(card) => setActiveMove({ card, fromStationId: stationId })}
            />
          ))}
        </div>
      )}

      {createStation && (
        <CreateLotModal stationId={createStation} onClose={() => setCreateStation(null)} />
      )}
      {activeMove && (
        <MoveLotModal
          card={activeMove.card}
          fromStationId={activeMove.fromStationId}
          onClose={() => setActiveMove(null)}
        />
      )}
      {activeDetail && (
        <LotDetailModal
          card={activeDetail.card}
          onClose={() => setActiveDetail(null)}
          onMove={(card, fromStationId) => {
            setActiveDetail(null)
            setActiveMove({ card, fromStationId })
          }}
        />
      )}
    </div>
  )
}

// ─── Kanban column ────────────────────────────────────────────────────────────

interface ColumnProps {
  stationId:    string
  station:      import('../../models').Station
  lots:         Card[]
  templates:    Record<string, import('../../models').LotTemplate>
  routes:       Record<string, Route>
  onCreateLot:  () => void
  onOpenDetail: (card: Card) => void
  onMoveLot:    (card: Card) => void
}

function KanbanColumn({
  stationId, station, lots, templates, routes, onCreateLot, onOpenDetail, onMoveLot,
}: ColumnProps) {
  const totalUnits = lots.reduce((sum, c) => sum + (c.bins[stationId]?.count ?? 0), 0)
  const hasOutgoing = Object.values(routes).some((r) => r.load === stationId)
  const accentColor = station.color ?? color.bluePrimary

  const statusColors: Record<string, string> = {
    idle:    color.textDim,
    working: color.statusRunning,
    done:    color.statusWarning,
  }

  return (
    <div style={{
      width:        220,
      flexShrink:   0,
      background:   color.bgCard,
      border:       `1px solid ${color.border}`,
      borderTop:    `3px solid ${accentColor}`,
      borderRadius: size.radiusMd,
      display:      'flex',
      flexDirection:'column',
      maxHeight:    'calc(100vh - 140px)',
    }}>
      {/* Column header */}
      <div style={{
        padding:      `${size.sp3} ${size.sp4}`,
        borderBottom: `1px solid ${color.border}`,
        flexShrink:   0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 600, fontSize: 13, color: color.textPrimary }}>
            {station.name}
          </span>
          <span style={{
            background:   lots.length > 0 ? `${accentColor}22` : color.bgElevated,
            color:        lots.length > 0 ? accentColor : color.textDim,
            borderRadius: size.radiusFull,
            padding:      '1px 8px',
            fontSize:     11,
            fontFamily:   font.mono,
            fontWeight:   600,
          }}>
            {lots.length}
          </span>
        </div>
        {totalUnits > 0 && (
          <div style={{ fontSize: 10, color: color.textDim, marginTop: 2, fontFamily: font.mono }}>
            {totalUnits} unit{totalUnits !== 1 ? 's' : ''}
          </div>
        )}
      </div>

      {/* Lot cards */}
      <div style={{ flex: 1, overflowY: 'auto', padding: size.sp2, display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
        {lots.map((card) => {
          const tmpl = templates[card.lotTemplateId]
          const statusDot = statusColors[card.status] ?? color.textDim
          return (
            <div key={card._id} style={{ position: 'relative' }}>
              {/* Status indicator */}
              {card.status !== 'idle' && (
                <div style={{
                  position:  'absolute',
                  top:       6,
                  right:     6,
                  width:     6,
                  height:    6,
                  borderRadius: '50%',
                  background: statusDot,
                  zIndex:    1,
                }} />
              )}
              <LotCard
                card={card}
                stationId={stationId}
                template={tmpl}
                onClick={() => onOpenDetail(card)}
                onMove={hasOutgoing ? () => onMoveLot(card) : undefined}
              />
            </div>
          )
        })}
        {lots.length === 0 && (
          <div style={{
            flex:       1,
            display:    'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding:    size.sp5,
            fontSize:   11,
            color:      color.textDim,
            fontStyle:  'italic',
          }}>
            empty
          </div>
        )}
      </div>

      {/* Footer: create lot */}
      <div style={{ padding: size.sp2, borderTop: `1px solid ${color.border}`, flexShrink: 0 }}>
        <button
          onClick={onCreateLot}
          style={{
            width:        '100%',
            background:   'transparent',
            border:       `1px dashed ${color.border}`,
            borderRadius: size.radius,
            color:        color.textDim,
            cursor:       'pointer',
            fontSize:     11,
            padding:      '5px 0',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = color.textSecondary }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = color.textDim }}
        >
          + create lot
        </button>
      </div>
    </div>
  )
}
