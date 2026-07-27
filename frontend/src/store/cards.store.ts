import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { devtools } from 'zustand/middleware'
import type { Card } from '../models'
import { cardsApi } from '../api/cards.api'
import { loadSlice, saveSlice } from './offlineCache'

interface CardsState {
  cards:   Record<string, Card>
  loading: boolean
  error:   string | null

  fetchAll: ()                                                           => Promise<void>
  fetchOne: (id: string)                                                 => Promise<void>
  create:   (body: Omit<Card, '_id' | 'createdAt' | 'updatedAt'>)       => Promise<Card>
  update:    (id: string, patch: Partial<Card>)                          => Promise<Card>
  setStatus: (id: string, status: 'idle' | 'working' | 'done')          => Promise<Card>
  remove:   (id: string)                                                 => Promise<void>
  upsert:   (card: Card)                                                 => void
  drop:     (id: string)                                                 => void   // local-only (WS card_delete)
}

export const useCardsStore = create<CardsState>()(
  devtools(
    immer((set) => ({
      cards:   {},
      loading: false,
      error:   null,

      fetchAll: async () => {
        set((s) => { s.loading = true; s.error = null })
        try {
          const list = await cardsApi.list()
          set((s) => {
            s.cards = Object.fromEntries(list.map((c) => [c._id, c]))
            s.loading = false
          })
          saveSlice('cards', list)
        } catch (e) {
          // Server unreachable → fall back to the last-known snapshot (stale
          // banner shows) so a reload during an outage isn't a blank board.
          const cached = loadSlice<Card[]>('cards')
          set((s) => {
            if (cached) s.cards = Object.fromEntries(cached.map((c) => [c._id, c]))
            s.loading = false
            s.error = cached ? null : String(e)
          })
        }
      },

      fetchOne: async (id) => {
        const card = await cardsApi.get(id)
        set((s) => { s.cards[id] = card })
      },

      create: async (body) => {
        const card = await cardsApi.create(body)
        set((s) => { s.cards[card._id] = card })
        return card
      },

      update: async (id, patch) => {
        const card = await cardsApi.update(id, patch)
        set((s) => { s.cards[id] = card })
        return card
      },

      setStatus: async (id, status) => {
        const card = await cardsApi.setStatus(id, status)
        set((s) => { s.cards[id] = card })
        return card
      },

      remove: async (id) => {
        await cardsApi.remove(id)
        set((s) => { delete s.cards[id] })
      },

      upsert: (card) => set((s) => { s.cards[card._id] = card }),

      drop: (id) => set((s) => { delete s.cards[id] }),
    })),
    { name: 'taktline/cards' }
  )
)
