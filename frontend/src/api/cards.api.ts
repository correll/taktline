import { client } from './client'
import type { Card } from '../models'

export const cardsApi = {
  list:   ():                                   Promise<Card[]> => client.get('/cards/'),
  get:    (id: string):                         Promise<Card>   => client.get(`/cards/${id}`),
  create: (body: Omit<Card, '_id' | 'createdAt' | 'updatedAt'>): Promise<Card> =>
    client.post('/cards/', body),
  update: (id: string, patch: Partial<Card>):  Promise<Card>   => client.put(`/cards/${id}`, patch),
  remove: (id: string):                         Promise<void>   => client.delete(`/cards/${id}`),
}
