import React, { useCallback, useState } from 'react'
import { useStationsStore, useProcessesStore, useCardsStore, useMachinesStore } from '../../store'
import { stationsApi } from '../../api/stations.api'
import { color, font, size, shadow } from '../../theme/tokens'
import { STATUS_CSS } from './mapColors'
import LotCard from '../lots/LotCard'
import CreateLotModal from '../lots/CreateLotModal'
import MoveLotModal from '../lots/MoveLotModal'
import type { Card, MachineStatus } from '../../models'

interface Props {
  stationId: string
  onClose:   () => void
}

export default function StationPanel({ stationId, onClose }: Props) {
  const station     = useStationsStore((s) => s.stations[stationId])
  const machineState= useMachinesStore((s) => s.states[stationId])
  const allCards    = useCardsStore((s) => s.cards)
  const templates   = useProcessesStore((s) => s.lotTemplates)

  const [showCreate, setShowCreate] = useState(false)
  const [moveCard, setMoveCard]     = useState<Card | null>(null)

  const cards = Object.values(allCards).filter(
    (c) => (c.bins[stationId]?.count ?? 0) > 0
  )

  const status     = (machineState?.status ?? 'none') as MachineStatus | 'none'
  const statusColor = STATUS_CSS[status]
  const hasAdapter  = !!station?.adapterType

  const sendCommand = useCallback(async (type: string) => {
    try {
      await stationsApi.sendCommand(stationId, { type })
    } catch { /* adapter may not be connected */ }
  }, [stationId])

  if (!station) return null

  return (
    <aside style={{
      width:       size.sidebarWidth,
      flexShrink:  0,
      background:  color.bgPanel,
      borderLeft:  `1px solid ${color.border}`,
      display:     'flex',
      flexDirection: 'column',
      overflow:    'hidden',
      boxShadow:   shadow.lg,
    }}>
      {/* Header */}
      <div style={{
        padding:     `${size.sp4} ${size.sp4} ${size.sp3}`,
        borderBottom:`1px solid ${color.border}`,
        display:     'flex',
        alignItems:  'flex-start',
        gap:         size.sp3,
      }}>
        <span
          className="status-dot"
          style={{
            background: statusColor,
            boxShadow:  status === 'running' ? `0 0 6px ${statusColor}` : undefined,
            marginTop: 3,
          }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }} className="truncate">
            {station.name}
          </div>
          {station.description && (
            <div style={{ fontSize: 11, color: color.textSecondary, marginTop: 2 }}>
              {station.description}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          style={{
            background:  'none',
            border:      'none',
            color:       color.textDim,
            cursor:      'pointer',
            fontSize:    16,
            lineHeight:  1,
            padding:     2,
            flexShrink:  0,
          }}
        >
          ×
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: size.sp4, display: 'flex', flexDirection: 'column', gap: size.sp4 }}>

        {/* Machine status */}
        <Section label="MACHINE">
          <div style={{ display: 'flex', alignItems: 'center', gap: size.sp2, marginBottom: size.sp3 }}>
            <StatusBadge status={status} />
            {machineState?.message && (
              <span style={{ fontSize: 11, color: color.textSecondary }}>{machineState.message}</span>
            )}
          </div>

          {/* Metrics grid */}
          {machineState && Object.values(machineState.metrics).length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: size.sp2 }}>
              {Object.values(machineState.metrics).map((m, i) => (
                <div key={i} style={{
                  background:   color.bgCard,
                  border:       `1px solid ${color.border}`,
                  borderRadius: size.radius,
                  padding:      `${size.sp2} ${size.sp3}`,
                }}>
                  <div style={{ fontSize: 10, color: color.textSecondary, marginBottom: 2 }}>{m.label}</div>
                  <div style={{ fontFamily: font.mono, fontSize: 14, color: color.textPrimary, fontWeight: 500 }}>
                    {typeof m.value === 'number' ? m.value.toLocaleString() : m.value}
                    {m.unit && (
                      <span style={{ fontSize: 10, color: color.textSecondary, marginLeft: 4 }}>{m.unit}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {!hasAdapter && (
            <div style={{ fontSize: 11, color: color.textDim, fontStyle: 'italic' }}>
              No hardware adapter configured
            </div>
          )}
        </Section>

        {/* Controls */}
        {hasAdapter && (
          <Section label="CONTROLS">
            <div style={{ display: 'flex', gap: size.sp2 }}>
              <Btn
                label="START"
                active={status !== 'running'}
                color={color.statusRunning}
                onClick={() => sendCommand('start')}
              />
              <Btn
                label="STOP"
                active={status === 'running'}
                color={color.statusFault}
                onClick={() => sendCommand('stop')}
              />
            </div>
          </Section>
        )}

        {/* Lot cards at this station */}
        <Section
          label={`LOTS (${cards.length})`}
          action={
            <button
              onClick={() => setShowCreate(true)}
              style={{
                background: 'none', border: 'none',
                color: color.textSecondary, cursor: 'pointer',
                fontSize: 16, lineHeight: 1, padding: '0 2px',
              }}
              title="Create lot at this station"
            >
              +
            </button>
          }
        >
          {cards.length === 0 ? (
            <div style={{ fontSize: 11, color: color.textDim }}>
              No lots here — press + to create one
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
              {cards.map((card) => (
                <LotCard
                  key={card._id}
                  card={card}
                  template={templates[card.lotTemplateId]}
                  stationId={stationId}
                  onClick={() => setMoveCard(card)}
                />
              ))}
            </div>
          )}
        </Section>

      </div>

      {showCreate && (
        <CreateLotModal stationId={stationId} onClose={() => setShowCreate(false)} />
      )}
      {moveCard && (
        <MoveLotModal card={moveCard} fromStationId={stationId} onClose={() => setMoveCard(null)} />
      )}
    </aside>
  )
}

function Section({ label, children, action }: { label: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div>
      <div style={{
        display:       'flex',
        alignItems:    'center',
        marginBottom:  size.sp2,
      }}>
        <span style={{
          fontSize:      9,
          fontFamily:    font.mono,
          letterSpacing: '0.14em',
          color:         color.textDim,
          flex:          1,
        }}>
          {label}
        </span>
        {action}
      </div>
      {children}
    </div>
  )
}

function StatusBadge({ status }: { status: MachineStatus | 'none' }) {
  const css = STATUS_CSS[status]
  const bg  = css + '26'   // ~15% opacity
  return (
    <span style={{
      padding:      '2px 8px',
      borderRadius: size.radiusFull,
      background:   bg,
      border:       `1px solid ${css}40`,
      color:        css,
      fontSize:     10,
      fontFamily:   font.mono,
      letterSpacing:'0.1em',
      fontWeight:   600,
    }}>
      {status.toUpperCase()}
    </span>
  )
}

function Btn({ label, active, color: col, onClick }: {
  label: string; active: boolean; color: string; onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex:         1,
        padding:      `${size.sp2} 0`,
        background:   active ? col + '20' : 'transparent',
        border:       `1px solid ${active ? col : color.border}`,
        borderRadius: size.radius,
        color:        active ? col : color.textDim,
        fontFamily:   font.mono,
        fontSize:     11,
        letterSpacing:'0.1em',
        cursor:       'pointer',
        transition:   'all 0.15s ease',
      }}
    >
      {label}
    </button>
  )
}
