import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useStationsStore, useCardsStore, useProcessesStore } from '../../store'
import { sessionsApi, type WorkSession } from '../../api/sessions.api'
import { color, font, size, shadow } from '../../theme/tokens'
import type { Card } from '../../models'
import { formatDistanceToNow, differenceInSeconds } from 'date-fns'
import { getValidDestinations } from '../lots/LotsView'
import { mergeNodes } from '../../domain/graph'
import { mergeApi } from '../../api/merge.api'
import LotCard from '../../components/lots/LotCard'

// Returns the total seconds from the most recent closed session for a card at a station.
async function fetchDoneElapsed(stationId: string, cardId: string): Promise<number> {
  try {
    const sessions = await sessionsApi.list(stationId)
    const last = sessions
      .filter((s) => s.cardId === cardId && s.durationSec != null)
      .sort((a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime())[0]
    return last?.durationSec ?? 0
  } catch {
    return 0
  }
}

function formatElapsed(totalSeconds: number): string {
  const t  = Math.floor(totalSeconds)
  const h  = Math.floor(t / 3600)
  const m  = Math.floor((t % 3600) / 60)
  const s  = t % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${String(h).padStart(2, '0')}:${mm}:${ss}` : `${mm}:${ss}`
}

// ─── Flow ─────────────────────────────────────────────────────────────────────
// 1. pick-location  → pick your station
// 2. pick-lot       → see lots at that station, tap one
// 3. working        → lot selected + START button → timer running → STOP button
// 4. done           → timer shows final time + MOVE button

type Phase = 'pick-location' | 'pick-lot' | 'working' | 'done'

export default function OperatorView() {
  const [phase,         setPhase]         = useState<Phase>('pick-location')
  const [stationId,     setStationId]     = useState<string | null>(null)
  const [card,          setCard]          = useState<Card | null>(null)
  const [session,       setSession]       = useState<WorkSession | null>(null)
  const [elapsed,       setElapsed]       = useState(0)
  const [elapsedOffset, setElapsedOffset] = useState(0)

  const cards       = useCardsStore((s) => s.cards)
  const routes      = useProcessesStore((s) => s.routes)
  const updateCard  = useCardsStore((s) => s.update)

  const mergeNodeSet = useMemo(
    () => mergeNodes(Object.values(routes) as { load: string; unload: string }[]),
    [routes],
  )

  const [selectedCard, setSelectedCard] = useState<Card | null>(null)
  const [quantity,     setQuantity]     = useState(1)

  const reset = useCallback(() => {
    setPhase('pick-location')
    setStationId(null)
    setCard(null)
    setSession(null)
    setElapsed(0)
    setElapsedOffset(0)
  }, [])

  // On mount: if there is exactly one open session, jump straight to working panel.
  useEffect(() => {
    sessionsApi.openSessions().then((sessions) => {
      if (sessions.length !== 1) return
      const s = sessions[0]
      setStationId(s.stationId)
      setCard(s.cardId ? (cards[s.cardId] ?? null) : null)
      setSession(s)
      setQuantity(s.quantity)
      setPhase('working')
    }).catch(() => {})
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const selectLocation = useCallback(async (id: string) => {
    setStationId(id)
    // 1. Resume any in-progress (open) session at this station.
    try {
      const sessions = await sessionsApi.list(id, true)
      if (sessions.length > 0) {
        const s = sessions[0]
        setCard(s.cardId ? (cards[s.cardId] ?? null) : null)
        setSession(s)
        setQuantity(s.quantity)
        setPhase('working')
        return
      }
    } catch { /* fall through */ }
    // 2. Resume a card that was stopped but not yet moved (status = 'done').
    const doneCard = Object.values(cards).find(
      (c) => (c.bins[id]?.count ?? 0) > 0 && c.status === 'done'
    )
    if (doneCard) {
      setCard(doneCard)
      setQuantity(doneCard.bins[id]?.count ?? 1)
      setElapsed(await fetchDoneElapsed(id, doneCard._id))
      setPhase('done')
      return
    }
    setPhase('pick-lot')
  }, [cards])

  const handleSelectLot = useCallback((c: Card | null) => {
    setSelectedCard(c)
    setQuantity(c && stationId ? (c.bins[stationId]?.count ?? 1) : 1)
  }, [stationId])

  const handleStart = useCallback(async () => {
    if (!stationId) return
    const c = selectedCard
    // Card already done (stopped but not moved) — skip straight to move screen.
    if (c?.status === 'done') {
      setCard(c)
      setElapsed(await fetchDoneElapsed(stationId, c._id))
      setPhase('done')
      return
    }
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

  const handleStop = useCallback(async () => {
    if (!session) return
    await sessionsApi.end(session._id, quantity)
    if (card) await updateCard(card._id, { status: 'done' })
    setPhase('done')
  }, [session, card, quantity, updateCard])

  const handleContinue = useCallback(async () => {
    if (!stationId || !card) return
    const s = await sessionsApi.start({ stationId, cardId: card._id, quantity })
    await updateCard(card._id, { status: 'working' })
    setSession(s)
    setElapsedOffset(elapsed)   // timer resumes from where it left off
    setPhase('working')
  }, [stationId, card, quantity, elapsed, updateCard])

  const handleMove = useCallback(async (toStationId: string) => {
    if (!card || !stationId) return
    const fromCount = card.bins[stationId]?.count ?? 0
    const moveQty   = Math.min(quantity, fromCount)
    if (moveQty <= 0) { reset(); return }

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
      flex:      1, display: 'flex', flexDirection: 'column',
      overflow:  'hidden', background: color.bgDeep,
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
          <LocationPicker onSelect={selectLocation} mergeNodeSet={mergeNodeSet} />
        )}
        {phase === 'pick-lot' && stationId && (
          <LotPicker
            stationId={stationId}
            selected={selectedCard}
            quantity={quantity}
            isMergeStation={mergeNodeSet.has(stationId)}
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
            elapsedOffset={elapsedOffset}
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
            onContinue={handleContinue}
            onBack={() => { setCard(null); setSession(null); setElapsed(0); setElapsedOffset(0); setPhase('pick-lot') }}
          />
        )}
      </div>
    </div>
  )
}

// ─── Phase 1: Pick a location ─────────────────────────────────────────────────

function LocationPicker({
  onSelect, mergeNodeSet,
}: {
  onSelect:     (id: string) => void
  mergeNodeSet: Set<string>
}) {
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
          const lots      = lotCounts[s._id] ?? 0
          const active    = openByStation[s._id] ?? 0
          const isMerge   = mergeNodeSet.has(s._id)
          const accent    = s.color ?? color.bluePrimary
          const sideBorder = `1px solid ${active > 0 ? color.statusRunning + '60' : lots > 0 ? accent + '50' : color.border}`
          return (
            <button key={s._id} onClick={() => onSelect(s._id)} style={{
              background:   lots > 0 ? `${accent}18` : color.bgCard,
              borderTop:    sideBorder,
              borderRight:  sideBorder,
              borderBottom: sideBorder,
              borderLeft:   `4px solid ${accent}`,
              borderRadius: size.radiusMd, padding: size.sp5,
              cursor: 'pointer', textAlign: 'left',
              boxShadow: active > 0 ? `0 0 12px ${color.statusRunning}18` : lots > 0 ? `0 0 8px ${accent}20` : shadow.sm,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <div style={{ fontSize: 15, fontWeight: 600, color: color.textPrimary, flex: 1 }}>{s.name}</div>
                {isMerge && (
                  <span style={{
                    fontSize: 8, fontFamily: font.mono, letterSpacing: '0.08em',
                    color: '#8B5CF6', background: '#8B5CF620', border: '1px solid #8B5CF640',
                    borderRadius: size.radiusFull, padding: '1px 5px', flexShrink: 0,
                  }}>
                    MERGE
                  </span>
                )}
              </div>
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
  stationId, selected, quantity, isMergeStation,
  onSelectLot, onSetQuantity, onStart,
}: {
  stationId:      string
  selected:       Card | null
  quantity:       number
  isMergeStation: boolean
  onSelectLot:    (c: Card | null) => void
  onSetQuantity:  (n: number) => void
  onStart:        () => void
}) {
  const stations  = useStationsStore((s) => s.stations)
  const cards     = useCardsStore((s) => s.cards)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const routes    = useProcessesStore((s) => s.routes)
  const fetchAll  = useCardsStore((s) => s.fetchAll)

  const [starting,   setStarting]   = useState(false)
  const [error,      setError]      = useState<string | null>(null)
  const [merging,    setMerging]    = useState(false)
  const [mergeError, setMergeError] = useState<string | null>(null)

  const station = stations[stationId]
  const lots    = Object.values(cards).filter((c) => (c.bins[stationId]?.count ?? 0) > 0)

  // Auto-merge when entering a merge station
  useEffect(() => {
    if (!isMergeStation) return
    setMerging(true)
    setMergeError(null)
    mergeApi.perform(stationId)
      .then(() => fetchAll())
      .catch((e: unknown) => {
        const msg = String(e)
        if (msg.includes('No assembly template')) {
          setMergeError('No assembly template configured for this station.')
        }
        // "not enough units" (400) is expected when precursors are incomplete — not shown as error
      })
      .finally(() => setMerging(false))
  }, [stationId, isMergeStation])   // intentionally not re-running on fetchAll change

  // Identify which lots are assembly cards vs. unconsumed precursors
  const incomingSourceIds = useMemo(() => {
    if (!isMergeStation) return new Set<string>()
    return new Set(Object.values(routes).filter((r) => r.unload === stationId).map((r) => r.load))
  }, [isMergeStation, routes, stationId])

  const assemblyLots  = useMemo(() => lots.filter(
    (c) => templates[c.lotTemplateId]?.startStationId === stationId,
  ), [lots, templates, stationId])

  const precursorLots = useMemo(() => lots.filter((c) => {
    const sid = templates[c.lotTemplateId]?.startStationId
    return sid && incomingSourceIds.has(sid)
  }), [lots, templates, incomingSourceIds])

  // At a normal station show all lots; at a merge station show only assembly lots
  const selectableLots = isMergeStation ? assemblyLots : lots

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
          {isMergeStation
            ? 'Select an assembled lot, then press START'
            : 'Select a lot to work on, then press START'}
        </div>
      </div>

      {/* Merging indicator */}
      {merging && (
        <div style={{
          padding: `${size.sp2} ${size.sp3}`,
          background: '#8B5CF615', border: '1px solid #8B5CF640',
          borderRadius: size.radius, fontSize: 11, color: '#8B5CF6', fontFamily: font.mono,
        }}>
          Merging precursors…
        </div>
      )}

      {/* Merge configuration error */}
      {mergeError && (
        <div style={{
          padding: `${size.sp2} ${size.sp3}`,
          background: `${color.statusFault}18`, border: `1px solid ${color.statusFault}40`,
          borderRadius: size.radius, fontSize: 11, color: color.statusFault,
        }}>
          {mergeError}
        </div>
      )}

      {/* Selectable lot cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
        {selectableLots.map((c) => {
          const tmpl  = templates[c.lotTemplateId]
          const isSel = selected?._id === c._id
          const accent = tmpl?.color ?? color.bluePrimary
          return (
            <div
              key={c._id}
              onClick={() => onSelectLot(isSel ? null : c)}
              style={{
                borderRadius: size.radiusMd,
                outline: isSel ? `2px solid ${accent}` : '2px solid transparent',
                outlineOffset: 2,
                cursor: 'pointer',
                transition: 'outline-color 0.12s',
              }}
            >
              <LotCard card={c} template={tmpl} stationId={stationId} />
            </div>
          )
        })}

        {selectableLots.length === 0 && !merging && (
          <div style={{
            padding: size.sp5, background: color.bgCard, borderRadius: size.radiusMd,
            color: color.textDim, fontSize: 12, textAlign: 'center',
            border: `1px solid ${color.border}`,
          }}>
            {isMergeStation
              ? 'No assemblies ready — waiting for precursors'
              : 'No lots at this location'}
          </div>
        )}
      </div>

      {/* Unconsumed precursor lots — grayed out, not selectable */}
      {isMergeStation && precursorLots.length > 0 && (
        <div>
          <div style={{
            fontSize: 9, fontFamily: font.mono, color: color.textDim,
            letterSpacing: '0.1em', marginBottom: size.sp2,
          }}>
            WAITING FOR MORE PRECURSORS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
            {precursorLots.map((c) => {
              const tmpl  = templates[c.lotTemplateId]
              const count = c.bins[stationId]?.count ?? 0
              return (
                <div key={c._id} style={{
                  background:   color.bgCard,
                  border:       `1px solid ${color.border}`,
                  borderLeft:   `4px solid ${color.textDim}`,
                  borderRadius: size.radiusMd, padding: `${size.sp3} ${size.sp4}`,
                  display: 'flex', alignItems: 'center', gap: size.sp3,
                  opacity: 0.45, pointerEvents: 'none',
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: color.textPrimary }}>
                      {tmpl?.name ?? 'Unknown'}
                      {c.lotNum != null && (
                        <span style={{ color: color.textSecondary, fontFamily: font.mono, fontWeight: 400 }}> #{c.lotNum}</span>
                      )}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ fontFamily: font.mono, fontSize: 14, fontWeight: 700, color: color.textPrimary }}>{count}</div>
                    <div style={{ fontSize: 9, color: color.textDim }}>units</div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Quantity — shown only when a card is selected */}
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

      {/* API error */}
      {error && (
        <div style={{
          background: `${color.statusFault}18`, border: `1px solid ${color.statusFault}40`,
          borderRadius: size.radius, padding: `${size.sp2} ${size.sp3}`,
          fontSize: 11, color: color.statusFault,
        }}>
          {error}
        </div>
      )}

      {/* START / MOVE */}
      {selected !== null && (() => {
        const isDone   = selected.status === 'done'
        const btnColor = isDone ? color.bluePrimary : color.statusRunning
        return (
          <button
            onClick={doStart}
            disabled={starting}
            style={{
              width: '100%', padding: `${size.sp5} 0`,
              background:   starting ? `${btnColor}40` : btnColor,
              border:       'none', borderRadius: size.radiusMd,
              color:        '#fff', fontFamily: font.mono,
              fontSize:     20, fontWeight: 700, letterSpacing: '0.12em',
              cursor:       starting ? 'not-allowed' : 'pointer',
              opacity:      starting ? 0.7 : 1,
              boxShadow:    `0 4px 20px ${btnColor}40`,
              transition:   'all 0.15s ease',
              marginTop:    size.sp2,
            }}
          >
            {isDone ? 'MOVE' : starting ? 'STARTING…' : 'START'}
          </button>
        )
      })()}
    </div>
  )
}

// ─── Phase 3: Working + timer ─────────────────────────────────────────────────

function WorkingPanel({
  session, card, stationId, quantity, elapsed, elapsedOffset,
  onSetQuantity, onElapsed, onStop,
}: {
  session:       WorkSession
  card:          Card | null
  stationId:     string
  quantity:      number
  elapsed:       number
  elapsedOffset: number
  onSetQuantity: (n: number) => void
  onElapsed:     (n: number) => void
  onStop:        () => void
}) {
  const stations  = useStationsStore((s) => s.stations)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const [stopping, setStopping] = useState(false)

  // Ensure the ISO string is treated as UTC — Motor/Pydantic may omit the Z suffix.
  const startedAtStr = session.startedAt
  const startedAt = new Date(
    startedAtStr.endsWith('Z') || startedAtStr.includes('+') ? startedAtStr : startedAtStr + 'Z'
  )

  useEffect(() => {
    const tick = () => onElapsed(elapsedOffset + Math.max(0, differenceInSeconds(new Date(), startedAt)))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [session.startedAt, elapsedOffset])

  const station  = stations[stationId]
  const tmpl     = card ? templates[card.lotTemplateId] : null
  const timeStr  = formatElapsed(elapsed)

  const doStop = async () => { setStopping(true); try { await onStop() } finally { setStopping(false) } }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: size.sp6, paddingTop: size.sp8 }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 13, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>WORKING AT</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: color.textPrimary, marginTop: 4 }}>{station?.name}</div>
      </div>

      {card && (
        <div style={{ width: '100%', maxWidth: 320 }}>
          <LotCard card={card} template={tmpl ?? undefined} stationId={stationId} />
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
  card, stationId, quantity, elapsed, onMove, onContinue, onBack,
}: {
  card:        Card | null
  stationId:   string
  quantity:    number
  elapsed:     number
  onMove:      (toStationId: string) => void
  onContinue:  () => Promise<void>
  onBack:      () => void
}) {
  const stations  = useStationsStore((s) => s.stations)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const routes    = useProcessesStore((s) => s.routes)
  const [moving,     setMoving]     = useState(false)
  const [continuing, setContinuing] = useState(false)

  const station = stations[stationId]
  const tmpl    = card ? templates[card.lotTemplateId] : null

  const timeStr = formatElapsed(elapsed)

  const nextStation = useMemo(() => {
    const ids = getValidDestinations(stationId, routes)
    return ids.length > 0 ? stations[ids[0]] : null
  }, [stationId, routes, stations])

  const doMove = async () => {
    if (!nextStation) return
    setMoving(true)
    try { await onMove(nextStation._id) } finally { setMoving(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: size.sp6, paddingTop: size.sp8 }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 8, filter: 'drop-shadow(0 0 12px #10B981)' }}>✓</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: color.statusRunning }}>DONE</div>
        <div style={{ fontSize: 13, color: color.textSecondary, marginTop: 4 }}>{station?.name}</div>
      </div>

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

      {card && (
        <div style={{ fontSize: 12, color: color.textSecondary, textAlign: 'center' }}>
          {tmpl?.name ?? 'Lot'}
          {card.lotNum != null && <span style={{ fontFamily: font.mono }}> #{card.lotNum}</span>}
        </div>
      )}

      {nextStation && (
        <button
          onClick={doMove}
          disabled={moving}
          style={{
            width: '100%', maxWidth: 320, padding: `${size.sp5} 0`,
            background:   moving ? `${color.bluePrimary}40` : color.bluePrimary,
            border: 'none', borderRadius: size.radiusMd,
            color: '#fff', fontFamily: font.mono,
            fontSize: 20, fontWeight: 700, letterSpacing: '0.12em',
            cursor: moving ? 'not-allowed' : 'pointer',
            boxShadow: `0 4px 20px ${color.bluePrimary}40`,
            transition: 'all 0.15s ease',
          }}
        >
          {moving ? 'MOVING…' : `MOVE → ${nextStation.name}`}
        </button>
      )}

      <button
        onClick={async () => { setContinuing(true); try { await onContinue() } finally { setContinuing(false) } }}
        disabled={continuing}
        style={{
          width: '100%', maxWidth: 320, padding: `${size.sp4} 0`,
          background:   continuing ? `${color.statusRunning}40` : 'transparent',
          border:       `1px solid ${color.statusRunning}60`,
          borderRadius: size.radiusMd,
          color:        color.statusRunning, fontFamily: font.mono,
          fontSize:     16, fontWeight: 700, letterSpacing: '0.1em',
          cursor:       continuing ? 'not-allowed' : 'pointer',
          opacity:      continuing ? 0.7 : 1,
          transition:   'all 0.15s ease',
        }}
      >
        {continuing ? 'STARTING…' : 'CONTINUE WORKING'}
      </button>

      <button onClick={onBack} style={{
        background: 'none', border: `1px solid ${color.border}`,
        borderRadius: size.radius, color: color.textSecondary,
        cursor: 'pointer', fontSize: 12, padding: '6px 20px',
      }}>
        Back to lot view
      </button>
    </div>
  )
}
