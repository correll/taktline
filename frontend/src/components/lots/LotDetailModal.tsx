import React, { useEffect, useState } from 'react'
import { useCardsStore, useStationsStore, useProcessesStore } from '../../store'
import { cardsApi, type CardEvent } from '../../api/cards.api'
import { color, font, size, shadow } from '../../theme/tokens'
import type { Card } from '../../models'
import { formatDistanceToNow } from 'date-fns'

interface Props {
  card:     Card
  onClose:  () => void
  onMove?:  (card: Card, fromStationId: string) => void
}

export default function LotDetailModal({ card: initialCard, onClose, onMove }: Props) {
  const stations   = useStationsStore((s) => s.stations)
  const templates  = useProcessesStore((s) => s.lotTemplates)
  const processes  = useProcessesStore((s) => s.processes)
  const updateCard = useCardsStore((s) => s.update)
  const removeCard = useCardsStore((s) => s.remove)
  // Always read live card from store so flag/status changes appear immediately
  const liveCards  = useCardsStore((s) => s.cards)
  const card       = liveCards[initialCard._id] ?? initialCard

  const [events,      setEvents]      = useState<CardEvent[]>([])
  const [loadingEvts, setLoadingEvts] = useState(true)
  const [description, setDescription] = useState(initialCard.description)
  const [saving,      setSaving]      = useState(false)
  const [confirmDel,  setConfirmDel]  = useState(false)
  const [tab,         setTab]         = useState<'info' | 'history'>('info')

  const template = templates[card.lotTemplateId]
  const process  = processes[card.processId]

  useEffect(() => {
    cardsApi.getEvents(card._id)
      .then(setEvents)
      .catch(() => setEvents([]))
      .finally(() => setLoadingEvts(false))
  }, [card._id])

  const handleToggleFlag = async () => {
    setSaving(true)
    try { await updateCard(card._id, { flagged: !card.flagged }) }
    finally { setSaving(false) }
  }

  const handleSaveDesc = async () => {
    setSaving(true)
    try { await updateCard(card._id, { description }) }
    finally { setSaving(false) }
  }

  const handleDelete = async () => {
    await removeCard(card._id)
    onClose()
  }

  const activeBins = Object.entries(card.bins).filter(([, b]) => b.count > 0)

  const TAB_STYLE = (active: boolean): React.CSSProperties => ({
    padding:      `${size.sp1} ${size.sp3}`,
    borderRadius: size.radius,
    background:   active ? color.bgElevated : 'transparent',
    border:       active ? `1px solid ${color.border}` : '1px solid transparent',
    color:        active ? color.textPrimary : color.textSecondary,
    cursor:       'pointer',
    fontSize:     11,
    fontFamily:   font.sans,
  })

  return (
    <div
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(6,14,30,0.78)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background:    color.bgPanel,
        border:        `1px solid ${color.border}`,
        borderRadius:  size.radiusMd,
        width:         500,
        maxHeight:     '85vh',
        overflowY:     'auto',
        boxShadow:     shadow.lg,
        display:       'flex',
        flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{
          padding:      `${size.sp4} ${size.sp5}`,
          borderBottom: `1px solid ${color.border}`,
          display:      'flex',
          alignItems:   'flex-start',
          gap:          size.sp3,
        }}>
          {/* Colour swatch */}
          <div style={{
            width: 10, height: 10, borderRadius: '50%', marginTop: 4, flexShrink: 0,
            background: template?.color ?? color.bluePrimary,
          }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>
              Lot {card.lotNum != null ? `#${card.lotNum}` : card._id.slice(-6).toUpperCase()}
            </div>
            <div style={{ fontSize: 11, color: color.textSecondary, marginTop: 2 }}>
              {template?.name ?? 'Unknown template'}
              {process && <span style={{ color: color.textDim }}> · {process.name}</span>}
            </div>
          </div>
          {card.flagged && (
            <span style={{
              fontSize: 10, fontFamily: font.mono, letterSpacing: '0.08em',
              color: color.statusWarning, background: `${color.statusWarning}18`,
              border: `1px solid ${color.statusWarning}40`, borderRadius: size.radiusFull,
              padding: '2px 8px', flexShrink: 0,
            }}>FLAGGED</span>
          )}
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: color.textDim, cursor: 'pointer', fontSize: 18, lineHeight: 1, flexShrink: 0 }}
          >×</button>
        </div>

        {/* Tabs */}
        <div style={{
          padding:      `${size.sp2} ${size.sp5}`,
          borderBottom: `1px solid ${color.border}`,
          display:      'flex',
          gap:          size.sp1,
        }}>
          <button style={TAB_STYLE(tab === 'info')}    onClick={() => setTab('info')}>Info</button>
          <button style={TAB_STYLE(tab === 'history')} onClick={() => setTab('history')}>
            History {events.length > 0 ? `(${events.length})` : ''}
          </button>
        </div>

        <div style={{ padding: size.sp5, display: 'flex', flexDirection: 'column', gap: size.sp4 }}>
          {tab === 'info' && (
            <>
              {/* Stats row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: size.sp3 }}>
                <Stat label="Total Qty"   value={card.totalQuantity} />
                <Stat label="Bins"        value={activeBins.length} />
                <Stat label="Lot #"       value={card.lotNum != null ? String(card.lotNum) : '—'} />
              </div>

              {/* Bins */}
              {activeBins.length > 0 && (
                <Section label="CURRENT LOCATION">
                  {activeBins.map(([sid, bin]) => (
                    <div key={sid} style={{
                      display:        'flex',
                      alignItems:     'center',
                      justifyContent: 'space-between',
                      padding:        `${size.sp2} 0`,
                      borderBottom:   `1px solid ${color.border}`,
                    }}>
                      <span style={{ fontSize: 12, color: color.textPrimary }}>
                        {stations[sid]?.name ?? sid}
                      </span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: size.sp2 }}>
                        <span style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono }}>
                          {bin.count} unit{bin.count !== 1 ? 's' : ''}
                        </span>
                        {onMove && (
                          <button
                            onClick={() => { onClose(); onMove(card, sid) }}
                            style={{
                              background: 'none', border: `1px solid ${color.border}`,
                              borderRadius: size.radius, color: color.textSecondary,
                              cursor: 'pointer', fontSize: 10, padding: '2px 8px',
                            }}
                          >
                            Move
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </Section>
              )}

              {/* Custom fields */}
              {template?.fields && template.fields.length > 0 && (
                <Section label="FIELDS">
                  {template.fields.map((fd) => (
                    <div key={fd.key} style={{
                      display:        'flex',
                      justifyContent: 'space-between',
                      padding:        `${size.sp2} 0`,
                      borderBottom:   `1px solid ${color.border}`,
                      fontSize:       12,
                    }}>
                      <span style={{ color: color.textSecondary }}>{fd.label}</span>
                      <span style={{ color: color.textPrimary, fontFamily: fd.type === 'number' ? font.mono : undefined }}>
                        {String(card.fields[fd.key] ?? '—')}
                      </span>
                    </div>
                  ))}
                </Section>
              )}

              {/* Description */}
              <Section label="DESCRIPTION">
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: color.bgCard, border: `1px solid ${color.border}`,
                    borderRadius: size.radius, color: color.textPrimary,
                    padding: '6px 10px', fontSize: 12, resize: 'vertical', outline: 'none',
                  }}
                />
                {description !== card.description && (
                  <button
                    onClick={handleSaveDesc}
                    disabled={saving}
                    style={{
                      marginTop: size.sp2,
                      padding: '4px 14px',
                      background: color.bluePrimary, border: 'none',
                      borderRadius: size.radius, color: color.white,
                      cursor: 'pointer', fontSize: 11, fontWeight: 600,
                    }}
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                )}
              </Section>

              {/* Actions */}
              <div style={{ display: 'flex', gap: size.sp2, paddingTop: size.sp2 }}>
                <button
                  onClick={handleToggleFlag}
                  disabled={saving}
                  style={{
                    flex: 1,
                    padding: `${size.sp2} 0`,
                    background: card.flagged ? `${color.statusWarning}18` : 'transparent',
                    border: `1px solid ${card.flagged ? color.statusWarning : color.border}40`,
                    borderRadius: size.radius,
                    color: card.flagged ? color.statusWarning : color.textSecondary,
                    cursor: 'pointer', fontSize: 12,
                  }}
                >
                  {card.flagged ? 'Unflag' : 'Flag'}
                </button>
                {confirmDel ? (
                  <>
                    <button
                      onClick={() => setConfirmDel(false)}
                      style={{
                        padding: `${size.sp2} ${size.sp4}`, background: 'transparent',
                        border: `1px solid ${color.border}`, borderRadius: size.radius,
                        color: color.textSecondary, cursor: 'pointer', fontSize: 12,
                      }}
                    >Cancel</button>
                    <button
                      onClick={handleDelete}
                      style={{
                        padding: `${size.sp2} ${size.sp4}`, background: 'transparent',
                        border: `1px solid ${color.statusFault}60`, borderRadius: size.radius,
                        color: color.statusFault, cursor: 'pointer', fontSize: 12, fontWeight: 600,
                      }}
                    >Confirm Delete</button>
                  </>
                ) : (
                  <button
                    onClick={() => setConfirmDel(true)}
                    style={{
                      padding: `${size.sp2} ${size.sp4}`, background: 'transparent',
                      border: `1px solid ${color.statusFault}40`, borderRadius: size.radius,
                      color: color.statusFault, cursor: 'pointer', fontSize: 12,
                    }}
                  >Delete Lot</button>
                )}
              </div>
            </>
          )}

          {tab === 'history' && (
            <div>
              {loadingEvts ? (
                <div style={{ fontSize: 11, color: color.textDim }}>Loading…</div>
              ) : events.length === 0 ? (
                <div style={{ fontSize: 11, color: color.textDim }}>No events yet.</div>
              ) : (
                [...events].reverse().map((evt, i) => (
                  <EventRow key={evt._id ?? i} evt={evt} stations={stations} />
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        fontSize: 9, fontFamily: font.mono, letterSpacing: '0.14em',
        color: color.textDim, marginBottom: size.sp2,
      }}>
        {label}
      </div>
      {children}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{
      background: color.bgCard, border: `1px solid ${color.border}`,
      borderRadius: size.radius, padding: `${size.sp2} ${size.sp3}`,
    }}>
      <div style={{ fontSize: 9, color: color.textDim, fontFamily: font.mono, marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, fontFamily: font.mono, color: color.textPrimary }}>{value}</div>
    </div>
  )
}

function EventRow({ evt, stations }: { evt: CardEvent; stations: Record<string, import('../../models').Station> }) {
  const ICONS: Record<string, string> = {
    created: '✦', moved: '→', flagged: '⚑', unflagged: '⚐', updated: '✎', deleted: '✕',
  }
  const COLORS: Record<string, string> = {
    created: color.statusRunning, moved: color.blueBright,
    flagged: color.statusWarning, unflagged: color.textSecondary,
    updated: color.textSecondary, deleted: color.statusFault,
  }
  const icon  = ICONS[evt.type]  ?? '·'
  const col   = COLORS[evt.type] ?? color.textDim

  const stationName = (id: string | null) => id ? (stations[id]?.name ?? id) : null

  return (
    <div style={{
      display:      'flex',
      gap:          size.sp3,
      padding:      `${size.sp2} 0`,
      borderBottom: `1px solid ${color.border}`,
      alignItems:   'flex-start',
    }}>
      <span style={{ color: col, fontFamily: font.mono, fontSize: 12, marginTop: 1, flexShrink: 0 }}>{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, color: color.textPrimary }}>
          {evt.type.charAt(0).toUpperCase() + evt.type.slice(1)}
          {evt.type === 'moved' && evt.fromStation && evt.toStation && (
            <span style={{ color: color.textSecondary }}>
              {' '}{stationName(evt.fromStation)} → {stationName(evt.toStation)}
              {evt.quantity != null && <span style={{ color: color.textDim }}> ({evt.quantity} units)</span>}
            </span>
          )}
          {evt.note && <span style={{ color: color.textDim }}> · {evt.note}</span>}
        </div>
        <div style={{ fontSize: 10, color: color.textDim, marginTop: 1 }}>
          {formatDistanceToNow(new Date(evt.timestamp), { addSuffix: true })}
        </div>
      </div>
    </div>
  )
}
