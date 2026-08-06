import { create } from 'zustand'

/** Which pieces of shared screen chrome are on screen right now.
 *
 * Bottom-centre is contested ground — the daily tip and the undo bar both
 * live there, and this corner has already had one collision resolved by
 * floating a control 148px into the view. Components that own an edge
 * register here so the others can stack above instead of covering or dodging
 * blind.
 */
interface ChromeState {
  undoBarVisible: boolean
  setUndoBarVisible: (v: boolean) => void
}

export const useChromeStore = create<ChromeState>()((set) => ({
  undoBarVisible: false,
  setUndoBarVisible: (v) => set({ undoBarVisible: v }),
}))
