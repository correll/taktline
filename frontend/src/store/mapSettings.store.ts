import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { devtools } from 'zustand/middleware'
import type { MapSettingsData } from '../api/mapSettings.api'
import { mapSettingsApi } from '../api/mapSettings.api'

interface MapSettingsState {
  settings: MapSettingsData | null
  loading:  boolean

  fetch:  ()                                => Promise<void>
  update: (patch: Partial<MapSettingsData>) => Promise<void>
  upload: (file: File)                      => Promise<string>
}

export const useMapSettingsStore = create<MapSettingsState>()(
  devtools(
    immer((set) => ({
      settings: null,
      loading:  false,

      fetch: async () => {
        set((s) => { s.loading = true })
        try {
          const data = await mapSettingsApi.get()
          set((s) => { s.settings = data; s.loading = false })
        } catch {
          set((s) => { s.loading = false })
        }
      },

      update: async (patch) => {
        const data = await mapSettingsApi.update(patch)
        set((s) => { s.settings = data })
      },

      upload: async (file) => {
        const { url } = await mapSettingsApi.uploadFloorPlan(file)
        // Fetch fresh settings so the store reflects the new URL
        const data = await mapSettingsApi.get()
        set((s) => { s.settings = data })
        return url
      },
    })),
    { name: 'veridion/mapSettings' }
  )
)
