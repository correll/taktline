import { client } from './client'

export interface WorkSession {
  _id:         string
  stationId:   string
  cardId:      string | null
  operatorId:  string
  quantity:    number
  startedAt:   string
  endedAt:     string | null
  durationSec: number | null
}

export interface SessionStats {
  stationId:       string
  sessionCount:    number
  totalUnits:      number
  totalWorkingSec: number
  /** Seconds of work per unit — what start/stop actually measured. */
  cycleTimeSec:    number | null
  /** Seconds between departures per piece — the station's actual exit rate.
   *  Null until there are two departures to measure between. */
  lineCycleTimeSec: number | null
  oee:             number | null
  isWarehouse?:    boolean          // storage, not a work station — no OEE
}

export const sessionsApi = {
  list:       (stationId?: string, openOnly?: boolean): Promise<WorkSession[]> =>
    client.get('/sessions/', { params: { stationId, open_only: openOnly } }),

  openSessions: (): Promise<WorkSession[]> => client.get('/sessions/open'),

  start: (body: { stationId: string; cardId?: string | null; operatorId?: string; quantity?: number }): Promise<WorkSession> =>
    client.post('/sessions/', body),

  end: (id: string, quantity?: number): Promise<WorkSession> =>
    client.post(`/sessions/${id}/end`, { quantity }),

  allStats: (): Promise<SessionStats[]> =>
    client.get('/sessions/stats'),

  stationStats: (stationId: string): Promise<SessionStats> =>
    client.get(`/sessions/stats/${stationId}`),
}
