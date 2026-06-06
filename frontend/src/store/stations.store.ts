import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { devtools } from 'zustand/middleware'
import type { Station } from '../models'
import { stationsApi } from '../api/stations.api'

interface StationsState {
  stations: Record<string, Station>
  loading:  boolean
  error:    string | null

  fetchAll: ()                                                               => Promise<void>
  create:   (body: Omit<Station, '_id' | 'createdAt' | 'updatedAt'>)        => Promise<Station>
  update:   (id: string, patch: Partial<Station>)                           => Promise<Station>
  remove:   (id: string)                                                     => Promise<void>
}

export const useStationsStore = create<StationsState>()(
  devtools(
    immer((set) => ({
      stations: {},
      loading:  false,
      error:    null,

      fetchAll: async () => {
        set((s) => { s.loading = true; s.error = null })
        try {
          const list = await stationsApi.list()
          set((s) => {
            s.stations = Object.fromEntries(list.map((st) => [st._id, st]))
            s.loading = false
          })
        } catch (e) {
          set((s) => { s.loading = false; s.error = String(e) })
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
    })),
    { name: 'veridion/stations' }
  )
)
