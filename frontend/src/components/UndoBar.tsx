import { useCallback, useEffect, useState } from 'react'
import { undoApi, type UndoState } from '../api/undo.api'
import { useCardsStore } from '../store/cards.store'
import { useChromeStore } from '../store/chrome.store'
import { useProcessesStore } from '../store/processes.store'
import { useStationsStore } from '../store/stations.store'
import { color, font, shadow, size } from '../theme/tokens'

/**
 * Undo and redo for the graph editor — stations and routes, not lots.
 *
 * A lot card records a physical fact: where the material actually is. Undoing
 * a move would not carry the material back down the shop, so the board would
 * start disagreeing with the floor, which is the one thing it exists not to do.
 * Drawing the line is configuration, and a mis-clicked delete is exactly the
 * kind of mistake software should be able to take back.
 *
 * The stack lives on the server, so these buttons are a view of it rather than
 * the thing itself — they ask what is undoable rather than remembering. That is
 * what keeps them right when two people edit one line from different rooms.
 * A refusal is therefore normal rather than an error, and is shown as a
 * sentence someone can act on rather than a toast saying something failed.
 */

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
const CHORD = isMac ? '⌘Z' : 'Ctrl+Z'
const CHORD_REDO = isMac ? '⇧⌘Z' : 'Ctrl+Y'

export function UndoBar() {
  const [state, setState] = useState<UndoState | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const cards = useCardsStore((s) => s.cards)
  const fetchCards = useCardsStore((s) => s.fetchAll)
  const fetchStations = useStationsStore((s) => s.fetchAll)
  const fetchGraph = useProcessesStore((s) => s.fetchAll)
  const setUndoBarVisible = useChromeStore((s) => s.setUndoBarVisible)

  const refresh = useCallback(async () => {
    try { setState(await undoApi.state()) } catch { /* offline: leave it as it was */ }
  }, [])

  // Re-ask whenever the board changes — including changes another tablet made,
  // which arrive on the websocket and are exactly the ones that can invalidate
  // an undo.
  useEffect(() => { refresh() }, [refresh, cards])

  const run = useCallback(async (direction: 'undo' | 'redo') => {
    if (busy) return
    setBusy(true); setNote(null)
    try {
      const res = direction === 'undo' ? await undoApi.undo() : await undoApi.redo()
      setNote(`${direction === 'undo' ? 'Undid' : 'Redid'} · ${res.label}`)
      // Undo restores STATIONS and ROUTES — refetching only the cards store
      // left the graph stores stale, and the restore was invisible until a
      // page reload. Cards refetch too: cheap, and a deleted station's column
      // affects what the board shows.
      await Promise.all([fetchStations(), fetchGraph(), fetchCards()])
    } catch (e: any) {
      setNote(e?.response?.data?.detail ?? 'That could not be undone.')
    } finally {
      setBusy(false)
      refresh()
    }
  }, [busy, fetchCards, fetchStations, fetchGraph, refresh])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = isMac ? e.metaKey : e.ctrlKey
      if (!mod) return
      const target = e.target as HTMLElement | null
      // Never steal the chord from a text field — undo means something else
      // there, and taking it would be worse than not having it.
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (target?.isContentEditable) return

      const k = e.key.toLowerCase()
      if (k === 'z' && !e.shiftKey) { e.preventDefault(); run('undo') }
      else if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); run('redo') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [run])

  useEffect(() => {
    if (!note) return
    const t = setTimeout(() => setNote(null), 5200)
    return () => clearTimeout(t)
  }, [note])

  const visible = !!state && (state.canUndo || state.canRedo || !!note)

  // Register with the shared chrome so the daily tip — the other bottom-centre
  // card — stacks above these buttons instead of covering them. That collision
  // was previously dodged by floating this bar 148px into the view, which put
  // a toolbar in the middle of the screen.
  useEffect(() => {
    setUndoBarVisible(visible)
    return () => setUndoBarVisible(false)
  }, [visible, setUndoBarVisible])

  if (!visible) return null

  return (
    <div style={{
      position: 'fixed', left: '50%', transform: 'translateX(-50%)',
      bottom: `calc(${size.sp6} + env(safe-area-inset-bottom, 0px))`, zIndex: 9100,
      display: 'flex', alignItems: 'center', gap: size.sp2,
      background: color.bgPanel, border: `1px solid ${color.border}`,
      borderRadius: size.radiusFull, boxShadow: shadow.lg,
      padding: `6px ${size.sp3}`, maxWidth: 'calc(100vw - 32px)',
    }}>
      <Btn onClick={() => run('undo')} disabled={!state.canUndo || busy}
           title={state.undoLabel ? `Undo: ${state.undoLabel} (${CHORD})` : `Nothing to undo`}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 14 4 9l5-5" /><path d="M4 9h11a5 5 0 0 1 0 10h-4" />
        </svg>
        Undo
      </Btn>
      <Btn onClick={() => run('redo')} disabled={!state.canRedo || busy}
           title={state.redoLabel ? `Redo: ${state.redoLabel} (${CHORD_REDO})` : `Nothing to redo`}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m15 14 5-5-5-5" /><path d="M20 9H9a5 5 0 0 0 0 10h4" />
        </svg>
        Redo
      </Btn>

      {note && (
        <span style={{
          fontSize: 12, color: color.textSecondary, paddingLeft: size.sp2,
          borderLeft: `1px solid ${color.border}`, maxWidth: 380,
        }}>
          {note}
        </span>
      )}
      {!note && (state.undoLabel || state.redoLabel) && (
        <span style={{
          fontSize: 11, fontFamily: font.mono, color: color.textDim, paddingLeft: size.sp2,
          borderLeft: `1px solid ${color.border}`, whiteSpace: 'nowrap',
        }}>
          {state.undoLabel ?? state.redoLabel}
        </span>
      )}
    </div>
  )
}

function Btn({ onClick, disabled, title, children }: {
  onClick: () => void; disabled: boolean; title: string; children: React.ReactNode
}) {
  return (
    <button onClick={onClick} disabled={disabled} title={title} style={{
      display: 'flex', alignItems: 'center', gap: 5,
      background: 'transparent', border: 'none', borderRadius: size.radiusFull,
      padding: '5px 10px', fontSize: 12.5,
      color: disabled ? color.textDisabled : color.textPrimary,
      cursor: disabled ? 'default' : 'pointer',
    }}>
      {children}
    </button>
  )
}
