import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCardsStore, useStationsStore, useProcessesStore } from '../../store'
import { color, font, size } from '../../theme/tokens'
import LotCard from '../../components/lots/LotCard'
import CreateLotModal from '../../components/lots/CreateLotModal'
import MergeLotModal from '../../components/lots/MergeLotModal'
import MoveLotModal from '../../components/lots/MoveLotModal'
import LotDetailModal from '../../components/lots/LotDetailModal'
import { mergeNodes, computeColumnGroups, computeLanes, type BarSpan } from '../../domain/graph'
import { mergeApi, type MergePreview } from '../../api/merge.api'
import { useRole } from '../../auth/useRole'
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

// Immediate upstream stations (direct predecessors) — valid *backward* drop
// targets in the lot board (moving a lot one step back / triggering an unmerge).
export function getBackwardDestinations(
  fromStationId: string,
  routes: Record<string, Route>,
): string[] {
  return Object.values(routes)
    .filter((r) => r.unload === fromStationId)
    .map((r) => r.load)
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

// ─── Split icon ───────────────────────────────────────────────────────────────
function SplitIcon() {
  return (
    <svg width="13" height="11" viewBox="0 0 13 11" fill="currentColor" aria-hidden="true">
      <rect x="0" y="0"   width="13" height="4.5" rx="1.2" />
      <rect x="0" y="6.5" width="13" height="4.5" rx="1.2" />
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
  const fetchAllCards = useCardsStore((s) => s.fetchAll)
  // canEdit (super-admin): structural board editing — drag, move, unmerge.
  // canManageLots (admin+): create lots, pull precursors, merge.
  const { canEdit, canManageLots } = useRole()

  const [createStation, setCreateStation] = useState<string | null>(null)
  const [activeMove,    setActiveMove]    = useState<ActiveMove | null>(null)
  const [activeDetail,  setActiveDetail]  = useState<ActiveDetail | null>(null)

  // ─── Drag-and-drop / view-mode state ─────────────────────────────────────
  const [unlocked,  setUnlocked]  = useState(false)
  const [lockFlash, setLockFlash] = useState(false)
  const [dragging,  setDragging]  = useState<DragState | null>(null)
  const [splitMode, setSplitMode] = useState(() => {
    try { return localStorage.getItem('lots-split') === '1' } catch { return false }
  })
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => {
    try {
      const stored = localStorage.getItem('lots-groups')
      return stored ? new Set<string>(JSON.parse(stored)) : new Set<string>()
    } catch { return new Set<string>() }
  })
  const [cardLimit, setCardLimit] = useState<number>(() => {
    try { return parseInt(localStorage.getItem('lots-limit') ?? '3', 10) || 3 } catch { return 3 }
  })
  const [sortBy,  setSortBy]  = useState<'age' | 'units'>(() => {
    try { return (localStorage.getItem('lots-sort') as 'age' | 'units') || 'age' } catch { return 'age' }
  })
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(() => {
    try { return (localStorage.getItem('lots-sort-dir') as 'asc' | 'desc') || 'asc' } catch { return 'asc' }
  })

  const triggerLockFlash = useCallback(() => {
    setLockFlash(true)
    setTimeout(() => setLockFlash(false), 550)
  }, [])

  const validDropTargets = useMemo(
    () => dragging
      ? new Set([
          ...getValidDestinations(dragging.fromStationId, routes),    // forward
          ...getBackwardDestinations(dragging.fromStationId, routes), // one step back
        ])
      : new Set<string>(),
    [dragging, routes],
  )

  const handleDrop = useCallback(async (toStationId: string) => {
    if (!dragging || !validDropTargets.has(toStationId)) return
    const from = dragging.fromStationId
    const card = cards[dragging.cardId]
    if (!card) return
    const qty = card.bins[from]?.count ?? 0
    if (qty <= 0) return
    // Clear drag state immediately so UI resets even if the API call takes time
    setDragging(null)

    const isBackward = Object.values(routes).some((r) => r.load === toStationId && r.unload === from)
    const fromIncoming = Object.values(routes).filter((r) => r.unload === from).length

    try {
      // Backward-dragging out of a merge station: if this lot was assembled here,
      // dissolve it into ALL its precursor branches. We ask the backend rather
      // than checking the template client-side — an auto-created assembly template
      // may not be in the store yet, and misclassifying it as a plain lot would do
      // a bare move and strand the other precursors (data loss). The backend
      // rejects (400) when it isn't an assembly here, so we fall back to a move.
      if (isBackward && fromIncoming >= 2) {
        try {
          await cardsApi.unmerge(card._id, from, qty)
          await fetchAllCards()
          return
        } catch (e) {
          // Fall back to a plain move ONLY when the backend says this lot is not
          // an assembly here. Any other failure (stale quantity, race, network)
          // must NOT retry as a move — the unmerge may have partially applied
          // state we can't see, and a blind move can duplicate or strand lots.
          const msg = String(e)
          if (!msg.includes('not assembled') && !msg.includes('Not a merge station')) {
            console.error('unmerge failed:', e)
            await fetchAllCards()   // resync whatever the server state is
            return
          }
        }
      }
      const updated = await cardsApi.move(card._id, from, toStationId, qty)
      upsertCard(updated)
    } catch (e) {
      console.error('Drag-move failed:', e)
    }
  }, [dragging, validDropTargets, cards, routes, upsertCard, fetchAllCards])

  // ─── Merge nodes ──────────────────────────────────────────────────────────

  const mergeNodeSet = useMemo(
    () => mergeNodes(Object.values(routes) as { load: string; unload: string }[]),
    [routes],
  )

  const { order: topoOrder, solidBars, dashedBars } = useMemo(() => {
    const edgeList = Object.values(routes).map((r) => ({ load: r.load, unload: r.unload }))
    return computeColumnGroups(edgeList, Object.keys(stations))
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

  // ─── Group / collapse helpers ─────────────────────────────────────────────

  const colById = useMemo(
    () => new Map(columns.map((c) => [c.stationId, c])),
    [columns],
  )

  // Segments = solid-bar groups (each segment has ≥ 2 columns).
  const segments = useMemo(
    () => solidBars.map((bar) => ({
      key:        topoOrder[bar.start] ?? `seg-${bar.start}`,
      stationIds: topoOrder.slice(bar.start, bar.end + 1),
    })),
    [solidBars, topoOrder],
  )

  // Render groups: each solid-bar segment becomes one group; remaining columns
  // are singletons.  Groups are returned in topoOrder.
  const renderGroupsData = useMemo(() => {
    type RG = { key: string; stationIds: string[]; hasSolidBar: boolean }
    const result: RG[] = []
    const inSegment = new Set<string>()
    for (const seg of segments) {
      result.push({ key: seg.key, stationIds: seg.stationIds, hasSolidBar: true })
      seg.stationIds.forEach((id) => inSegment.add(id))
    }
    for (const id of topoOrder) {
      if (!inSegment.has(id)) result.push({ key: id, stationIds: [id], hasSolidBar: false })
    }
    result.sort((a, b) => topoOrder.indexOf(a.stationIds[0]) - topoOrder.indexOf(b.stationIds[0]))
    return result
  }, [segments, topoOrder])

  // Source nodes and merge nodes show action buttons — always stay visible when collapsed.
  const isActionStation = (stationId: string): boolean =>
    mergeNodeSet.has(stationId) ||
    !Object.values(routes).some((r) => r.unload === stationId)

  const toggleGroup = (key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      try { localStorage.setItem('lots-groups', JSON.stringify([...next])) } catch {}
      return next
    })
  }

  const collapseAllGroups = () => {
    const keys = splitRows
      ? splitRows.map((lane) => lane[0]?.stationId).filter((k): k is string => !!k)
      : segments.map((s) => s.key)
    const next = new Set(keys)
    try { localStorage.setItem('lots-groups', JSON.stringify([...next])) } catch {}
    setCollapsedGroups(next)
  }

  const expandAllGroups = () => {
    try { localStorage.setItem('lots-groups', JSON.stringify([])) } catch {}
    setCollapsedGroups(new Set<string>())
  }

  // ─── Split-mode lanes ─────────────────────────────────────────────────────
  // One lane per source node = peak parallelism of the process.
  // Each lane follows its source forward; post-merge segments extend the lane
  // that first claims the merge node (first source in topological order).
  const splitRows = useMemo(() => {
    if (!splitMode || columns.length === 0) return null
    const edgeList = Object.values(routes).map((r) => ({ load: r.load, unload: r.unload }))
    const lanes    = computeLanes(edgeList, Object.keys(stations))
    if (lanes.length === 0) return null
    return lanes.map((lane) => lane.map((id) => colById.get(id)!).filter(Boolean))
  }, [splitMode, columns, stations, routes, colById])

  // ─── Column-item renderer (shared by normal and split layouts) ────────────
  const renderColumnItem = (col: (typeof columns)[number]) => {
    const { stationId, station, lots } = col
    const isDropTarget = validDropTargets.has(stationId)
    const props = {
      stationId, station, lots, templates, routes, canEdit, canManageLots, onLockedDrag: triggerLockFlash,
      unlocked: canEdit && unlocked, isDragging: dragging !== null, isDropTarget,
      onDragStart: (cardId: string) => setDragging({ cardId, fromStationId: stationId }),
      onDragEnd:   () => setDragging(null),
      onDrop:      () => handleDrop(stationId),
      onCreateLot: () => setCreateStation(stationId),
      onOpenDetail: (card: Card) => setActiveDetail({ card, stationId }),
      onMoveLot:   (card: Card) => setActiveMove({ card, fromStationId: stationId }),
      cardLimit,
      sortBy,
      sortDir,
    }
    return mergeNodeSet.has(stationId)
      ? <MergeColumn  key={stationId} {...props} />
      : <KanbanColumn key={stationId} {...props} />
  }

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

        {/* Right-side controls */}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: size.sp2 }}>
          {(['FOLD', 'UNFOLD'] as const).map((label) => (
            <button
              key={label}
              onClick={label === 'FOLD' ? collapseAllGroups : expandAllGroups}
              title={label === 'FOLD' ? 'Collapse all groups' : 'Expand all groups'}
              style={{
                display: 'flex', alignItems: 'center', gap: 5,
                padding: '4px 10px', background: 'transparent',
                border: `1px solid ${color.border}`, borderRadius: size.radius,
                color: color.textSecondary, cursor: 'pointer',
                fontSize: 11, fontFamily: font.mono, letterSpacing: '0.06em',
              }}
            >
              {label}
            </button>
          ))}
          {/* Divider */}
          <div style={{ width: 1, height: 18, background: color.border }} />

          {/* Sort-by buttons */}
          {(['age', 'units'] as const).map((opt) => (
            <button
              key={opt}
              onClick={() => {
                setSortBy(opt)
                try { localStorage.setItem('lots-sort', opt) } catch {}
              }}
              title={opt === 'age' ? 'Sort by creation date' : 'Sort by unit count'}
              style={{
                padding: '4px 8px', cursor: 'pointer',
                background:   sortBy === opt ? `${color.bluePrimary}18` : 'transparent',
                border:       `1px solid ${sortBy === opt ? `${color.bluePrimary}60` : color.border}`,
                borderRadius: size.radius,
                color:        sortBy === opt ? color.bluePrimary : color.textSecondary,
                fontSize: 11, fontFamily: font.mono, letterSpacing: '0.06em',
              }}
            >
              {opt === 'age' ? 'AGE' : 'UNITS'}
            </button>
          ))}

          {/* Sort direction toggle */}
          <button
            onClick={() => {
              const next = sortDir === 'asc' ? 'desc' : 'asc'
              setSortDir(next)
              try { localStorage.setItem('lots-sort-dir', next) } catch {}
            }}
            title={sortDir === 'asc' ? 'Ascending — click to reverse' : 'Descending — click to reverse'}
            style={{
              padding: '4px 7px', background: 'transparent',
              border: `1px solid ${color.border}`, borderRadius: size.radius,
              color: color.textSecondary, cursor: 'pointer', fontSize: 13, lineHeight: 1,
            }}
          >
            {sortDir === 'asc' ? '↑' : '↓'}
          </button>

          {/* Divider */}
          <div style={{ width: 1, height: 18, background: color.border }} />

          {/* Card limit stepper */}
          <div
            title="Max cards shown per column"
            style={{
              display: 'flex', alignItems: 'center',
              border: `1px solid ${color.border}`, borderRadius: size.radius,
              overflow: 'hidden',
            }}
          >
            <button
              onClick={() => {
                const next = Math.max(1, cardLimit - 1)
                setCardLimit(next)
                try { localStorage.setItem('lots-limit', String(next)) } catch {}
              }}
              style={{
                padding: '4px 8px', background: 'transparent', border: 'none',
                borderRight: `1px solid ${color.border}`,
                color: color.textSecondary, cursor: 'pointer',
                fontSize: 13, lineHeight: 1, fontFamily: font.mono,
              }}
            >−</button>
            <span style={{
              fontSize: 11, fontFamily: font.mono, color: color.textPrimary,
              minWidth: 22, textAlign: 'center', userSelect: 'none', padding: '0 2px',
            }}>
              {cardLimit}
            </span>
            <button
              onClick={() => {
                const next = Math.min(50, cardLimit + 1)
                setCardLimit(next)
                try { localStorage.setItem('lots-limit', String(next)) } catch {}
              }}
              style={{
                padding: '4px 8px', background: 'transparent', border: 'none',
                borderLeft: `1px solid ${color.border}`,
                color: color.textSecondary, cursor: 'pointer',
                fontSize: 13, lineHeight: 1, fontFamily: font.mono,
              }}
            >+</button>
          </div>

          {/* Divider */}
          <div style={{ width: 1, height: 18, background: color.border }} />

          <button
            onClick={() => {
              const next = !splitMode
              setSplitMode(next)
              try { localStorage.setItem('lots-split', next ? '1' : '0') } catch {}
            }}
            title="Stack parallel branches vertically"
            style={{
              display:       'flex',
              alignItems:    'center',
              gap:           5,
              padding:       '4px 10px',
              background:    splitMode ? `${color.bluePrimary}18` : 'transparent',
              border:        `1px solid ${splitMode ? `${color.bluePrimary}60` : color.border}`,
              borderRadius:  size.radius,
              color:         splitMode ? color.bluePrimary : color.textSecondary,
              cursor:        'pointer',
              fontSize:      11,
              fontFamily:    font.mono,
              letterSpacing: '0.06em',
              transition:    'all 0.15s ease',
            }}
          >
            <SplitIcon />
            SPLIT
          </button>
          {canEdit && (
          <button
            className={lockFlash ? 'lock-flash' : undefined}
            onClick={() => { setUnlocked((u) => !u); setDragging(null) }}
            style={{
              display:       'flex',
              alignItems:    'center',
              gap:           5,
              padding:       '4px 10px',
              background:    unlocked ? '#EF9F2718' : 'transparent',
              border:        `1px solid ${unlocked ? '#EF9F2760' : color.border}`,
              borderRadius:  size.radius,
              color:         unlocked ? '#EF9F27' : color.textSecondary,
              cursor:        'pointer',
              fontSize:      11,
              fontFamily:    font.mono,
              letterSpacing: '0.06em',
              transition:    'all 0.15s ease',
            }}
          >
            <LockIcon open={unlocked} />
            {unlocked ? 'LOCK' : 'DRAG'}
          </button>
          )}
        </div>
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
      ) : splitRows ? (
        // ── Split mode: one row per source-node lane ───────────────────────
        <div style={{
          flex:          1,
          display:       'flex',
          flexDirection: 'column',
          overflowX:     'hidden',
          overflowY:     'auto',
        }}>
          {splitRows.map((lane, laneIdx) => {
            const laneKey        = lane[0]?.stationId ?? `lane-${laneIdx}`
            const isLaneCollapsed = collapsedGroups.has(laneKey)
            const visibleLane    = isLaneCollapsed
              ? lane.filter((col) => isActionStation(col.stationId))
              : lane
            return (
              <React.Fragment key={laneIdx}>
                {laneIdx > 0 && (
                  <div style={{
                    height:     8,
                    flexShrink: 0,
                    background: color.bgPanel,
                    borderTop:  `1px solid ${color.border}`,
                  }} />
                )}
                <div style={{
                  display:       'flex',
                  flexDirection: 'column',
                  overflowX:     'auto',
                  overflowY:     'hidden',
                  flexShrink:    0,
                }}>
                  {lane.length >= 2 && (
                    <LaneBar
                      laneLength={visibleLane.length}
                      collapsed={isLaneCollapsed}
                      onClick={() => toggleGroup(laneKey)}
                    />
                  )}
                  <div style={{
                    display:    'flex',
                    padding:    size.sp4,
                    paddingTop: lane.length >= 2 ? 4 : size.sp4,
                    gap:        size.sp4,
                    alignItems: 'flex-start',
                  }}>
                    {visibleLane.map(renderColumnItem)}
                  </div>
                </div>
              </React.Fragment>
            )
          })}
        </div>
      ) : (
        // ── Normal mode: group-based layout, solid bars are collapse triggers ──
        <div style={{
          flex:       1,
          overflowX:  'auto',
          overflowY:  'hidden',
          alignItems: 'flex-start',
        }}>
          <div style={{ display: 'flex', padding: size.sp4, gap: size.sp4, alignItems: 'flex-start' }}>
            {renderGroupsData.map((group) => {
              const isCollapsed = collapsedGroups.has(group.key)
              const groupCols   = group.stationIds
                .map((id) => colById.get(id))
                .filter((c): c is (typeof columns)[0] => !!c)
              const visibleCols = isCollapsed
                ? groupCols.filter((col) => isActionStation(col.stationId))
                : groupCols

              if (!group.hasSolidBar) {
                return visibleCols.length > 0 ? renderColumnItem(visibleCols[0]) : null
              }

              return (
                <div key={group.key} style={{ display: 'flex', flexDirection: 'column' }}>
                  <GroupBar
                    columnCount={visibleCols.length}
                    collapsed={isCollapsed}
                    onClick={() => toggleGroup(group.key)}
                  />
                  <div style={{ display: 'flex', gap: size.sp4, alignItems: 'flex-start' }}>
                    {visibleCols.map((col) => renderColumnItem(col))}
                  </div>
                </div>
              )
            })}
          </div>
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
  // Display
  cardLimit:    number
  sortBy:       'age' | 'units'
  sortDir:      'asc' | 'desc'
  canEdit:      boolean   // super-admin: drag / move / unmerge
  canManageLots: boolean  // admin+: create lots, pull precursors, merge
  onLockedDrag: () => void
}

// ─── Drop-zone styling helper ─────────────────────────────────────────────────

function columnBorderTop(accentColor: string, isDragging: boolean, isDropTarget: boolean, hovering: boolean): string {
  if (isDragging && isDropTarget) return `3px solid #639922`
  return `3px solid ${accentColor}`
}

function columnOpacity(isDragging: boolean, isDropTarget: boolean): number {
  if (isDragging && !isDropTarget) return 0.45
  return 1
}

function columnBackground(isDragging: boolean, isDropTarget: boolean, hovering: boolean, base: string): string {
  if (isDragging && isDropTarget && hovering) return '#63992210'
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
  cardLimit, sortBy, sortDir, canEdit, canManageLots, onLockedDrag,
}: KanbanColumnProps) {
  const [hovering,   setHovering]   = useState(false)
  const totalUnits  = lots.reduce((sum, c) => sum + (c.bins[stationId]?.count ?? 0), 0)
  const hasOutgoing    = Object.values(routes).some((r) => r.load   === stationId)
  const hasIncoming    = Object.values(routes).some((r) => r.unload === stationId)
  const isMergeStation = Object.values(routes).filter((r) => r.unload === stationId).length >= 2
  const accentColor = station.color ?? color.lotBlue

  const displayLots = [...lots].sort((a, b) => {
    const cmp = sortBy === 'age'
      ? a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : 0
      : (a.bins[stationId]?.count ?? 0) - (b.bins[stationId]?.count ?? 0)
    return sortDir === 'asc' ? cmp : -cmp
  }).slice(0, cardLimit)
  const hiddenCount = lots.length - displayLots.length

  return (
    <div
      style={{
        width:         220,
        flexShrink:    0,
        background:    columnBackground(isDragging, isDropTarget, hovering, color.bgCard),
        border:        `1px solid ${isDragging && isDropTarget ? '#63992250' : color.border}`,
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
        {displayLots.map((card) => (
          <div
            key={card._id}
            draggable={canEdit}
            onDragStart={(e) => {
              if (!unlocked) { e.preventDefault(); onLockedDrag(); return }
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
              onMove={canEdit && hasOutgoing ? () => onMoveLot(card) : undefined}
            />
          </div>
        ))}
        {hiddenCount > 0 && (
          <div style={{
            fontSize: 10, color: color.textDim, fontFamily: font.mono,
            textAlign: 'center', padding: `${size.sp1} 0`, letterSpacing: '0.05em',
          }}>
            +{hiddenCount} more
          </div>
        )}
        {lots.length === 0 && (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: size.sp5, fontSize: 11, color: color.textDim, fontStyle: 'italic',
          }}>
            {isDragging && isDropTarget ? 'Drop here' : 'empty'}
          </div>
        )}
      </div>

      {/* Footer: source queues create a lot directly; a finished-goods leaf (no
          outgoing route) pulls precursors. Pass-through stations do neither —
          their lots arrive by being advanced from upstream. (Merges have their
          own column with a pull button.) */}
      {canManageLots && (!hasIncoming || !hasOutgoing) && (
        <div style={{ padding: size.sp2, borderTop: `1px solid ${color.border}`, flexShrink: 0 }}>
          <button
            data-tour={hasIncoming && !hasOutgoing ? 'lots-pull' : undefined}
            onClick={onCreateLot}
            style={{
              width: '100%', background: 'transparent',
              border: `1px dashed ${hasIncoming ? '#7C3AED80' : color.border}`,
              borderRadius: size.radius,
              color: hasIncoming ? '#A78BFA' : color.textDim,
              cursor: 'pointer', fontSize: 11, padding: '5px 0',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.opacity = '0.75' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.opacity = '1' }}
          >
            {hasIncoming ? '⬇ pull precursors' : '+ create lot'}
          </button>
        </div>
      )}
    </div>
  )
}

// ─── Branch group bars ────────────────────────────────────────────────────────
// COL_W / COL_GAP must match the actual column widths and gap in the columns row.

const COL_W   = 220
const COL_GAP = 16   // px — matches size.sp4
const UNIT    = COL_W + COL_GAP  // = 236

// Clickable solid bar spanning n columns; used as a group collapse trigger in
// normal mode.  Width = (n-1)×UNIT + COL_W which exactly matches n columns with
// gap=COL_GAP between them (no outer padding on the group container).
function GroupBar({
  columnCount,
  collapsed,
  onClick,
}: {
  columnCount: number
  collapsed:   boolean
  onClick:     () => void
}) {
  if (columnCount < 1) return null
  const width = (columnCount - 1) * UNIT + COL_W
  const clr   = color.border
  return (
    <div
      onClick={onClick}
      title={collapsed ? 'Expand group' : 'Collapse group'}
      style={{ position: 'relative', width, height: 28, flexShrink: 0, cursor: 'pointer' }}
    >
      <div style={{ position: 'absolute', top: 14, left: 0, width: '100%', height: 1.5, background: clr }} />
      <div style={{ position: 'absolute', left:  0, top: 11, width: 1.5, height: 7, background: clr }} />
      <div style={{ position: 'absolute', right: 0, top: 11, width: 1.5, height: 7, background: clr }} />
      {collapsed && (
        <span style={{
          position: 'absolute', top: 7, left: 6,
          fontSize: 9, color: color.textDim, userSelect: 'none',
        }}>▶▶</span>
      )}
    </div>
  )
}

function BarLine({ bar, top, dashed }: { bar: BarSpan; top: number; dashed: boolean }) {
  const left  = 16 + bar.start * UNIT
  const width = (bar.end - bar.start) * UNIT + COL_W
  const clr   = dashed ? color.textDim : color.border
  return (
    <div style={{
      position:   'absolute',
      top,
      left,
      width,
      height:     dashed ? 0 : 1.5,
      background: dashed ? undefined : clr,
      borderTop:  dashed ? `1.5px dashed ${clr}` : undefined,
    }}>
      <div style={{ position: 'absolute', left:  0, top: -3, width: 1.5, height: 7, background: clr }} />
      <div style={{ position: 'absolute', right: 0, top: -3, width: 1.5, height: 7, background: clr }} />
    </div>
  )
}

// Clickable solid bar spanning all columns in a split-mode lane; also serves as
// the lane's collapse trigger.
function LaneBar({ laneLength, collapsed, onClick }: {
  laneLength: number
  collapsed?: boolean
  onClick?:   () => void
}) {
  if (laneLength < 1) return null
  const bar: BarSpan = { start: 0, end: laneLength - 1 }
  const totalW = 16 + laneLength * UNIT
  return (
    <div
      onClick={onClick}
      style={{
        position: 'relative', width: totalW, height: 28, flexShrink: 0,
        cursor: onClick ? 'pointer' : 'default',
      }}
    >
      <BarLine bar={bar} top={14} dashed={false} />
      {collapsed && (
        <span style={{
          position: 'absolute', top: 7, left: 22,
          fontSize: 9, color: color.textDim, userSelect: 'none',
        }}>▶▶</span>
      )}
    </div>
  )
}

// ─── Merge station column ─────────────────────────────────────────────────────

interface MergeColumnProps extends ColumnProps {
  onCreateLot: () => void
}

function MergeColumn({
  stationId, station, lots, templates, routes, onCreateLot, onOpenDetail, onMoveLot,
  unlocked, isDragging, isDropTarget, onDragStart, onDragEnd, onDrop,
  cardLimit, sortBy, sortDir, canEdit, canManageLots, onLockedDrag,
}: MergeColumnProps) {
  const navigate    = useNavigate()
  const accentColor = station.color ?? '#8B5CF6'
  const hasOutgoing = Object.values(routes).some((r) => r.load === stationId)

  const displayLots = [...lots].sort((a, b) => {
    const cmp = sortBy === 'age'
      ? a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : 0
      : (a.bins[stationId]?.count ?? 0) - (b.bins[stationId]?.count ?? 0)
    return sortDir === 'asc' ? cmp : -cmp
  }).slice(0, cardLimit)
  const hiddenCount = lots.length - displayLots.length

  const [hovering,  setHovering]  = useState(false)
  const [preview,   setPreview]   = useState<MergePreview | null>(null)
  const [showMerge, setShowMerge] = useState(false)

  const lotsKey = useMemo(
    () => lots.map((c) => `${c._id}:${c.bins[stationId]?.count ?? 0}`).join('|'),
    [lots, stationId],
  )

  const refreshPreview = useCallback(() => {
    mergeApi.preview(stationId).then(setPreview).catch(console.error)
  }, [stationId])

  useEffect(() => { refreshPreview() }, [refreshPreview, lotsKey])

  const canMerge   = (preview?.assembliesPossible ?? 0) > 0

  return (
    <div
      style={{
        width:         220,
        flexShrink:    0,
        background:    columnBackground(isDragging, isDropTarget, hovering, color.bgCard),
        border:        `1px solid ${isDragging && isDropTarget ? '#63992250' : color.border}`,
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
                    background: req.availableUnits >= req.requiredPerAssembly ? '#639922' : color.textDim,
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

      {/* Merge ready banner */}
      {canManageLots && canMerge && (
        <div style={{
          margin: `${size.sp2} ${size.sp2} 0`,
          padding: `${size.sp2} ${size.sp3}`,
          background: '#63992215', border: `1px solid #63992240`,
          borderRadius: size.radius,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: size.sp2,
        }}>
          <span style={{ fontSize: 11, color: '#639922', fontFamily: font.mono }}>
            {preview!.assembliesPossible}× ready
          </span>
          <button
            onClick={() => setShowMerge(true)}
            style={{
              background: '#639922', color: '#fff', border: 'none',
              borderRadius: size.radius, padding: '3px 10px',
              fontSize: 11, fontFamily: font.mono, cursor: 'pointer',
            }}
          >
            Merge…
          </button>
        </div>
      )}

      {showMerge && (
        <MergeLotModal
          stationId={stationId}
          onClose={() => setShowMerge(false)}
          onMerged={refreshPreview}
        />
      )}

      {/* Lot cards */}
      <div style={{ flex: 1, overflowY: 'auto', padding: size.sp2, display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
        {displayLots.map((card) => (
          <div
            key={card._id}
            draggable={canEdit}
            onDragStart={(e) => {
              if (!unlocked) { e.preventDefault(); onLockedDrag(); return }
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
              onMove={canEdit && hasOutgoing ? () => onMoveLot(card) : undefined}
            />
          </div>
        ))}
        {hiddenCount > 0 && (
          <div style={{
            fontSize: 10, color: color.textDim, fontFamily: font.mono,
            textAlign: 'center', padding: `${size.sp1} 0`, letterSpacing: '0.05em',
          }}>
            +{hiddenCount} more
          </div>
        )}
        {lots.length === 0 && (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: size.sp5, fontSize: 11, color: color.textDim, fontStyle: 'italic',
          }}>
            {isDragging && isDropTarget ? 'Drop here' : 'waiting for precursors'}
          </div>
        )}
      </div>

      {/* Footer: pull precursors */}
      {canManageLots && (
        <div style={{ padding: size.sp2, borderTop: `1px solid ${color.border}`, flexShrink: 0 }}>
          <button
            onClick={onCreateLot}
            style={{
              width: '100%', background: 'transparent',
              border: `1px dashed #7C3AED80`,
              borderRadius: size.radius,
              color: '#A78BFA',
              cursor: 'pointer', fontSize: 11, padding: '5px 0',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.opacity = '0.75' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.opacity = '1' }}
          >
            ⬇ pull precursors
          </button>
        </div>
      )}
    </div>
  )
}
