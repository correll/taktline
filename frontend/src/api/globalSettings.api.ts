import { client } from './client'

export interface GlobalSettingsData {
  timezone: string
  // 7×24 grid; each cell is a 4-bit quarter mask (0–15), bit i = the i-th 15-min
  // quarter of the hour (bit 0 = :00–:15 … bit 3 = :45–:00). Day 0 = Monday.
  workHours: number[][]
  /** Show operators a progress arc against their station's expected cycle time.
   *  Off unless a company turns it on — see the Operator view for why. */
  showCycleArc: boolean
}

export const FULL_HOUR = 0b1111   // all four quarters open

// Mon–Fri 9am–5pm fully open; weekends closed.
export const defaultWorkHours = (): number[][] =>
  Array.from({ length: 7 }, (_, d) =>
    Array.from({ length: 24 }, (_, h) => (d < 5 && h >= 9 && h < 17 ? FULL_HOUR : 0)))

export const globalSettingsApi = {
  get: (): Promise<GlobalSettingsData> => client.get('/global-settings/'),
  update: (data: Partial<GlobalSettingsData>): Promise<GlobalSettingsData> =>
    client.put('/global-settings/', data),
}

export const COMMON_TIMEZONES = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'America/Honolulu',
  'America/Toronto',
  'America/Vancouver',
  'America/Mexico_City',
  'America/Sao_Paulo',
  'America/Buenos_Aires',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Amsterdam',
  'Europe/Stockholm',
  'Europe/Helsinki',
  'Europe/Moscow',
  'Africa/Cairo',
  'Asia/Dubai',
  'Asia/Kolkata',
  'Asia/Bangkok',
  'Asia/Singapore',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Seoul',
  'Australia/Sydney',
  'Australia/Melbourne',
  'Pacific/Auckland',
]
