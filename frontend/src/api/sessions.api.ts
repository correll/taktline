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
  /** Stoppage time inside the session; durationSec excludes it. */
  pausedSec?:  number
  /** Set while the session is paused. */
  pausedAt?:   string | null
  pauseReason?: StoppageReason | null
  /** operator | move | next_start — anything but operator means Stop was never pressed. */
  closedBy?:   string | null
}

export type StoppageReason = 'breakdown' | 'changeover' | 'material' | 'other'

export const STOPPAGE_REASONS: { key: StoppageReason; label: string }[] = [
  { key: 'breakdown',  label: 'Breakdown' },
  { key: 'changeover', label: 'Changeover' },
  { key: 'material',   label: 'Waiting for material' },
  { key: 'other',      label: 'Other' },
]

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
  /** Sessions closed only by the operator's next Start (not used for cycle time). */
  unstoppedSessions?: number
  downtimeSec?:   number
  breakdowns?:    number
  changeoverSec?: number
  changeovers?:   number
  otherStopSec?:  number
  /** Working time ÷ (working + breakdown) — the data box's uptime. */
  uptime?:        number | null
  /** Time-averaged units at the station, rebuilt from the lot history. */
  wipAvg?:        number | null
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

  pause: (id: string, reason: StoppageReason): Promise<WorkSession> =>
    client.post(`/sessions/${id}/pause`, { reason }),

  resume: (id: string): Promise<WorkSession> =>
    client.post(`/sessions/${id}/resume`),

  allStats: (window?: TrendWindow): Promise<SessionStats[]> =>
    client.get('/sessions/stats', window ? { params: { window } } : undefined),

  stationStats: (stationId: string): Promise<SessionStats> =>
    client.get(`/sessions/stats/${stationId}`),
}
