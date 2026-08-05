import { create } from 'zustand'
import { globalSettingsApi, defaultWorkHours, type GlobalSettingsData } from '../api/globalSettings.api'
import { LANGUAGE_CODES } from '../i18n/languages'

interface GlobalSettingsState {
  settings: GlobalSettingsData
  loading:  boolean
  fetch:    () => Promise<void>
  update:   (data: Partial<GlobalSettingsData>) => Promise<void>
}

export const useGlobalSettingsStore = create<GlobalSettingsState>((set) => ({
  settings: { timezone: 'UTC', workHours: defaultWorkHours(), showCycleArc: false,
              orderTracking: false, orderTrackingSteps: true,
              supportedLanguages: [...LANGUAGE_CODES] },
  loading:  false,

  fetch: async () => {
    set({ loading: true })
    try {
      const s = await globalSettingsApi.get()
      set({ settings: s })
    } finally {
      set({ loading: false })
    }
  },

  update: async (data) => {
    const s = await globalSettingsApi.update(data)
    set({ settings: s })
  },
}))
