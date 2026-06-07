import { client } from './client'
import type { Card } from '../models'

export interface CardEvent {
  _id:         string
  cardId:      string
  type:        'created' | 'moved' | 'flagged' | 'unflagged' | 'updated' | 'deleted'
  fromStation: string | null
  toStation:   string | null
  quantity:    number | null
  note:        string
  timestamp:   string
}

export const cardsApi = {
  list:   ():                                   Promise<Card[]>        => client.get('/cards/'),
  get:    (id: string):                         Promise<Card>          => client.get(`/cards/${id}`),
  create: (body: Omit<Card, '_id' | 'createdAt' | 'updatedAt'>): Promise<Card> =>
    client.post('/cards/', body),
  update: (id: string, patch: Partial<Card>):  Promise<Card>          => client.put(`/cards/${id}`, patch),
  remove: (id: string):                         Promise<void>          => client.delete(`/cards/${id}`),
  move: (id: string, fromStationId: string, toStationId: string, quantity: number): Promise<Card> =>
    client.post(`/cards/${id}/move`, { fromStationId, toStationId, quantity }),
  getEvents: (id: string):                     Promise<CardEvent[]>   => client.get(`/cards/${id}/events`),
}

export const statsApi = {
  overview: (): Promise<{
    totalLots:       number
    totalUnits:      number
    flaggedLots:     number
    lotsPerStation:  Record<string, number>
    unitsPerStation: Record<string, number>
    lotsPerProcess:  Record<string, number>
    movesPerHour:    { hoursAgo: number; moves: number }[]
  }> => client.get('/stats/overview'),
}
