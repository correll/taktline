import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCardsStore, useStationsStore, useProcessesStore } from '../../store'
import { color, font, size } from '../../theme/tokens'
import LotCard from '../../components/lots/LotCard'
import CreateLotModal from '../../components/lots/CreateLotModal'
import MoveLotModal from '../../components/lots/MoveLotModal'
import LotDetailModal from '../../components/lots/LotDetailModal'
import { mergeNodes } from '../../domain/graph'
import { mergeApi, type MergePreview } from '../../api/merge.api'
import { cardsApi } from '../../api/cards.api'
import type { Card, Route } from '../../models'

interface ActiveMove   { card: Card; fromStationId: string }
interface ActiveDetail { card: Card; stationId: string }
interface DragState    { cardId: string; fromStationId: string }

// ─── Routing helper ───────────────────────────────────────────────────────────
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
    if ((inDegree[sid] ?? 0) > 1) continue
    for (const next of outgoing[sid] ?? []) {
      if (!visited.has(next)) queue.push(next)
    }
  }

  return [...valid]
}

// ─── Lock icon ────────────────────────────────────────────────────────────────
function LockIcon({ open }: { open: boolean }) {
  return (
    <svg width="12" height="13" viewBox="0 0 12 13" fill="none" aria-hidden="true">
      <rect x="1" y="5.5" width="10" height="7" rx="1.5" fill="currentColor" />
      {open
        ? <path d="M3.5 5.5V3.5a2.5 2.5 0 0 1 5 0" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        : <path d="M3.5 5.5V3.5a2.5 2.5 0 0 1 5 0v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      }
    </svg>
  )
}

// ─── View ─────────────────────────────────────────────────────────────────────

export default function LotsView() {
  const cards      = useCardsStore((s) => s.cards)
  const stations   = useStationsStore((s) => s.stations)
  const templates  = useProcessesStore((s) => s.lotTemplates)
  const routes     = useProcessesStore((s) => s.routes)
  const upsertCard = useCardsStore((s) => s.upsert)

  const [createStation, setCreateStation] = useState<string | null>(null)
  const [activeMove,    setActiveMove]    = useState<ActiveMove | null>(null)
  const [activeDetail,  setActiveDetail]  = useState<ActiveDetail | null>(null)

  // ─── Drag-and-drop state ───────────────────────────────────────────────────
  const [unlocked, setUnlocked] = useState(false)
  const [dragging, setDragging] = useState<DragState | null>(null)

  const validDropTargets = useMemo(
    () => dragging
      ? new Set(getValidDestinations(dragging.fromStationId, routes))
      : new Set<string>(),
    [dragging, routes],
  )

  const handleDrop = useCallback(async (toStationId: string) => {
    if (!dragging || !validDropTargets.has(toStationId)) return
    const card = cards[dragging.cardId]
    if (!card) return
    const qty = card.bins[dragging.fromStationId]?.count ?? 0
    if (qty <= 0) return
    // Clear drag state immediately so UI resets even if the API call takes time
    setDragging(null)
    try {
      const updated = await cardsApi.move(dragging.cardId, dragging.fromStationId, toStationId, qty)
      upsertCard(updated)
    } catch (e) {
      console.error('Drag-move failed:', e)
    }
  }, [dragging, validDropTargets, cards, upsertCard])

  // ─── Merge nodes ──────────────────────────────────────────────────────────

  const mergeNodeSet = useMemo(
    () => mergeNodes(Object.values(routes) as { load: string; unload: string }[]),
    [routes],
  )

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
    for (const id of Object.keys(stations)) {
      if (!order.includes(id)) order.push(id)
    }
    return order
  }, [stations, routes])

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
  const isDragging = dragging !== null

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

        {/* Lock / unlock drag mode */}
        <button
          onClick={() => { setUnlocked((u) => !u); setDragging(null) }}
          style={{
            marginLeft:   'auto',
            display:      'flex',
            alignItems:   'center',
            gap:          5,
            padding:      '4px 10px',
            background:   unlocked ? '#F59E0B18' : 'transparent',
            border:       `1px solid ${unlocked ? '#F59E0B60' : color.border}`,
            borderRadius: size.radius,
            color:        unlocked ? '#F59E0B' : color.textSecondary,
            cursor:       'pointer',
            fontSize:     11,
            fontFamily:   font.mono,
            letterSpacing:'0.06em',
            transition:   'all 0.15s ease',
          }}
        >
          <LockIcon open={unlocked} />
          {unlocked ? 'LOCK' : 'DRAG'}
        </button>
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
          {columns.map(({ stationId, station, lots }) => {
            const isDropTarget = validDropTargets.has(stationId)
            const dragProps = {
              unlocked,
              isDragging,
              isDropTarget,
              onDragStart: (cardId: string) => setDragging({ cardId, fromStationId: stationId }),
              onDragEnd:   () => setDragging(null),
              onDrop:      () => handleDrop(stationId),
            }
            return mergeNodeSet.has(stationId) ? (
              <MergeColumn
                key={stationId}
                stationId={stationId}
                station={station}
                lots={lots}
                templates={templates}
                routes={routes}
                onOpenDetail={(card) => setActiveDetail({ card, stationId })}
                onMoveLot={(card) => setActiveMove({ card, fromStationId: stationId })}
                {...dragProps}
              />
            ) : (
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
                {...dragProps}
              />
            )
          })}
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

// ─── Shared column props ──────────────────────────────────────────────────────

interface ColumnProps {
  stationId:    string
  station:      import('../../models').Station
  lots:         Card[]
  templates:    Record<string, import('../../models').LotTemplate>
  routes:       Record<string, Route>
  onOpenDetail: (card: Card) => void
  onMoveLot:    (card: Card) => void
  // Drag-and-drop
  unlocked:     boolean
  isDragging:   boolean
  isDropTarget: boolean
  onDragStart:  (cardId: string) => void
  onDragEnd:    () => void
  onDrop:       () => void
}

// ─── Drop-zone styling helper ─────────────────────────────────────────────────

function columnBorderTop(accentColor: string, isDragging: boolean, isDropTarget: boolean, hovering: boolean): string {
  if (isDragging && isDropTarget) return `3px solid #10B981`
  return `3px solid ${accentColor}`
}

function columnOpacity(isDragging: boolean, isDropTarget: boolean): number {
  if (isDragging && !isDropTarget) return 0.45
  return 1
}

function columnBackground(isDragging: boolean, isDropTarget: boolean, hovering: boolean, base: string): string {
  if (isDragging && isDropTarget && hovering) return '#10B98110'
  return base
}

// ─── Standard Kanban column ───────────────────────────────────────────────────

interface KanbanColumnProps extends ColumnProps {
  onCreateLot: () => void
}

function KanbanColumn({
  stationId, station, lots, templates, routes,
  onCreateLot, onOpenDetail, onMoveLot,
  unlocked, isDragging, isDropTarget, onDragStart, onDragEnd, onDrop,
}: KanbanColumnProps) {
  const [hovering,   setHovering]   = useState(false)
  const totalUnits  = lots.reduce((sum, c) => sum + (c.bins[stationId]?.count ?? 0), 0)
  const hasOutgoing = Object.values(routes).some((r) => r.load  === stationId)
  const hasIncoming = Object.values(routes).some((r) => r.unload === stationId)
  const accentColor = station.color ?? color.bluePrimary

  return (
    <div
      style={{
        width:         220,
        flexShrink:    0,
        background:    columnBackground(isDragging, isDropTarget, hovering, color.bgCard),
        border:        `1px solid ${isDragging && isDropTarget ? '#10B98150' : color.border}`,
        borderTop:     columnBorderTop(accentColor, isDragging, isDropTarget, hovering),
        borderRadius:  size.radiusMd,
        display:       'flex',
        flexDirection: 'column',
        maxHeight:     'calc(100vh - 140px)',
        opacity:       columnOpacity(isDragging, isDropTarget),
        transition:    'opacity 0.15s ease, border-color 0.15s ease, background 0.15s ease',
      }}
      onDragOver={(e) => {
        if (!isDropTarget) return
        e.preventDefault()
        e.dataTransfer.dropEffect = 'move'
        setHovering(true)
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setHovering(false)
      }}
      onDrop={(e) => {
        e.preventDefault()
        setHovering(false)
        onDrop()
      }}
    >
      {/* Column header */}
      <div style={{ padding: `${size.sp3} ${size.sp4}`, borderBottom: `1px solid ${color.border}`, flexShrink: 0 }}>
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
        {lots.map((card) => (
          <div
            key={card._id}
            draggable={unlocked}
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = 'move'
              e.dataTransfer.setData('text/plain', card._id)
              onDragStart(card._id)
            }}
            onDragEnd={onDragEnd}
            style={{ cursor: unlocked ? 'grab' : 'default' }}
          >
            <LotCard
              card={card}
              stationId={stationId}
              template={templates[card.lotTemplateId]}
              onClick={unlocked ? undefined : () => onOpenDetail(card)}
              onMove={hasOutgoing ? () => onMoveLot(card) : undefined}
            />
          </div>
        ))}
        {lots.length === 0 && (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: size.sp5, fontSize: 11, color: color.textDim, fontStyle: 'italic',
          }}>
            {isDragging && isDropTarget ? 'Drop here' : 'empty'}
          </div>
        )}
      </div>

      {/* Footer: create lot — only source nodes (no incoming routes) can originate lots */}
      {!unlocked && !hasIncoming && (
        <div style={{ padding: size.sp2, borderTop: `1px solid ${color.border}`, flexShrink: 0 }}>
          <button
            onClick={onCreateLot}
            style={{
              width: '100%', background: 'transparent',
              border: `1px dashed ${color.border}`, borderRadius: size.radius,
              color: color.textDim, cursor: 'pointer', fontSize: 11, padding: '5px 0',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = color.textSecondary }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = color.textDim }}
          >
            + create lot
          </button>
        </div>
      )}
    </div>
  )
}

// ─── Merge station column ─────────────────────────────────────────────────────

function MergeColumn({
  stationId, station, lots, templates, routes, onOpenDetail, onMoveLot,
  unlocked, isDragging, isDropTarget, onDragStart, onDragEnd, onDrop,
}: ColumnProps) {
  const fetchAll    = useCardsStore((s) => s.fetchAll)
  const navigate    = useNavigate()
  const accentColor = station.color ?? '#8B5CF6'
  const hasOutgoing = Object.values(routes).some((r) => r.load === stationId)

  const [hovering,   setHovering]   = useState(false)
  const [preview,    setPreview]    = useState<MergePreview | null>(null)
  const [merging,    setMerging]    = useState(false)
  const [mergeError, setMergeError] = useState<string | null>(null)

  const lotsKey = useMemo(
    () => lots.map((c) => `${c._id}:${c.bins[stationId]?.count ?? 0}`).join('|'),
    [lots, stationId],
  )

  const refreshPreview = useCallback(() => {
    mergeApi.preview(stationId).then(setPreview).catch(console.error)
  }, [stationId])

  useEffect(() => { refreshPreview() }, [refreshPreview, lotsKey])

  const handleMerge = async () => {
    setMerging(true)
    setMergeError(null)
    try {
      await mergeApi.perform(stationId)
      await fetchAll()
      refreshPreview()
    } catch (e) {
      setMergeError(String(e))
    } finally {
      setMerging(false)
    }
  }

  const canMerge   = (preview?.assembliesPossible ?? 0) > 0
  const noTemplate = preview?.isMergeStation && !preview.hasAssemblyTemplate

  return (
    <div
      style={{
        width:         220,
        flexShrink:    0,
        background:    columnBackground(isDragging, isDropTarget, hovering, color.bgCard),
        border:        `1px solid ${isDragging && isDropTarget ? '#10B98150' : color.border}`,
        borderTop:     columnBorderTop(accentColor, isDragging, isDropTarget, hovering),
        borderRadius:  size.radiusMd,
        display:       'flex',
        flexDirection: 'column',
        maxHeight:     'calc(100vh - 140px)',
        opacity:       columnOpacity(isDragging, isDropTarget),
        transition:    'opacity 0.15s ease, border-color 0.15s ease, background 0.15s ease',
      }}
      onDragOver={(e) => {
        if (!isDropTarget) return
        e.preventDefault()
        e.dataTransfer.dropEffect = 'move'
        setHovering(true)
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setHovering(false)
      }}
      onDrop={(e) => {
        e.preventDefault()
        setHovering(false)
        onDrop()
      }}
    >
      {/* Header */}
      <div style={{ padding: `${size.sp3} ${size.sp4}`, borderBottom: `1px solid ${color.border}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 4 }}>
          <span style={{
            fontWeight: 600, fontSize: 13, color: color.textPrimary,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {station.name}
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
            <span style={{
              fontSize: 8, fontFamily: font.mono, letterSpacing: '0.08em',
              color: '#8B5CF6', background: '#8B5CF620', border: '1px solid #8B5CF640',
              borderRadius: size.radiusFull, padding: '1px 5px',
            }}>
              MERGE
            </span>
            <span style={{
              background:   lots.length > 0 ? `${accentColor}22` : color.bgElevated,
              color:        lots.length > 0 ? accentColor : color.textDim,
              borderRadius: size.radiusFull, padding: '1px 8px',
              fontSize: 11, fontFamily: font.mono, fontWeight: 600,
            }}>
              {lots.length}
            </span>
          </div>
        </div>

        {/* Requirements summary bars */}
        {preview?.isMergeStation && preview.requirements.length > 0 && (
          <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {preview.requirements.map((req) => (
              <div key={req.routeId} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ flex: 1, height: 3, borderRadius: 2, background: color.bgElevated, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%',
                    width: `${Math.min(100, (req.canMake / Math.max(1, preview.assembliesPossible || req.canMake)) * 100)}%`,
                    background: req.availableUnits >= req.requiredPerAssembly ? '#10B981' : color.textDim,
                    borderRadius: 2,
                  }} />
                </div>
                <span style={{ fontSize: 9, fontFamily: font.mono, color: color.textDim, flexShrink: 0 }}>
                  {req.availableUnits}/{req.requiredPerAssembly}×
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Missing template error */}
      {noTemplate && (
        <div style={{
          margin: size.sp2, padding: `${size.sp2} ${size.sp3}`,
          background: '#EF444415', border: `1px solid #EF444440`,
          borderRadius: size.radius, fontSize: 11, color: '#EF4444', lineHeight: 1.4,
        }}>
          No assembly template.{' '}
          <button
            onClick={() => navigate(`/settings?tab=templates&station=${stationId}`)}
            style={{
              color: color.bluePrimary, background: 'none', border: 'none',
              cursor: 'pointer', padding: 0, fontSize: 11, textDecoration: 'underline',
            }}
          >
            Create one
          </button>
        </div>
      )}

      {/* Merge ready banner */}
      {canMerge && (
        <div style={{
          margin: `${size.sp2} ${size.sp2} 0`,
          padding: `${size.sp2} ${size.sp3}`,
          background: '#10B98115', border: `1px solid #10B98140`,
          borderRadius: size.radius,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: size.sp2,
        }}>
          <span style={{ fontSize: 11, color: '#10B981', fontFamily: font.mono }}>
            {preview!.assembliesPossible}× ready
          </span>
          <button
            onClick={handleMerge}
            disabled={merging}
            style={{
              background: '#10B981', color: '#fff', border: 'none',
              borderRadius: size.radius, padding: '3px 10px',
              fontSize: 11, fontFamily: font.mono,
              cursor: merging ? 'wait' : 'pointer', opacity: merging ? 0.7 : 1,
            }}
          >
            {merging ? '…' : 'Merge'}
          </button>
        </div>
      )}

      {mergeError && (
        <div style={{ margin: `${size.sp1} ${size.sp2} 0`, fontSize: 10, color: '#EF4444' }}>
          {mergeError}
        </div>
      )}

      {/* Lot cards */}
      <div style={{ flex: 1, overflowY: 'auto', padding: size.sp2, display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
        {lots.map((card) => (
          <div
            key={card._id}
            draggable={unlocked}
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = 'move'
              e.dataTransfer.setData('text/plain', card._id)
              onDragStart(card._id)
            }}
            onDragEnd={onDragEnd}
            style={{ cursor: unlocked ? 'grab' : 'default' }}
          >
            <LotCard
              card={card}
              stationId={stationId}
              template={templates[card.lotTemplateId]}
              onClick={unlocked ? undefined : () => onOpenDetail(card)}
              onMove={hasOutgoing ? () => onMoveLot(card) : undefined}
            />
          </div>
        ))}
        {lots.length === 0 && (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: size.sp5, fontSize: 11, color: color.textDim, fontStyle: 'italic',
          }}>
            {isDragging && isDropTarget ? 'Drop here' : 'waiting for precursors'}
          </div>
        )}
      </div>
    </div>
  )
}
