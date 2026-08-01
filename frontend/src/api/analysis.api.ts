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

export const analysisApi = {
  /** What is wrong with this line. Computed entirely on our own server — no
   *  production data is sent anywhere. */
  report: (): Promise<LineReport> => client.get('/analysis/'),
}
