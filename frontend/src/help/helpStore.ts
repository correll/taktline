import { create } from 'zustand'

export const DISMISS_KEY = 'taktline.help.calloutDismissed'

interface HelpState {
  tourActive: boolean
  tourStep: number
  manualOpen: boolean
  /** Heading id the manual should scroll to when it opens — set by the "read
   *  more" links on measurement tooltips, cleared once the manual has jumped. */
  manualSection: string | null
  calloutDismissed: boolean

  startTour: () => void
  stopTour: () => void
  nextStep: () => void
  backStep: () => void
  goToStep: (n: number) => void

  openManual: (section?: string) => void
  closeManual: () => void

  showCallout: () => void
  dismissCallout: (remember?: boolean) => void
}

export const useHelpStore = create<HelpState>((set) => ({
  tourActive: false,
  tourStep: 0,
  manualOpen: false,
  manualSection: null,
  calloutDismissed: localStorage.getItem(DISMISS_KEY) === '1',

  startTour: () => set({ tourActive: true, tourStep: 0, manualOpen: false, calloutDismissed: true }),
  stopTour: () => set({ tourActive: false }),
  nextStep: () => set((s) => ({ tourStep: s.tourStep + 1 })),
  backStep: () => set((s) => ({ tourStep: Math.max(0, s.tourStep - 1) })),
  goToStep: (n) => set({ tourStep: n }),

  openManual: (section?: string) => set({ manualOpen: true, manualSection: section ?? null }),
  closeManual: () => set({ manualOpen: false, manualSection: null }),

  showCallout: () => set({ calloutDismissed: false }),
  dismissCallout: (remember?: boolean) => {
    // Only "don't show this again" persists across sessions; a plain close is
    // for this session only, so the welcome returns next visit.
    if (remember) localStorage.setItem(DISMISS_KEY, '1')
    else localStorage.removeItem(DISMISS_KEY)
    set({ calloutDismissed: true })
  },
}))
