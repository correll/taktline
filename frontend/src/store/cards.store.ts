import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { devtools } from 'zustand/middleware'
import type { Card } from '../models'
import { cardsApi } from '../api/cards.api'

interface CardsState {
  cards:   Record<string, Card>
  loading: boolean
  error:   string | null

  fetchAll: ()                                                           => Promise<void>
  fetchOne: (id: string)                                                 => Promise<void>
  create:   (body: Omit<Card, '_id' | 'createdAt' | 'updatedAt'>)       => Promise<Card>
  update:   (id: string, patch: Partial<Card>)                          => Promise<Card>
  remove:   (id: string)                                                 => Promise<void>
  upsert:   (card: Card)                                                 => void
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
        } catch (e) {
          set((s) => { s.loading = false; s.error = String(e) })
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

      remove: async (id) => {
        await cardsApi.remove(id)
        set((s) => { delete s.cards[id] })
      },

      upsert: (card) => set((s) => { s.cards[card._id] = card }),
    })),
    { name: 'veridion/cards' }
  )
)
