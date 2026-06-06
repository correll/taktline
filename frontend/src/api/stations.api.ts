import { client } from './client'
import type { Station } from '../models'

export const stationsApi = {
  list:   ():                                       Promise<Station[]> => client.get('/stations/'),
  get:    (id: string):                             Promise<Station>   => client.get(`/stations/${id}`),
  create: (body: Omit<Station, '_id' | 'createdAt' | 'updatedAt'>): Promise<Station> =>
    client.post('/stations/', body),
  update: (id: string, patch: Partial<Station>):   Promise<Station>   => client.put(`/stations/${id}`, patch),
  remove: (id: string):                             Promise<void>      => client.delete(`/stations/${id}`),
}
