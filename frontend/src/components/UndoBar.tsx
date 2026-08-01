import { useCallback, useEffect, useState } from 'react'
import { undoApi, type UndoState } from '../api/undo.api'
import { useCardsStore } from '../store/cards.store'
import { color, font, shadow, size } from '../theme/tokens'

/**
 * Undo and redo for lot movements.
 *
 * The stack lives on the server, so the buttons here are a view of it rather
 * than the thing itself — they ask what is undoable rather than remembering.
 * That is what makes them correct on a line where eight tablets share a board:
 * the lot you moved a minute ago may since have been merged at the next bench,
 * and only the server knows.
 *
 * A refusal is therefore normal, not an error, and is shown as a sentence a
 * person standing at a bench can act on ("those lots have moved on since")
 * rather than a toast saying something failed.
 */

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
const CHORD = isMac ? '⌘Z' : 'Ctrl+Z'
const CHORD_REDO = isMac ? '⇧⌘Z' : 'Ctrl+Y'

export function UndoBar() {
  const [state, setState] = useState<UndoState | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const cards = useCardsStore((s) => s.cards)
  const fetchAll = useCardsStore((s) => s.fetchAll)

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
      await fetchAll()
    } catch (e: any) {
      setNote(e?.response?.data?.detail ?? 'That could not be undone.')
    } finally {
      setBusy(false)
      refresh()
    }
  }, [busy, fetchAll, refresh])

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

  if (!state || (!state.canUndo && !state.canRedo && !note)) return null

  return (
    <div style={{
      position: 'fixed', left: '50%', transform: 'translateX(-50%)',
      // Clear of the daily tip, which is also a bottom-centred card and sits
      // at a higher layer — it covered these buttons outright. Floating well
      // above the edge reads as a toolbar rather than a notification, which is
      // what this is: it stays for as long as there is something to undo.
      bottom: `calc(148px + env(safe-area-inset-bottom, 0px))`, zIndex: 9100,
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
