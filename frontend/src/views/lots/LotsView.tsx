import React, { useMemo, useState } from 'react'
import { useCardsStore, useStationsStore, useProcessesStore } from '../../store'
import { color, font, size } from '../../theme/tokens'
import LotCard from '../../components/lots/LotCard'
import CreateLotModal from '../../components/lots/CreateLotModal'
import MoveLotModal from '../../components/lots/MoveLotModal'
import type { Card } from '../../models'

interface ActiveMove { card: Card; fromStationId: string }

export default function LotsView() {
  const cards     = useCardsStore((s) => s.cards)
  const stations  = useStationsStore((s) => s.stations)
  const templates = useProcessesStore((s) => s.lotTemplates)

  const [createStation, setCreateStation] = useState<string | null>(null)
  const [activeMove, setActiveMove]       = useState<ActiveMove | null>(null)

  // Build columns: one per station that has at least one lot, ordered by station name
  const columns = useMemo(() => {
    const cardList = Object.values(cards)
    // Gather stationIds that have lots
    const stationIds = new Set<string>()
    for (const card of cardList) {
      for (const [sid, bin] of Object.entries(card.bins)) {
        if (bin.count > 0) stationIds.add(sid)
      }
    }
    return [...stationIds]
      .map((id) => ({
        stationId: id,
        station:   stations[id],
        lots:      cardList.filter((c) => (c.bins[id]?.count ?? 0) > 0),
      }))
      .sort((a, b) => (a.station?.name ?? a.stationId).localeCompare(b.station?.name ?? b.stationId))
  }, [cards, stations])

  const isEmpty = columns.length === 0

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
          {Object.values(cards).length} cards · {columns.length} active stations
        </span>
      </div>

      {isEmpty ? (
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 12,
        }}>
          <span style={{ fontSize: 36, opacity: 0.15 }}>▤</span>
          <span style={{ fontFamily: font.mono, fontSize: 12, color: color.textDim, letterSpacing: '0.1em' }}>
            NO LOTS IN PROGRESS
          </span>
          <span style={{ fontSize: 11, color: color.textDim }}>
            Create a lot from the Map view by selecting a station
          </span>
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
              stationName={station?.name ?? stationId}
              lots={lots}
              templates={templates}
              onCreateLot={() => setCreateStation(stationId)}
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
    </div>
  )
}

interface ColumnProps {
  stationId:   string
  stationName: string
  lots:        Card[]
  templates:   Record<string, import('../../models').LotTemplate>
  onCreateLot: () => void
  onMoveLot:   (card: Card) => void
}

function KanbanColumn({ stationId, stationName, lots, templates, onCreateLot, onMoveLot }: ColumnProps) {
  const totalUnits = lots.reduce((sum, c) => sum + (c.bins[stationId]?.count ?? 0), 0)

  return (
    <div style={{
      width:        220,
      flexShrink:   0,
      background:   color.bgCard,
      border:       `1px solid ${color.border}`,
      borderRadius: size.radiusMd,
      display:      'flex',
      flexDirection:'column',
      maxHeight:    'calc(100vh - 140px)',
    }}>
      {/* Column header */}
      <div style={{
        padding:      `${size.sp3} ${size.sp3} ${size.sp2}`,
        borderBottom: `1px solid ${color.border}`,
        display:      'flex',
        alignItems:   'center',
        gap:          size.sp2,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize:     12,
            fontWeight:   600,
            color:        color.textPrimary,
            overflow:     'hidden',
            textOverflow: 'ellipsis',
            whiteSpace:   'nowrap',
          }}>
            {stationName}
          </div>
          <div style={{ fontSize: 10, color: color.textDim, fontFamily: font.mono }}>
            {lots.length} card{lots.length !== 1 ? 's' : ''} · {totalUnits} unit{totalUnits !== 1 ? 's' : ''}
          </div>
        </div>
        <button
          onClick={onCreateLot}
          title="Create lot at this station"
          style={{
            width:        20,
            height:       20,
            borderRadius: '50%',
            background:   color.bgElevated,
            border:       `1px solid ${color.border}`,
            color:        color.textSecondary,
            fontSize:     14,
            lineHeight:   '18px',
            cursor:       'pointer',
            flexShrink:   0,
            display:      'flex',
            alignItems:   'center',
            justifyContent: 'center',
            padding:      0,
          }}
        >
          +
        </button>
      </div>

      {/* Cards */}
      <div style={{
        overflowY: 'auto',
        padding:   size.sp2,
        display:   'flex',
        flexDirection: 'column',
        gap:       size.sp2,
      }}>
        {lots.length === 0 ? (
          <div style={{ fontSize: 10, color: color.textDim, padding: size.sp2, textAlign: 'center' }}>
            empty
          </div>
        ) : (
          lots.map((card) => (
            <LotCard
              key={card._id}
              card={card}
              template={templates[card.lotTemplateId]}
              stationId={stationId}
              onClick={() => onMoveLot(card)}
            />
          ))
        )}
      </div>
    </div>
  )
}
