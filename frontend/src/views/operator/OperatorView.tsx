import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useStationsStore, useCardsStore, useProcessesStore } from '../../store'
import { sessionsApi, type WorkSession } from '../../api/sessions.api'
import { color, font, size, shadow } from '../../theme/tokens'
import type { Card } from '../../models'
import { formatDistanceToNow, differenceInSeconds } from 'date-fns'
import { getValidDestinations } from '../lots/LotsView'

// ─── Flow ─────────────────────────────────────────────────────────────────────
// 1. pick-location  → pick your station
// 2. pick-lot       → see lots at that station, tap one (or "without lot")
// 3. working        → lot selected + START button → timer running → STOP button
// 4. done           → timer shows final time + MOVE button

type Phase = 'pick-location' | 'pick-lot' | 'working' | 'done'

export default function OperatorView() {
  const [phase,     setPhase]     = useState<Phase>('pick-location')
  const [stationId, setStationId] = useState<string | null>(null)
  const [card,      setCard]      = useState<Card | null>(null)
  const [session,   setSession]   = useState<WorkSession | null>(null)
  const [elapsed,   setElapsed]   = useState(0)

  const updateCard = useCardsStore((s) => s.update)

  const reset = useCallback(() => {
    setPhase('pick-location')
    setStationId(null)
    setCard(null)
    setSession(null)
    setElapsed(0)
  }, [])

  const selectLocation = useCallback((id: string) => {
    setStationId(id)
    setPhase('pick-lot')
  }, [])

  // Phase 2 → 3: tap lot to select, then press START
  const [selectedCard, setSelectedCard] = useState<Card | null>(null)
  const [quantity,     setQuantity]     = useState(1)

  const handleSelectLot = useCallback((c: Card | null) => {
    setSelectedCard(c)
    setQuantity(c && stationId ? (c.bins[stationId]?.count ?? 1) : 1)
  }, [stationId])

  const handleStart = useCallback(async () => {
    if (!stationId) return
    const c = selectedCard
    setCard(c)
    const s = await sessionsApi.start({
      stationId,
      cardId:   c?._id ?? null,
      quantity: quantity,
    })
    if (c) await updateCard(c._id, { status: 'working' })
    setSession(s)
    setPhase('working')
  }, [stationId, selectedCard, quantity, updateCard])

  // Phase 3 → 4: STOP
  const handleStop = useCallback(async () => {
    if (!session) return
    await sessionsApi.end(session._id, quantity)
    if (card) await updateCard(card._id, { status: 'done' })
    setPhase('done')
  }, [session, card, quantity, updateCard])

  // Phase 4: MOVE to next station
  const handleMove = useCallback(async (toStationId: string) => {
    if (!card || !stationId) return
    const fromCount = card.bins[stationId]?.count ?? 0
    const moveQty   = Math.min(quantity, fromCount)
    if (moveQty <= 0) { reset(); return }

    // Update bins and reset status
    const newBins = { ...card.bins }
    const remaining = (newBins[stationId]?.count ?? 0) - moveQty
    if (remaining <= 0) {
      delete newBins[stationId]
    } else {
      newBins[stationId] = { count: remaining }
    }
    newBins[toStationId] = { count: (newBins[toStationId]?.count ?? 0) + moveQty }

    await updateCard(card._id, { bins: newBins, status: 'idle' })
    reset()
  }, [card, stationId, quantity, updateCard, reset])

  return (
    <div style={{
      flex:          1, display: 'flex', flexDirection: 'column',
      overflow:      'hidden', background: color.bgDeep,
    }}>
      {/* Header */}
      <div style={{
        padding:      `${size.sp3} ${size.sp6}`,
        borderBottom: `1px solid ${color.border}`,
        display:      'flex', alignItems: 'center', gap: size.sp4, flexShrink: 0,
      }}>
        <span style={{ fontSize: 12, fontFamily: font.mono, color: color.textSecondary, letterSpacing: '0.1em' }}>
          OPERATOR
        </span>
        {phase !== 'pick-location' && (
          <button onClick={reset} style={{
            marginLeft: 'auto', background: 'none',
            border: `1px solid ${color.border}`, borderRadius: size.radius,
            color: color.textSecondary, cursor: 'pointer', fontSize: 11, padding: '3px 10px',
          }}>
            ← Locations
          </button>
        )}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: size.sp4 }}>
        {phase === 'pick-location' && (
          <LocationPicker onSelect={selectLocation} />
        )}
        {phase === 'pick-lot' && stationId && (
          <LotPicker
            stationId={stationId}
            selected={selectedCard}
            quantity={quantity}
            onSelectLot={handleSelectLot}
            onSetQuantity={setQuantity}
            onStart={handleStart}
          />
        )}
        {phase === 'working' && session && stationId && (
          <WorkingPanel
            session={session}
            card={card}
            stationId={stationId}
            quantity={quantity}
            elapsed={elapsed}
            onSetQuantity={setQuantity}
            onElapsed={setElapsed}
            onStop={handleStop}
          />
        )}
        {phase === 'done' && stationId && (
          <DonePanel
            card={card}
            stationId={stationId}
            quantity={quantity}
            elapsed={elapsed}
            onMove={handleMove}
            onBack={reset}
          />
        )}
      </div>
    </div>
  )
}

// ─── Phase 1: Pick a location ─────────────────────────────────────────────────

function LocationPicker({ onSelect }: { onSelect: (id: string) => void }) {
  const stations = useStationsStore((s) => s.stations)
  const cards    = useCardsStore((s) => s.cards)
  const [openSessions, setOpenSessions] = useState<WorkSession[]>([])

  useEffect(() => {
    sessionsApi.openSessions().then(setOpenSessions).catch(() => {})
  }, [])

  const lotCounts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const c of Object.values(cards)) {
      for (const [sid, bin] of Object.entries(c.bins)) {
        if (bin.count > 0) m[sid] = (m[sid] ?? 0) + 1
      }
    }
    return m
  }, [cards])

  const openByStation = useMemo(() => {
    const m: Record<string, number> = {}
    for (const s of openSessions) m[s.stationId] = (m[s.stationId] ?? 0) + 1
    return m
  }, [openSessions])

  const list = Object.values(stations).sort((a, b) => a.name.localeCompare(b.name))

  if (list.length === 0) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 300, gap: 12 }}>
      <span style={{ fontFamily: font.mono, fontSize: 12, color: color.textDim, letterSpacing: '0.1em' }}>NO LOCATIONS CONFIGURED</span>
    </div>
  )

  return (
    <div>
      <div style={{ fontSize: 11, fontFamily: font.mono, color: color.textDim, letterSpacing: '0.1em', marginBottom: size.sp4 }}>
        SELECT YOUR LOCATION
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: size.sp3 }}>
        {list.map((s) => {
          const lots   = lotCounts[s._id] ?? 0
          const active = openByStation[s._id] ?? 0
          return (
            <button key={s._id} onClick={() => onSelect(s._id)} style={{
              background:   color.bgCard,
              border:       `1px solid ${active > 0 ? color.statusRunning + '60' : color.border}`,
              borderLeft:   `4px solid ${s.color ?? color.bluePrimary}`,
              borderRadius: size.radiusMd, padding: size.sp5,
              cursor: 'pointer', textAlign: 'left',
              boxShadow: active > 0 ? `0 0 12px ${color.statusRunning}18` : shadow.sm,
            }}>
              <div style={{ fontSize: 15, fontWeight: 600, color: color.textPrimary, marginBottom: 4 }}>{s.name}</div>
              <div style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono }}>
                {lots} lot{lots !== 1 ? 's' : ''}
                {active > 0 && <span style={{ color: color.statusRunning, marginLeft: 8 }}>· {active} active</span>}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ─── Phase 2: Pick a lot + START button ──────────────────────────────────────

function LotPicker({
  stationId, selected, quantity,
  onSelectLot, onSetQuantity, onStart,
}: {
  stationId:    string
  selected:     Card | null
  quantity:     number
  onSelectLot:  (c: Card | null) => void
  onSetQuantity:(n: number) => void
  onStart:      () => void
}) {
  const stations  = useStationsStore((s) => s.stations)
  const cards     = useCardsStore((s) => s.cards)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const [starting, setStarting] = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  const station = stations[stationId]
  const lots    = Object.values(cards).filter((c) => (c.bins[stationId]?.count ?? 0) > 0)

  const doStart = async () => {
    setStarting(true)
    setError(null)
    try { await onStart() } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setStarting(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp5 }}>
      <div>
        <div style={{ fontSize: 20, fontWeight: 700, color: color.textPrimary }}>{station?.name}</div>
        <div style={{ fontSize: 11, color: color.textDim, marginTop: 2 }}>
          Select a lot to work on, then press START
        </div>
      </div>

      {/* Lot list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2, marginBottom: size.sp1 }}>
        {lots.map((c) => {
          const tmpl  = templates[c.lotTemplateId]
          const count = c.bins[stationId]?.count ?? 0
          const isSel = selected?._id === c._id
          return (
            <button key={c._id} onClick={() => onSelectLot(isSel ? null : c)} style={{
              background:   isSel ? `${tmpl?.color ?? color.bluePrimary}18` : color.bgCard,
              border:       `1.5px solid ${isSel ? (tmpl?.color ?? color.bluePrimary) : color.border}`,
              borderLeft:   `4px solid ${tmpl?.color ?? color.bluePrimary}`,
              borderRadius: size.radiusMd, padding: `${size.sp3} ${size.sp4}`,
              cursor: 'pointer', textAlign: 'left',
              display: 'flex', alignItems: 'center', gap: size.sp3,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: color.textPrimary }}>
                  {tmpl?.name ?? 'Unknown'}
                  {c.lotNum != null && (
                    <span style={{ color: color.textSecondary, fontFamily: font.mono, fontWeight: 400 }}> #{c.lotNum}</span>
                  )}
                </div>
                {c.description && <div style={{ fontSize: 11, color: color.textDim, marginTop: 2 }}>{c.description}</div>}
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontFamily: font.mono, fontSize: 14, fontWeight: 700, color: color.textPrimary }}>{count}</div>
                <div style={{ fontSize: 9, color: color.textDim }}>units</div>
              </div>
              {c.flagged && <span style={{ color: color.statusWarning, flexShrink: 0 }}>⚑</span>}
            </button>
          )
        })}

        {lots.length === 0 && (
          <div style={{
            padding: size.sp5, background: color.bgCard, borderRadius: size.radiusMd,
            color: color.textDim, fontSize: 12, textAlign: 'center',
            border: `1px solid ${color.border}`,
          }}>
            No lots at this location
          </div>
        )}

      </div>

      {/* Quantity — only when a card is selected */}
      {selected !== null && (
        <label style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: size.sp2 }}>
          <span style={{ fontSize: 10, fontFamily: font.mono, color: color.textDim, letterSpacing: '0.1em' }}>UNITS</span>
          <input
            type="number" min={1} value={quantity}
            onChange={(e) => onSetQuantity(Math.max(1, parseInt(e.target.value, 10) || 1))}
            style={{
              background: color.bgCard, border: `1px solid ${color.border}`,
              borderRadius: size.radius, color: color.textPrimary,
              padding: '8px 16px', fontSize: 20, fontFamily: font.mono,
              textAlign: 'center', width: 80, outline: 'none',
            }}
          />
        </label>
      )}

      {/* Error */}
      {error && (
        <div style={{
          background: `${color.statusFault}18`, border: `1px solid ${color.statusFault}40`,
          borderRadius: size.radius, padding: `${size.sp2} ${size.sp3}`,
          fontSize: 11, color: color.statusFault,
        }}>
          {error}
        </div>
      )}

      {/* START — only appears after a lot card is selected */}
      {selected !== null && (
        <button
          onClick={doStart}
          disabled={starting}
          style={{
            width: '100%', padding: `${size.sp5} 0`,
            background:   starting ? `${color.statusRunning}40` : color.statusRunning,
            border:       'none', borderRadius: size.radiusMd,
            color:        '#fff', fontFamily: font.mono,
            fontSize:     20, fontWeight: 700, letterSpacing: '0.12em',
            cursor:       starting ? 'not-allowed' : 'pointer',
            opacity:      starting ? 0.7 : 1,
            boxShadow:    `0 4px 20px ${color.statusRunning}40`,
            transition:   'all 0.15s ease',
            marginTop:    size.sp2,
          }}
        >
          {starting ? 'STARTING…' : 'START'}
        </button>
      )}
    </div>
  )
}

// ─── Phase 3: Working + timer ─────────────────────────────────────────────────

function WorkingPanel({
  session, card, stationId, quantity, elapsed,
  onSetQuantity, onElapsed, onStop,
}: {
  session:      WorkSession
  card:         Card | null
  stationId:    string
  quantity:     number
  elapsed:      number
  onSetQuantity:(n: number) => void
  onElapsed:    (n: number) => void
  onStop:       () => void
}) {
  const stations  = useStationsStore((s) => s.stations)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const [stopping, setStopping] = useState(false)

  const startedAt = new Date(session.startedAt)

  useEffect(() => {
    const tick = () => onElapsed(differenceInSeconds(new Date(), startedAt))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [session.startedAt])

  const station = stations[stationId]
  const tmpl    = card ? templates[card.lotTemplateId] : null

  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  const timeStr = h > 0
    ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
    : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`

  const doStop = async () => { setStopping(true); try { await onStop() } finally { setStopping(false) } }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: size.sp6, paddingTop: size.sp8 }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 13, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>WORKING AT</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: color.textPrimary, marginTop: 4 }}>{station?.name}</div>
      </div>

      {card && (
        <div style={{
          background: color.bgCard, border: `1px solid ${color.border}`,
          borderLeft: `4px solid ${tmpl?.color ?? color.bluePrimary}`,
          borderRadius: size.radiusMd, padding: `${size.sp3} ${size.sp5}`,
          textAlign: 'center', minWidth: 240,
        }}>
          <div style={{ fontSize: 12, color: color.textSecondary }}>{tmpl?.name ?? 'Lot'}</div>
          {card.lotNum != null && (
            <div style={{ fontSize: 16, fontFamily: font.mono, fontWeight: 700, color: color.textPrimary }}>#{card.lotNum}</div>
          )}
        </div>
      )}

      {/* Timer */}
      <div style={{
        background: color.bgCard, border: `1px solid ${color.statusRunning}40`,
        borderRadius: size.radiusLg, padding: `${size.sp6} ${size.sp8}`,
        textAlign: 'center', boxShadow: `0 0 24px ${color.statusRunning}20`,
      }}>
        <div style={{
          fontFamily: font.mono, fontSize: 52, fontWeight: 700,
          color: color.statusRunning, letterSpacing: '0.04em', lineHeight: 1,
        }}>
          {timeStr}
        </div>
        <div style={{ fontSize: 10, color: color.textDim, marginTop: 8, fontFamily: font.mono, letterSpacing: '0.12em' }}>
          ELAPSED TIME
        </div>
      </div>

      {/* Quantity */}
      <label style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: size.sp2 }}>
        <span style={{ fontSize: 10, fontFamily: font.mono, color: color.textDim, letterSpacing: '0.1em' }}>UNITS COMPLETED</span>
        <input
          type="number" min={1} value={quantity}
          onChange={(e) => onSetQuantity(Math.max(1, parseInt(e.target.value, 10) || 1))}
          style={{
            background: color.bgCard, border: `1px solid ${color.border}`,
            borderRadius: size.radius, color: color.textPrimary,
            padding: '8px 16px', fontSize: 20, fontFamily: font.mono,
            textAlign: 'center', width: 80, outline: 'none',
          }}
        />
      </label>

      {/* DONE */}
      <button onClick={doStop} disabled={stopping} style={{
        width: 200, padding: `${size.sp4} 0`,
        background:   stopping ? `${color.statusRunning}20` : color.statusRunning,
        border: 'none', borderRadius: size.radiusMd,
        color: '#fff', fontFamily: font.mono,
        fontSize: 16, fontWeight: 700, letterSpacing: '0.1em',
        cursor: stopping ? 'not-allowed' : 'pointer',
        opacity: stopping ? 0.7 : 1, boxShadow: shadow.md, transition: 'all 0.15s ease',
      }}>
        {stopping ? 'FINISHING…' : 'DONE'}
      </button>

      <div style={{ fontSize: 11, color: color.textDim }}>
        Started {formatDistanceToNow(startedAt, { addSuffix: true })}
      </div>
    </div>
  )
}

// ─── Phase 4: Done — show elapsed, MOVE button ────────────────────────────────

function DonePanel({
  card, stationId, quantity, elapsed, onMove, onBack,
}: {
  card:     Card | null
  stationId:string
  quantity: number
  elapsed:  number
  onMove:   (toStationId: string) => void
  onBack:   () => void
}) {
  const stations  = useStationsStore((s) => s.stations)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const routes    = useProcessesStore((s) => s.routes)
  const [moving,  setMoving]  = useState(false)
  const [toId,    setToId]    = useState('')

  const station = stations[stationId]
  const tmpl    = card ? templates[card.lotTemplateId] : null

  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  const timeStr = h > 0
    ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
    : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`

  const destinations = useMemo(() => {
    const ids = getValidDestinations(stationId, routes)
    return ids.map((id) => stations[id]).filter(Boolean)
  }, [stationId, routes, stations])

  // Auto-select if only one destination
  useEffect(() => {
    if (destinations.length === 1) setToId(destinations[0]!._id)
  }, [destinations])

  const doMove = async () => {
    const dest = toId || (destinations.length === 1 ? destinations[0]!._id : '')
    if (!dest) return
    setMoving(true)
    try { await onMove(dest) } finally { setMoving(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: size.sp6, paddingTop: size.sp8 }}>
      {/* Done indicator */}
      <div style={{ textAlign: 'center' }}>
        <div style={{
          fontSize: 40, marginBottom: 8,
          filter: 'drop-shadow(0 0 12px #10B981)',
        }}>✓</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: color.statusRunning }}>DONE</div>
        <div style={{ fontSize: 13, color: color.textSecondary, marginTop: 4 }}>{station?.name}</div>
      </div>

      {/* Final time */}
      <div style={{
        background: color.bgCard, border: `1px solid ${color.border}`,
        borderRadius: size.radiusLg, padding: `${size.sp5} ${size.sp8}`,
        textAlign: 'center',
      }}>
        <div style={{ fontFamily: font.mono, fontSize: 44, fontWeight: 700, color: color.textPrimary, lineHeight: 1 }}>
          {timeStr}
        </div>
        <div style={{ fontSize: 10, color: color.textDim, marginTop: 6, fontFamily: font.mono, letterSpacing: '0.1em' }}>
          {quantity} UNIT{quantity !== 1 ? 'S' : ''} · {(elapsed / Math.max(1, quantity)).toFixed(1)}s EACH
        </div>
      </div>

      {/* Lot info */}
      {card && (
        <div style={{ fontSize: 12, color: color.textSecondary, textAlign: 'center' }}>
          {tmpl?.name ?? 'Lot'}
          {card.lotNum != null && <span style={{ fontFamily: font.mono }}> #{card.lotNum}</span>}
        </div>
      )}

      {/* Destination picker (only when multiple options) */}
      {destinations.length > 1 && (
        <div style={{ width: '100%', maxWidth: 320 }}>
          <div style={{ fontSize: 10, fontFamily: font.mono, color: color.textDim, letterSpacing: '0.1em', marginBottom: 6 }}>
            MOVE TO
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
            {destinations.map((dest) => (
              <button
                key={dest!._id}
                onClick={() => setToId(dest!._id)}
                style={{
                  background:   toId === dest!._id ? `${dest!.color ?? color.bluePrimary}18` : color.bgCard,
                  border:       `1.5px solid ${toId === dest!._id ? (dest!.color ?? color.bluePrimary) : color.border}`,
                  borderRadius: size.radiusMd, padding: `${size.sp3} ${size.sp4}`,
                  cursor: 'pointer', textAlign: 'left', color: color.textPrimary,
                  fontSize: 13, fontWeight: toId === dest!._id ? 600 : 400,
                }}
              >
                {dest!.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* MOVE button */}
      {destinations.length > 0 && (
        <button
          onClick={doMove}
          disabled={moving || (!toId && destinations.length > 1)}
          style={{
            width: '100%', maxWidth: 320, padding: `${size.sp5} 0`,
            background:   (moving || (!toId && destinations.length > 1))
              ? `${color.bluePrimary}40`
              : color.bluePrimary,
            border: 'none', borderRadius: size.radiusMd,
            color: '#fff', fontFamily: font.mono,
            fontSize: 20, fontWeight: 700, letterSpacing: '0.12em',
            cursor: (moving || (!toId && destinations.length > 1)) ? 'not-allowed' : 'pointer',
            boxShadow: `0 4px 20px ${color.bluePrimary}40`,
            transition: 'all 0.15s ease',
          }}
        >
          {moving ? 'MOVING…' : destinations.length === 1
            ? `MOVE → ${destinations[0]!.name}`
            : 'MOVE'}
        </button>
      )}

      <button onClick={onBack} style={{
        background: 'none', border: `1px solid ${color.border}`,
        borderRadius: size.radius, color: color.textSecondary,
        cursor: 'pointer', fontSize: 12, padding: '6px 20px',
      }}>
        Back to locations
      </button>
    </div>
  )
}
