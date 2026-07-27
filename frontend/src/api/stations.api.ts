import { client } from './client'
import type { Station } from '../models'

export const stationsApi = {
  list:   ():                                       Promise<Station[]> => client.get('/stations/'),
  get:    (id: string):                             Promise<Station>   => client.get(`/stations/${id}`),
  create: (body: Omit<Station, '_id' | 'createdAt' | 'updatedAt'>): Promise<Station> =>
    client.post('/stations/', body),
  update: (id: string, patch: Partial<Station>):   Promise<Station>   => client.put(`/stations/${id}`, patch),
  remove:      (id: string):                                              Promise<void>      => client.delete(`/stations/${id}`),
  favorites:   ():                                                        Promise<string[]>  => client.get('/stations/favorites'),
  setFavorite: (id: string, favorite: boolean):                           Promise<void>      =>
    favorite ? client.put(`/stations/${id}/favorite`) : client.delete(`/stations/${id}/favorite`),
  sendCommand: (id: string, cmd: { type: string; params?: Record<string, unknown> }): Promise<{ ok: boolean }> =>
    client.post(`/stations/${id}/command`, cmd),
}
