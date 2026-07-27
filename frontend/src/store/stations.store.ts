import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { devtools } from 'zustand/middleware'
import type { Station } from '../models'
import { stationsApi } from '../api/stations.api'
import { loadSlice, saveSlice } from './offlineCache'

interface StationsState {
  stations:  Record<string, Station>
  favorites: Record<string, true>   // current user's favorite station ids
  loading:   boolean
  error:     string | null

  fetchAll: ()                                                               => Promise<void>
  create:   (body: Omit<Station, '_id' | 'createdAt' | 'updatedAt'>)        => Promise<Station>
  update:   (id: string, patch: Partial<Station>)                           => Promise<Station>
  remove:   (id: string)                                                     => Promise<void>
  // Local-only position write (no API) — lets routes/heatmap follow a node
  // mid-drag; the caller commits via update() on release.
  nudgePosition: (id: string, x: number, y: number)                          => void

  fetchFavorites: ()                                                         => Promise<void>
  toggleFavorite: (id: string)                                               => Promise<void>
}

export const useStationsStore = create<StationsState>()(
  devtools(
    immer((set, get) => ({
      stations:  {},
      favorites: {},
      loading:   false,
      error:     null,

      fetchAll: async () => {
        set((s) => { s.loading = true; s.error = null })
        try {
          const list = await stationsApi.list()
          set((s) => {
            s.stations = Object.fromEntries(list.map((st) => [st._id, st]))
            s.loading = false
          })
          saveSlice('stations', list)
        } catch (e) {
          const cached = loadSlice<Station[]>('stations')
          set((s) => {
            if (cached) s.stations = Object.fromEntries(cached.map((st) => [st._id, st]))
            s.loading = false
            s.error = cached ? null : String(e)
          })
        }
      },

      create: async (body) => {
        const station = await stationsApi.create(body)
        set((s) => { s.stations[station._id] = station })
        return station
      },

      update: async (id, patch) => {
        const station = await stationsApi.update(id, patch)
        set((s) => { s.stations[id] = station })
        return station
      },

      remove: async (id) => {
        await stationsApi.remove(id)
        set((s) => { delete s.stations[id] })
      },

      nudgePosition: (id, x, y) => {
        set((s) => {
          const st = s.stations[id]
          if (st) { st.position.x = x; st.position.y = y }
        })
      },

      fetchFavorites: async () => {
        try {
          const ids = await stationsApi.favorites()
          set((s) => { s.favorites = Object.fromEntries(ids.map((id) => [id, true as const])) })
        } catch { /* favorites are cosmetic — never block the picker */ }
      },

      toggleFavorite: async (id) => {
        const willFavorite = !get().favorites[id]
        // Optimistic: hearts must feel instant on a shop-floor tablet.
        set((s) => { if (willFavorite) s.favorites[id] = true; else delete s.favorites[id] })
        try {
          await stationsApi.setFavorite(id, willFavorite)
        } catch {
          set((s) => { if (willFavorite) delete s.favorites[id]; else s.favorites[id] = true })
        }
      },
    })),
    { name: 'taktline/stations' }
  )
)
