import { client } from './client'

export type Severity = 'critical' | 'warning' | 'insight'
export type Readiness = 'no-data' | 'partial' | 'ready'

export interface Finding {
  rule: string
  severity: Severity
  basis: 'topology' | 'timing'
  title: string
  detail: string
  stations: string[]
  process: string | null
  waste: string | null
  manual: string | null
  metrics: Record<string, number>
}

export interface LineReport {
  readiness: Readiness
  headline: string
  narrative: string[]
  findings: Finding[]
  coverage: {
    stationsWithTiming: number
    sessions: number
    stationsNeeded: number
    sessionsNeeded: number
  }
  counts: { critical: number; warning: number; insight: number }
}

/** One line's clock at a shared station: how long until the station this
 *  line feeds runs out of material. `runoutSec` 0 = starving now; null = no
 *  measured rate downstream, so there is no clock — those sort FIFO. */
export interface LineRunout {
  processId: string
  processName: string
  nextStationId: string
  nextStationName: string
  bufferUnits: number
  lineCycleSec: number | null
  runoutSec: number | null
}

export interface RunoutInfo {
  stationId: string
  lines: Record<string, LineRunout>
}

export const analysisApi = {
  /** What is wrong with this line. Computed entirely on our own server — no
   *  production data is sent anywhere. */
  report: (): Promise<LineReport> => client.get('/analysis/'),

  /** The runout rule for one station's lot picker. */
  runout: (stationId: string): Promise<RunoutInfo> =>
    client.get(`/analysis/runout/${stationId}`),
}
