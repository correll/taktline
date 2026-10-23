import { client } from './client'

export type Severity = 'critical' | 'warning' | 'insight'
export type Readiness = 'no-data' | 'partial' | 'ready'

export interface Finding {
  rule: string
  severity: Severity
  basis: 'topology' | 'timing' | 'load' | 'flow'
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

export interface WhatIfChange {
  stationId: string
  speedFactor?: number
  cv?: number | null
  breakdowns?: boolean
  servers?: number
}
export interface WhatIfScenario { name: string; changes: WhatIfChange[]; demandFactor?: number }
export interface WhatIfRow {
  name: string
  stationId: string | null
  leadTimeHours: number | null
  gainHours: number | null
  gainCi95Hours: [number, number] | null
  gainShare: number | null
}
export interface WhatIfResult {
  unit: string
  baseline: { leadTimeHours: number | null }
  calibration: { observedLeadTimeHours: number | null; modelLeadTimeHours: number | null; observedUnits: number }
  scenarios: WhatIfRow[]
}

export const analysisApi = {
  /** Replay the recorded period with something changed. */
  whatIf: (scenarios: WhatIfScenario[], replications = 20): Promise<WhatIfResult> =>
    client.post('/analysis/what-if', { scenarios, replications }),

  /** The same machine tried at every hand-worked station, ranked by gain. */
  automation: (body: { speedFactor: number; cv: number | null; breakdowns: boolean }): Promise<WhatIfResult> =>
    client.post('/analysis/automation', { ...body, replications: 20 }),

  /** What is wrong with this line. Computed entirely on our own server — no
   *  production data is sent anywhere. */
  report: (): Promise<LineReport> => client.get('/analysis/'),

  /** The runout rule for one station's lot picker. */
  runout: (stationId: string): Promise<RunoutInfo> =>
    client.get(`/analysis/runout/${stationId}`),
}
