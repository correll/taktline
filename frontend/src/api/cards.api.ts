import { client } from './client'
import type { Card } from '../models'

export interface CardEvent {
  _id:         string
  cardId:      string
  type:        'created' | 'moved' | 'flagged' | 'unflagged' | 'updated' | 'deleted' | 'worked'
  fromStation: string | null
  toStation:   string | null
  quantity:    number | null
  note:        string
  operatorId?: string | null
  durationSec?: number | null
  timestamp:   string
}

export const cardsApi = {
  list:   ():                                   Promise<Card[]>        => client.get('/cards/'),
  get:    (id: string):                         Promise<Card>          => client.get(`/cards/${id}`),
  create: (body: Omit<Card, '_id' | 'createdAt' | 'updatedAt'>): Promise<Card> =>
    client.post('/cards/', body),
  update: (id: string, patch: Partial<Card>):  Promise<Card>          => client.put(`/cards/${id}`, patch),
  setStatus: (id: string, status: 'idle' | 'working' | 'done'): Promise<Card> =>
    client.patch(`/cards/${id}/status`, { status }),
  remove: (id: string):                         Promise<void>          => client.delete(`/cards/${id}`),
  move: (id: string, fromStationId: string, toStationId: string, quantity: number): Promise<Card> =>
    client.post(`/cards/${id}/move`, { fromStationId, toStationId, quantity }),
  advance: (id: string, fromStationId: string, toStationId: string, quantity: number): Promise<Card> =>
    client.post(`/cards/${id}/advance`, { fromStationId, toStationId, quantity }),
  unmerge: (id: string, stationId: string, quantity: number): Promise<{ unmerged: number; createdCardIds: string[] }> =>
    client.post(`/cards/${id}/unmerge`, { stationId, quantity }),
  /** Hand finished goods to an integration partner — "Send back to Odoo".
   *  This is where the lot leaves Taktline: the units are consumed and the
   *  partner's connector is told. Deliberately an act, not an arrival. */
  handoff: (id: string, fromStationId: string, integrationStationId: string, quantity: number):
    Promise<{ sentTo: string; quantity: number; orderId: string | null; orderStatus: string | null }> =>
    client.post(`/cards/${id}/handoff`, { fromStationId, integrationStationId, quantity }),
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
