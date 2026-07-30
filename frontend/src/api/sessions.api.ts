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
  /** Set when a trend window was asked for: the same metrics over the window
   *  immediately before this one, so the client can show which way each number
   *  is moving. Null when the station has no history that far back. */
  previous?: {
    cycleTimeSec:     number | null
    lineCycleTimeSec: number | null
    oee:              number | null
    totalUnits:       number
  } | null
  window?: TrendWindow
}

/** How far back a trend compares. Also the labels the picker shows. */
export const TREND_WINDOWS = {
  '1h': 'past hour', '1d': 'past day', '1w': 'past week', '1m': 'past month',
} as const
export type TrendWindow = keyof typeof TREND_WINDOWS

export const sessionsApi = {
  list:       (stationId?: string, openOnly?: boolean): Promise<WorkSession[]> =>
    client.get('/sessions/', { params: { stationId, open_only: openOnly } }),

  openSessions: (): Promise<WorkSession[]> => client.get('/sessions/open'),

  start: (body: { stationId: string; cardId?: string | null; operatorId?: string; quantity?: number }): Promise<WorkSession> =>
    client.post('/sessions/', body),

  end: (id: string, quantity?: number): Promise<WorkSession> =>
    client.post(`/sessions/${id}/end`, { quantity }),

  allStats: (window?: TrendWindow): Promise<SessionStats[]> =>
    client.get('/sessions/stats', window ? { params: { window } } : undefined),

  stationStats: (stationId: string): Promise<SessionStats> =>
    client.get(`/sessions/stats/${stationId}`),
}
