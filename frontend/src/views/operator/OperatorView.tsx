import { useT } from '../../i18n'
import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Heart, ScanLine } from 'lucide-react'
import { useStationsStore, useCardsStore, useProcessesStore } from '../../store'
import { sessionsApi, type WorkSession } from '../../api/sessions.api'
import { color, font, size, shadow } from '../../theme/tokens'
import type { Card, Station } from '../../models'
import { formatDistanceToNow, differenceInSeconds } from 'date-fns'
import { getValidDestinations } from '../lots/LotsView'
import { mergeNodes } from '../../domain/graph'
import { mergeApi, type MergePreview } from '../../api/merge.api'
import { cardsApi } from '../../api/cards.api'
import LotCard, { lotLabel } from '../../components/lots/LotCard'
import CycleArc from '../../components/operator/CycleArc'
import { integrationProvider } from '../../domain/integrations'
import { useGlobalSettingsStore } from '../../store/globalSettings.store'
const ScanSheet = React.lazy(() => import('../../components/scan/ScanSheet'))

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
// 1. pick-station  → pick your station
// 2. pick-lot       → see lots at that station, tap one
// 3. working        → lot selected + START button → timer running → STOP button
// 4. done           → timer shows final time + MOVE button

type Phase = 'pick-station' | 'pick-lot' | 'working' | 'done'

export default function OperatorView() {
  const [phase,         setPhase]         = useState<Phase>('pick-station')
  const [stationId,     setStationId]     = useState<string | null>(null)
  const [card,          setCard]          = useState<Card | null>(null)
  const [session,       setSession]       = useState<WorkSession | null>(null)
  const [elapsed,       setElapsed]       = useState(0)
  const [elapsedOffset, setElapsedOffset] = useState(0)

  const cards       = useCardsStore((s) => s.cards)
  const routes      = useProcessesStore((s) => s.routes)
  const templates   = useProcessesStore((s) => s.lotTemplates)
  const setStatus   = useCardsStore((s) => s.setStatus)
  const upsertCard  = useCardsStore((s) => s.upsert)

  const mergeNodeSet = useMemo(
    () => mergeNodes(Object.values(routes)),
    [routes],
  )

  const [selectedCard, setSelectedCard] = useState<Card | null>(null)
  const [quantity,     setQuantity]     = useState(1)

  // Scan-to-advance. A scan never moves anything on its own: it resolves the
  // label to a lot and asks. The label is printed once and then lives on a
  // physical card that can be picked up at the wrong bench, and an advance is
  // not free to undo — a merge consumes precursors, a split mints new cards.
  // One tap to confirm is cheap next to that.
  const [scanning,  setScanning]  = useState(false)
  const [scanned,   setScanned]   = useState<{ card: Card; from: string; to?: string } | null>(null)
  const [scanError, setScanError] = useState<string | null>(null)

  const handleScan = useCallback((text: string) => {
    setScanning(false)
    const card = cards[text] ?? Object.values(cards).find((c) => c._id === text)
    if (!card) {
      setScanError('That label does not match any lot on this line — it may belong to another company, or the lot may already have been consumed by a merge.')
      return
    }
    const from = Object.entries(card.bins).find(([, b]) => (b?.count ?? 0) > 0)?.[0]
    if (!from) {
      setScanError('That lot has no units on the floor right now.')
      return
    }
    const [to] = getValidDestinations(from, routes, card.processId)
    setScanError(null)
    setScanned({ card, from, to })
  }, [cards, routes])

  const confirmScan = useCallback(async () => {
    if (!scanned?.to) return
    const { card, from, to } = scanned
    const qty = card.bins[from]?.count ?? 1
    try {
      const moved = await cardsApi.advance(card._id, from, to, qty)
      upsertCard(moved)
      setScanned(null)
    } catch (e) {
      setScanError(String((e as { message?: string })?.message ?? e))
      setScanned(null)
    }
  }, [scanned, upsertCard])

  const reset = useCallback(() => {
    setPhase('pick-station')
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

  // Deep link: /operator?station=…&card=… — where the QR on a lot card lands an
  // operator who scanned it. It runs after `cards` has loaded, because the whole
  // point is arriving with that lot already picked; with an empty store
  // `selectLocation` would drop the preference and show a bare list.
  const [searchParams, setSearchParams] = useSearchParams()
  const allStations = useStationsStore((st) => st.stations)
  const deepLinked = useRef(false)
  useEffect(() => {
    if (deepLinked.current || phase !== 'pick-station') return
    const station = searchParams.get('station')
    if (!station || !allStations[station]) return
    if (!Object.keys(cards).length) return
    deepLinked.current = true
    const wanted = searchParams.get('card')
    void selectLocation(station, wanted ? (cards[wanted] ?? null) : null)
    // Drop the parameters once used, so a refresh or a back-navigation does not
    // silently re-open somebody else's lot.
    setSearchParams({}, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cards, allStations, searchParams, phase])

  const selectLocation = useCallback(async (id: string, preferred?: Card | null) => {
    setStationId(id)
    setSelectedCard(null)
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
    // 2. Resume a card that was stopped but not yet moved (status = 'done') —
    //    preferring the card the worker tapped to get here (feeding-station jump).
    //    At a merge station only an assembly qualifies: a precursor waiting to be
    //    consumed is not this station's finished work, and greeting the worker
    //    with "DONE → move it downstream" for one would push an unmerged part
    //    into finished goods. Same rule the lot picker applies.
    const atHere = (c: Card | null | undefined) => (c?.bins[id]?.count ?? 0) > 0
    const workableHere = (c: Card | null | undefined) => {
      if (!c || !atHere(c)) return false
      if (!mergeNodeSet.has(id)) return true
      const origin = templates[c.lotTemplateId]?.startStationId
      // Unknown template → can't prove it's an assembly, so don't resume it.
      return origin != null && origin === id
    }
    const doneCard =
      (preferred && preferred.status === 'done' && workableHere(preferred) ? preferred : null)
      ?? Object.values(cards).find((c) => workableHere(c) && c.status === 'done')
    if (doneCard) {
      setCard(doneCard)
      setQuantity(doneCard.bins[id]?.count ?? 1)
      setElapsed(await fetchDoneElapsed(id, doneCard._id))
      setPhase('done')
      return
    }
    // 3. Otherwise pick-lot — with the tapped card pre-selected if it's here.
    if (preferred && atHere(preferred)) {
      setSelectedCard(preferred)
      setQuantity(preferred.bins[id]?.count ?? 1)
    }
    setPhase('pick-lot')
  }, [cards, templates, mergeNodeSet])

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
    if (c) await setStatus(c._id, 'working')
    setSession(s)
    setPhase('working')
  }, [stationId, selectedCard, quantity, setStatus])

  const handleStop = useCallback(async () => {
    if (!session) return
    await sessionsApi.end(session._id, quantity)
    if (card) await setStatus(card._id, 'done')
    setPhase('done')
  }, [session, card, quantity, setStatus])

  const handleContinue = useCallback(async () => {
    if (!stationId || !card) return
    const s = await sessionsApi.start({ stationId, cardId: card._id, quantity })
    await setStatus(card._id, 'working')
    setSession(s)
    setElapsedOffset(elapsed)   // timer resumes from where it left off
    setPhase('working')
  }, [stationId, card, quantity, elapsed, setStatus])

  // One or several route-constrained advances (allowed for operators and
  // admins). Several happen when a choice station's units are dealt across
  // destinations — each advance is its own transaction, in the given order,
  // so a failure partway leaves the earlier moves committed and visible.
  const handleMove = useCallback(async (moves: { toStationId: string; quantity: number }[]) => {
    if (!card || !stationId) return
    let remaining = Math.min(quantity, card.bins[stationId]?.count ?? 0)
    try {
      for (const m of moves) {
        const q = Math.min(m.quantity, remaining)
        if (q <= 0) continue
        const moved = await cardsApi.advance(card._id, stationId, m.toStationId, q)
        // Store the response directly: if the follow-up status call or the WS
        // echo is lost, the local board still reflects the committed move.
        upsertCard(moved)
        remaining -= q
      }
      await setStatus(card._id, 'idle')
    } catch (e) {
      console.error('advance failed:', e)
    }
    reset()
  }, [card, stationId, quantity, setStatus, upsertCard, reset])

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
        <button
          onClick={() => { setScanError(null); setScanning(true) }}
          title="Scan a printed lot label to advance it"
          style={{
            marginLeft: 'auto', background: 'none',
            border: `1px solid ${color.border}`, borderRadius: size.radius,
            color: color.textSecondary, cursor: 'pointer', fontSize: 11,
            padding: '3px 10px', display: 'flex', alignItems: 'center', gap: 5,
          }}>
          <ScanLine size={13} /> Scan
        </button>
        {phase !== 'pick-station' && (
          <button onClick={reset} style={{
            background: 'none',
            border: `1px solid ${color.border}`, borderRadius: size.radius,
            color: color.textSecondary, cursor: 'pointer', fontSize: 11, padding: '3px 10px',
          }}>
            ← Stations
          </button>
        )}
      </div>

      {scanError && (
        <div style={{
          padding: `${size.sp3} ${size.sp6}`, background: `${color.statusFault}18`,
          color: color.statusFault, fontSize: 12.5, lineHeight: 1.5,
          display: 'flex', alignItems: 'flex-start', gap: size.sp3,
        }}>
          <span style={{ flex: 1 }}>{scanError}</span>
          <button onClick={() => setScanError(null)} style={{
            background: 'none', border: 'none', color: color.statusFault,
            cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0,
          }}>×</button>
        </div>
      )}

      <div style={{ flex: 1, overflowY: 'auto', padding: size.sp4 }}>
        {scanning && (
          <React.Suspense fallback={null}>
            <ScanSheet onScan={handleScan} onClose={() => setScanning(false)} />
          </React.Suspense>
        )}
        {scanned && <ScanConfirm scanned={scanned} onConfirm={confirmScan}
                                 onCancel={() => setScanned(null)} />}
        {phase === 'pick-station' && (
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
            onGoToStation={(id, preferred) => selectLocation(id, preferred)}
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

// ─── Phase 1: Pick a station ─────────────────────────────────────────────────

function LocationPicker({
  onSelect, mergeNodeSet,
}: {
  onSelect:     (id: string) => void
  mergeNodeSet: Set<string>
}) {
  const stations       = useStationsStore((s) => s.stations)
  const favorites      = useStationsStore((s) => s.favorites)
  const toggleFavorite = useStationsStore((s) => s.toggleFavorite)
  const fetchFavorites = useStationsStore((s) => s.fetchFavorites)
  const cards    = useCardsStore((s) => s.cards)
  const [openSessions, setOpenSessions] = useState<WorkSession[]>([])

  useEffect(() => {
    sessionsApi.openSessions().then(setOpenSessions).catch(() => {})
    fetchFavorites()
  }, [fetchFavorites])

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

  // Favorites first, then alphabetical — a worker's own stations lead the grid.
  const list = Object.values(stations).sort((a, b) => {
    const favDiff = (favorites[a._id] ? 0 : 1) - (favorites[b._id] ? 0 : 1)
    return favDiff !== 0 ? favDiff : a.name.localeCompare(b.name)
  })

  if (list.length === 0) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 300, gap: 12 }}>
      <span style={{ fontFamily: font.mono, fontSize: 12, color: color.textDim, letterSpacing: '0.1em' }}>NO STATIONS CONFIGURED</span>
    </div>
  )

  return (
    <div>
      <div style={{ fontSize: 11, fontFamily: font.mono, color: color.textDim, letterSpacing: '0.1em', marginBottom: size.sp4 }}>
        SELECT YOUR STATION
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: size.sp3 }}>
        {list.map((s) => {
          const lots      = lotCounts[s._id] ?? 0
          const active    = openByStation[s._id] ?? 0
          const isMerge   = mergeNodeSet.has(s._id)
          const accent    = s.color ?? color.lotBlue
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
                {/* span, not button: the tile itself is already a <button> */}
                <span
                  role="button"
                  aria-label={favorites[s._id] ? 'Remove from favorites' : 'Add to favorites'}
                  title={favorites[s._id] ? 'Remove from favorites' : 'Add to favorites'}
                  onClick={(e) => { e.stopPropagation(); toggleFavorite(s._id) }}
                  style={{ display: 'flex', alignItems: 'center', padding: 4, margin: -4, flexShrink: 0, cursor: 'pointer' }}
                >
                  <Heart
                    size={15}
                    color={favorites[s._id] ? color.bluePrimary : color.textDim}
                    fill={favorites[s._id] ? color.bluePrimary : 'none'}
                    strokeWidth={1.8}
                  />
                </span>
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
  onSelectLot, onSetQuantity, onStart, onGoToStation,
}: {
  stationId:      string
  selected:       Card | null
  quantity:       number
  isMergeStation: boolean
  onSelectLot:    (c: Card | null) => void
  onSetQuantity:  (n: number) => void
  onStart:        () => void
  onGoToStation:  (id: string, preferred?: Card | null) => void
}) {
  const t = useT()
  const stations       = useStationsStore((s) => s.stations)
  const cards          = useCardsStore((s) => s.cards)
  const templates      = useProcessesStore((s) => s.lotTemplates)
  const routes         = useProcessesStore((s) => s.routes)
  const fetchAll       = useCardsStore((s) => s.fetchAll)
  const fetchProcesses = useProcessesStore((s) => s.fetchAll)

  const [starting,    setStarting]    = useState(false)
  const [error,       setError]       = useState<string | null>(null)
  const [merging,     setMerging]     = useState(false)
  const [mergeError,  setMergeError]  = useState<string | null>(null)
  const [selectedPre, setSelectedPre] = useState<Set<string>>(new Set())
  const [preview,     setPreview]     = useState<MergePreview | null>(null)
  // Which line the worker is assembling, when several merge at this bench.
  // Null = let the server pick the one that can actually be built now.
  const [mergeProc,   setMergeProc]   = useState<string | null>(null)

  const station = stations[stationId]
  const lots    = Object.values(cards).filter((c) => (c.bins[stationId]?.count ?? 0) > 0)

  // Merging is deliberate, but it opens as a proposal: the preview names the
  // lots this station would consume on its own and they arrive pre-selected,
  // so the worker confirms or adjusts rather than choosing between a blind
  // AUTO and rebuilding the recipe by hand.
  const applyPreview = useCallback((p: MergePreview) => {
    setPreview(p)
    setSelectedPre(new Set(p.requirements.flatMap((r) => r.proposedCardIds)))
  }, [])

  useEffect(() => {
    if (!isMergeStation) return
    mergeApi.preview(stationId, mergeProc ?? undefined).then(applyPreview).catch(() => {})
  }, [stationId, isMergeStation, mergeProc, applyPreview])

  const doMerge = async (cardIds?: string[]) => {
    setMerging(true)
    setMergeError(null)
    try {
      await mergeApi.perform(stationId, cardIds, mergeProc ?? undefined)
      setSelectedPre(new Set())
      // Refetch templates too — the merge may have auto-provisioned the assembly
      // template server-side; without it in the store the new assembly card
      // couldn't be classified and the station looked empty.
      await Promise.all([fetchAll(), fetchProcesses()])
      mergeApi.preview(stationId).then(applyPreview).catch(() => {})
    } catch (e: unknown) {
      setMergeError(String(e))
    } finally {
      setMerging(false)
    }
  }

  const togglePre = (id: string) => {
    setSelectedPre((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  // Identify which lots are assembly cards vs. unconsumed precursors
  const incomingSourceIds = useMemo(() => {
    if (!isMergeStation) return new Set<string>()
    return new Set(Object.values(routes).filter((r) => r.unload === stationId).map((r) => r.load))
  }, [isMergeStation, routes, stationId])

  const precursorLots = useMemo(() => lots.filter((c) => {
    const sid = templates[c.lotTemplateId]?.startStationId
    return sid && incomingSourceIds.has(sid)
  }), [lots, templates, incomingSourceIds])

  // At a merge station a card is only workable once we can PROVE it's an
  // assembly. A card whose template isn't in the store yet can't be classified
  // — treating it as workable let operators start on unmerged precursors, so
  // those wait in a brief "identifying" state instead (the template cache
  // self-heals via ensureTemplates within a second or two).
  const unclassifiedLots = useMemo(() => {
    if (!isMergeStation) return []
    return lots.filter((c) => !templates[c.lotTemplateId])
  }, [isMergeStation, lots, templates])

  const selectableLots = useMemo(() => {
    if (!isMergeStation) return lots
    const excluded = new Set([...precursorLots, ...unclassifiedLots].map((c) => c._id))
    return lots.filter((c) => !excluded.has(c._id))
  }, [isMergeStation, lots, precursorLots, unclassifiedLots])

  // Lots still at the stations that feed this one — the material a worker may
  // need to go fetch. Tapping one switches the operator view to that station.
  const feedingLots = useMemo(() => {
    const feedIds = [...new Set(
      Object.values(routes).filter((r) => r.unload === stationId).map((r) => r.load)
    )]
    return feedIds.flatMap((fid) =>
      Object.values(cards)
        .filter((c) => (c.bins[fid]?.count ?? 0) > 0)
        .map((c) => ({ card: c, feedStationId: fid })))
  }, [routes, cards, stationId])

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
          {isMergeStation ? t('op.selectPrecursors') : t('op.selectLot')}
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
          const accent = tmpl?.color ?? color.lotBlue
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

        {unclassifiedLots.length > 0 && (
          <div style={{
            padding: `${size.sp2} ${size.sp3}`, background: color.bgCard,
            border: `1px dashed ${color.border}`, borderRadius: size.radiusMd,
            color: color.textDim, fontSize: 11, fontFamily: font.mono,
          }}>
            Identifying {unclassifiedLots.length} lot{unclassifiedLots.length !== 1 ? 's' : ''}…
          </div>
        )}

        {selectableLots.length === 0 && unclassifiedLots.length === 0 && !merging && (
          <div style={{
            padding: size.sp5, background: color.bgCard, borderRadius: size.radiusMd,
            color: color.textDim, fontSize: 12, textAlign: 'center',
            border: `1px solid ${color.border}`,
          }}>
            {isMergeStation
              ? 'No assemblies ready — waiting for precursors'
              : 'No lots at this station'}
          </div>
        )}
      </div>

      {/* Precursor lots — worker selects which cards to merge */}
      {isMergeStation && precursorLots.length > 0 && (
        <div>
          <div style={{
            fontSize: 9, fontFamily: font.mono, color: color.textDim,
            letterSpacing: '0.1em', marginBottom: size.sp2,
          }}>
            PRECURSORS HERE — SELECT, THEN MERGE
          </div>
          {/* Which line is being assembled. Two chemistries can share a bench,
              and the recipe is meaningless without saying whose it is. */}
          {preview && preview.processes.length > 1 && (
            <div style={{ display: 'flex', gap: 6, marginBottom: size.sp2 }}>
              {preview.processes.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setMergeProc(p.id)}
                  style={{
                    flex: 1, padding: `${size.sp2} ${size.sp3}`, borderRadius: size.radius,
                    background: preview.processId === p.id ? '#8B5CF622' : 'transparent',
                    border: `1px solid ${preview.processId === p.id ? '#8B5CF6' : color.border}`,
                    color: preview.processId === p.id ? color.textPrimary : color.textSecondary,
                    fontSize: 12, fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  {p.name}
                </button>
              ))}
            </div>
          )}
          {preview && preview.requirements.length > 0 && (
            <div style={{ fontSize: 10, color: color.textDim, fontFamily: font.mono, marginBottom: size.sp2 }}>
              1 {preview.assemblyTemplateName ?? 'assembly'} needs {preview.requirements
                .map((r) => `${r.requiredPerAssembly} × ${stations[r.sourceStationId]?.name ?? '?'}`)
                .join('  +  ')}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
            {precursorLots.map((c) => {
              const tmpl  = templates[c.lotTemplateId]
              const count = c.bins[stationId]?.count ?? 0
              const isSel = selectedPre.has(c._id)
              const accent = tmpl?.color ?? '#8B5CF6'
              return (
                <div
                  key={c._id}
                  onClick={() => togglePre(c._id)}
                  style={{
                    background:   isSel ? '#8B5CF615' : color.bgCard,
                    border:       `1px solid ${isSel ? '#8B5CF680' : color.border}`,
                    borderLeft:   `4px solid ${accent}`,
                    borderRadius: size.radiusMd, padding: `${size.sp3} ${size.sp4}`,
                    display: 'flex', alignItems: 'center', gap: size.sp3,
                    cursor: 'pointer', transition: 'border-color 0.12s, background 0.12s',
                  }}
                >
                  {/* selection check */}
                  <div style={{
                    width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
                    border: `2px solid ${isSel ? '#8B5CF6' : color.border}`,
                    background: isSel ? '#8B5CF6' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#fff', fontSize: 11, fontWeight: 700,
                  }}>
                    {isSel ? '✓' : ''}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: color.textPrimary }}>
                      {tmpl?.name ?? 'Unknown'}
                      <span style={{ color: color.textSecondary, fontFamily: font.mono, fontWeight: 400 }}> {lotLabel(c)}</span>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ fontFamily: font.mono, fontSize: 14, fontWeight: 700, color: color.textPrimary }}>{count}</div>
                    <div style={{ fontSize: 9, color: color.textDim }}>{t('op.units')}</div>
                  </div>
                </div>
              )
            })}
          </div>

          {/* MERGE the selection — which opens as the station's own proposal */}
          <div style={{ display: 'flex', gap: size.sp2, marginTop: size.sp3 }}>
            <button
              onClick={() => doMerge([...selectedPre])}
              disabled={merging || selectedPre.size === 0}
              style={{
                flex: 1, padding: `${size.sp3} 0`,
                background: merging || selectedPre.size === 0 ? '#8B5CF630' : '#8B5CF6',
                border: 'none', borderRadius: size.radiusMd,
                color: '#fff', fontFamily: font.mono, fontSize: 14, fontWeight: 700,
                letterSpacing: '0.08em',
                cursor: merging || selectedPre.size === 0 ? 'not-allowed' : 'pointer',
              }}
            >
              {merging ? 'MERGING…' : `MERGE${selectedPre.size > 0 ? ` (${selectedPre.size})` : ''}`}
            </button>
          </div>
        </div>
      )}

      {/* Lots waiting at the stations that feed this one — tap to go fetch */}
      {feedingLots.length > 0 && (
        <div>
          <div style={{
            fontSize: 9, fontFamily: font.mono, color: color.textDim,
            letterSpacing: '0.1em', marginBottom: size.sp2,
          }}>
            AT FEEDING STATIONS — TAP TO GO THERE
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
            {feedingLots.map(({ card: c, feedStationId }) => {
              const tmpl   = templates[c.lotTemplateId]
              const feed   = stations[feedStationId]
              const count  = c.bins[feedStationId]?.count ?? 0
              const accent = tmpl?.color ?? color.lotBlue
              const badge  = c.status === 'done'
                ? { text: 'FINISHED', color: color.statusRunning }
                : c.status === 'working'
                  ? { text: 'IN WORK', color: '#EF9F27' }
                  : null
              return (
                <div
                  key={`${c._id}:${feedStationId}`}
                  onClick={() => onGoToStation(feedStationId, c)}
                  style={{
                    background:   color.bgCard,
                    border:       `1px solid ${color.border}`,
                    borderLeft:   `4px solid ${accent}`,
                    borderRadius: size.radiusMd, padding: `${size.sp3} ${size.sp4}`,
                    display: 'flex', alignItems: 'center', gap: size.sp3,
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: color.textPrimary }}>
                      {tmpl?.name ?? 'Lot'}
                      <span style={{ color: color.textSecondary, fontFamily: font.mono, fontWeight: 400 }}> {lotLabel(c)}</span>
                    </div>
                    <div style={{ fontSize: 10, color: color.textDim, fontFamily: font.mono, marginTop: 2 }}>
                      at {feed?.name ?? '—'}
                    </div>
                  </div>
                  {badge && (
                    <span style={{
                      fontSize: 8, fontFamily: font.mono, letterSpacing: '0.08em', flexShrink: 0,
                      color: badge.color, background: `${badge.color}20`,
                      border: `1px solid ${badge.color}40`,
                      borderRadius: size.radiusFull, padding: '1px 6px',
                    }}>
                      {badge.text}
                    </span>
                  )}
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ fontFamily: font.mono, fontSize: 14, fontWeight: 700, color: color.textPrimary }}>{count}</div>
                    <div style={{ fontSize: 9, color: color.textDim }}>{t('op.units')}</div>
                  </div>
                  <span style={{ color: color.textDim, fontSize: 14, flexShrink: 0 }}>→</span>
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
            {isDone ? t('op.move') : starting ? t('op.starting') : t('op.start')}
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
  const t = useT()
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

  // Pace feedback against the *station's* measured cycle time — opt-in per company,
  // and absent entirely when the station has no measured cycle time to compare to.
  const showCycleArc = useGlobalSettingsStore((g) => g.settings.showCycleArc)
  const [stationCycle, setStationCycle] = useState<number | null>(null)
  useEffect(() => {
    if (!showCycleArc) { setStationCycle(null); return }
    let alive = true
    sessionsApi.stationStats(stationId)
      .then((st) => { if (alive) setStationCycle(st.cycleTimeSec) })
      .catch(() => { if (alive) setStationCycle(null) })
    return () => { alive = false }
  }, [showCycleArc, stationId])

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
        {showCycleArc && stationCycle != null && stationCycle > 0 && (
          <div style={{ marginTop: size.sp4 }}>
            <CycleArc elapsedSec={elapsed} expectedSec={stationCycle * Math.max(1, quantity)} />
          </div>
        )}
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
        {stopping ? t('op.finishing') : t('op.done')}
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
  onMove:      (moves: { toStationId: string; quantity: number }[]) => void
  onContinue:  () => Promise<void>
  onBack:      () => void
}) {
  const t = useT()
  const stations  = useStationsStore((s) => s.stations)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const routes    = useProcessesStore((s) => s.routes)
  const [moving,     setMoving]     = useState(false)
  const [continuing, setContinuing] = useState(false)

  const station = stations[stationId]
  const tmpl    = card ? templates[card.lotTemplateId] : null

  const timeStr = formatElapsed(elapsed)

  // At a split, advancing does not pick one branch — it mints a piece on
  // *every* branch at once (a bar becomes four tubes and an offcut). Naming
  // only the first destination made that look like a choice the operator was
  // making, and hid the fact that one press produces several lots.
  const branchRoutes = useMemo(() => {
    const bound = new Set(Object.values(stations)
      .filter((st) => st.integrationProvider).map((st) => st._id))
    return Object.values(routes).filter((r) =>
      r.load === stationId && !bound.has(r.unload) &&
      (!card?.processId || r.processId === card.processId))
  }, [stationId, routes, stations, card])

  const branches = useMemo(
    () => branchRoutes.map((r) => stations[r.unload]).filter(Boolean),
    [branchRoutes, stations])

  // But not every lot at a many-routed station splits. Two cases move 1:1 and
  // the worker genuinely PICKS the destination:
  //  - the station is declared a **choice** (either/or routing), or
  //  - the lot already wears one of the branches' products (a piece of this
  //    station's own split — setting one aside is a relocation, mirroring the
  //    backend's piece check in cards._split_branches).
  const picksDestination = useMemo(() => {
    if (!card || branchRoutes.length < 2) return false
    if (station?.branchMode === 'choice') return true
    const procRoutes = Object.values(routes).filter((r) => r.processId === card.processId)
    const t = templates[card.lotTemplateId]
    for (const r of branchRoutes) {
      if (r.outputTemplateId != null) {
        if (r.outputTemplateId === card.lotTemplateId) return true
        continue
      }
      const intoMerge = procRoutes.filter((x) => x.unload === r.unload).length >= 2
      const startAt = intoMerge ? stationId : r.unload
      if (t && t.startStationId === startAt) return true
    }
    return false
  }, [card, branchRoutes, station, routes, templates, stationId])

  const nextStation = useMemo(() => {
    if (branches.length > 0) return branches[0]
    const ids = getValidDestinations(stationId, routes, card?.processId)
    return ids.length > 0 ? stations[ids[0]] : null
  }, [branches, stationId, routes, stations, card])

  /** "Weld", or "Modules, Busbars and Cables" when the lot splits. */
  const destinationLabel = useMemo(() => {
    const names = (branches.length > 1 ? branches : nextStation ? [nextStation] : [])
      .map((st) => st.name)
    if (names.length === 0) return ''
    if (names.length === 1) return names[0]
    return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
  }, [branches, nextStation])

  // Where this station hands finished goods to the outside world. The link is
  // drawn on the map but carries no material: sending is an act someone
  // performs when the goods are actually ready to leave, not something that
  // happens because a card arrived somewhere.
  const handoffTo = useMemo(() => {
    const link = Object.values(routes).find((r) => r.load === stationId &&
      stations[r.unload] && stations[r.unload].integrationRole &&
      ['sink', 'both'].includes(stations[r.unload].integrationRole as string))
    return link ? stations[link.unload] : null
  }, [routes, stations, stationId])
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState<string | null>(null)

  const doHandoff = async () => {
    if (!handoffTo || !card) return
    setSending(true)
    try {
      const r = await cardsApi.handoff(card._id, stationId, handoffTo._id, quantity)
      setSent(r.sentTo)
      onBack()
    } finally { setSending(false) }
  }

  // How the worked units are dealt across the destinations, when picking.
  // Defaults to everything down the first branch — the old single-button
  // behaviour — and re-anchors when the lot or its branches change.
  const [alloc, setAlloc] = useState<Record<string, number>>({})
  const branchKey = branches.map((b) => b._id).join('|')
  useEffect(() => {
    if (!picksDestination) return
    const init: Record<string, number> = {}
    branches.forEach((st, i) => { init[st._id] = i === 0 ? quantity : 0 })
    setAlloc(init)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picksDestination, quantity, branchKey])

  const allocTotal = branches.reduce((s, st) => s + (alloc[st._id] ?? 0), 0)
  // Raising a route's count takes units from the other routes when the total
  // would overflow — dealing, not gatekeeping: with everything defaulted onto
  // the first route, a hard clamp would pin every other row at zero.
  const setRow = (id: string, v: number) => {
    setAlloc((a) => {
      const next = { ...a, [id]: Math.max(0, Math.min(v, quantity)) }
      let excess = branches.reduce((s, st) => s + (next[st._id] ?? 0), 0) - quantity
      for (const st of branches) {
        if (excess <= 0) break
        if (st._id === id) continue
        const take = Math.min(next[st._id] ?? 0, excess)
        next[st._id] = (next[st._id] ?? 0) - take
        excess -= take
      }
      return next
    })
  }
  const allTo = (id: string) => {
    const next: Record<string, number> = {}
    branches.forEach((st) => { next[st._id] = st._id === id ? quantity : 0 })
    setAlloc(next)
  }

  const doMove = async (moves: { toStationId: string; quantity: number }[]) => {
    if (moves.length === 0) return
    setMoving(true)
    try { await onMove(moves) } finally { setMoving(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: size.sp6, paddingTop: size.sp8 }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 8, filter: 'drop-shadow(0 0 12px #639922)' }}>✓</div>
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
          <span style={{ fontFamily: font.mono }}> {lotLabel(card)}</span>
        </div>
      )}

      {handoffTo && (
        <button
          onClick={doHandoff}
          disabled={sending}
          style={{
            width: '100%', maxWidth: 320, padding: `${size.sp5} 0`,
            background: sending ? `${integrationProvider(handoffTo.integrationProvider)?.color ?? color.bluePrimary}60`
                                : integrationProvider(handoffTo.integrationProvider)?.color ?? color.bluePrimary,
            border: 'none', borderRadius: size.radiusMd,
            color: integrationProvider(handoffTo.integrationProvider)?.ink ?? '#fff',
            fontFamily: font.mono, fontSize: 17, fontWeight: 700, letterSpacing: '0.08em',
            cursor: sending ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: size.sp3,
          }}
        >
          {sending ? 'SENDING…' : `SEND TO ${handoffTo.name.toUpperCase()}`}
        </button>
      )}
      {handoffTo && (
        <div style={{ fontSize: 11, color: color.textDim, marginTop: -size.sp4, textAlign: 'center', maxWidth: 320 }}>
          This closes the lot out of Taktline and tells{' '}
          {integrationProvider(handoffTo.integrationProvider)?.label}.
        </div>
      )}

      {picksDestination ? (
        <div style={{ width: '100%', maxWidth: 320, display: 'flex', flexDirection: 'column', gap: size.sp3 }}>
          <div style={{ fontSize: 11, color: color.textDim, textAlign: 'center' }}>
            {t('op.wholelot')}
          </div>
          {branches.map((st) => (
            <div
              key={st._id}
              style={{
                display: 'flex', alignItems: 'center', gap: size.sp3,
                background: color.bgCard, border: `1px solid ${color.border}`,
                borderRadius: size.radiusMd, padding: `${size.sp3} ${size.sp4}`,
              }}
            >
              <span style={{
                flex: 1, fontSize: 13.5, fontWeight: 600, color: color.textPrimary,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {st.name}
              </span>
              <input
                type="number" min={0} max={quantity}
                value={alloc[st._id] ?? 0}
                onChange={(e) => setRow(st._id, parseInt(e.target.value, 10) || 0)}
                onFocus={(e) => e.target.select()}
                style={{
                  width: 64, background: color.bgInput, border: `1px solid ${color.border}`,
                  borderRadius: size.radius, color: color.textPrimary, padding: '8px 6px',
                  fontSize: 16, fontFamily: font.mono, textAlign: 'center',
                }}
              />
              <button
                onClick={() => allTo(st._id)}
                style={{
                  background: 'transparent', border: `1px solid ${color.border}`,
                  borderRadius: size.radius, color: color.textSecondary,
                  fontSize: 11, fontFamily: font.mono, letterSpacing: '0.06em',
                  padding: '9px 10px', cursor: 'pointer',
                }}
              >
                ALL
              </button>
            </div>
          ))}
          {allocTotal < quantity && (
            <div style={{ fontSize: 11, color: color.textDim, textAlign: 'center' }}>
              {quantity - allocTotal} unit{quantity - allocTotal !== 1 ? 's' : ''}{' '}
              stay{quantity - allocTotal === 1 ? 's' : ''} at {station?.name}.
            </div>
          )}
          <button
            onClick={() => doMove(branches
              .filter((st) => (alloc[st._id] ?? 0) > 0)
              .map((st) => ({ toStationId: st._id, quantity: alloc[st._id] })))}
            disabled={moving || allocTotal < 1}
            style={{
              width: '100%', padding: `${size.sp5} 0`,
              background:   moving || allocTotal < 1 ? `${color.bluePrimary}40` : color.bluePrimary,
              border: 'none', borderRadius: size.radiusMd,
              color: '#fff', fontFamily: font.mono,
              fontSize: 20, fontWeight: 700, letterSpacing: '0.12em',
              cursor: moving || allocTotal < 1 ? 'not-allowed' : 'pointer',
              boxShadow: `0 4px 20px ${color.bluePrimary}40`,
              transition: 'all 0.15s ease',
            }}
          >
            {moving ? t('op.moving')
                    : t(allocTotal === 1 ? 'op.moveUnits.one' : 'op.moveUnits.many',
                        { n: allocTotal })}
          </button>
        </div>
      ) : nextStation && (
        <button
          onClick={() => doMove([{ toStationId: nextStation._id, quantity }])}
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
          {moving ? t('op.moving') : t('op.moveTo', { dest: destinationLabel })}
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
        {continuing ? t('op.starting') : t('op.continueWorking')}
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


/** What a scan resolved to, and what advancing it would do. Shown before any
 *  move, because a printed label can be picked up anywhere on the floor and an
 *  advance is not trivially reversible. */
function ScanConfirm({ scanned, onConfirm, onCancel }: {
  scanned: { card: Card; from: string; to?: string }
  onConfirm: () => void
  onCancel: () => void
}) {
  const stations = useStationsStore((s) => s.stations)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const { card, from, to } = scanned
  const units = card.bins[from]?.count ?? 0
  const tmpl  = templates[card.lotTemplateId]

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9400, background: 'rgba(0,0,0,0.55)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: size.sp5,
    }}>
      <div style={{
        width: 380, maxWidth: '100%', background: color.bgPanel,
        border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
        boxShadow: shadow.lg, padding: size.sp6,
      }}>
        <div style={{ fontSize: 11, fontFamily: font.mono, color: color.textDim,
                      letterSpacing: '0.1em', marginBottom: size.sp3 }}>
          SCANNED
        </div>
        <div style={{ fontSize: 17, color: color.textPrimary, fontWeight: 500 }}>
          {tmpl?.name ?? 'Lot'} <span style={{ fontFamily: font.mono, fontSize: 13,
            color: color.textSecondary }}>{card.lotNum}</span>
        </div>
        <div style={{ marginTop: size.sp4, fontSize: 14, color: color.textSecondary, lineHeight: 1.7 }}>
          {units} unit{units === 1 ? '' : 's'} at <b style={{ color: color.textPrimary }}>
            {stations[from]?.name ?? 'here'}</b>
          {to
            ? <> → advance to <b style={{ color: color.textPrimary }}>{stations[to]?.name}</b></>
            : <> — no route onward from here, so there is nothing to advance to.</>}
        </div>
        <div style={{ display: 'flex', gap: size.sp3, marginTop: size.sp6 }}>
          <button onClick={onCancel} style={{
            flex: 1, padding: `${size.sp3} 0`, background: 'none',
            border: `1px solid ${color.border}`, borderRadius: size.radius,
            color: color.textSecondary, fontSize: 14, cursor: 'pointer',
          }}>Cancel</button>
          <button onClick={onConfirm} disabled={!to} style={{
            flex: 2, padding: `${size.sp3} 0`, border: 'none', borderRadius: size.radius,
            background: to ? color.bluePrimary : color.border,
            color: to ? '#fff' : color.textDim, fontSize: 14, fontWeight: 600,
            cursor: to ? 'pointer' : 'not-allowed',
          }}>Advance</button>
        </div>
      </div>
    </div>
  )
}
