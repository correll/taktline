import { client } from './client'

export interface MapSettingsData {
  _id:              string
  floorPlanUrl:     string | null
  pixelsPerUnit:    number
  unit:             'ft' | 'm'
  stationSizeUnits: number
  floorPlanOpacity: number
  mapWidthPx:       number | null
  mapHeightPx:      number | null
  updatedAt:        string
}

export const mapSettingsApi = {
  get:    (): Promise<MapSettingsData> =>
    client.get('/map-settings/'),

  update: (patch: Partial<MapSettingsData>): Promise<MapSettingsData> =>
    client.put('/map-settings/', patch),

  // Routed through the shared client so it inherits withCredentials, the
  // X-Company-Id header, and CSRF. Content-Type is cleared so the browser sets
  // the multipart boundary itself.
  uploadFloorPlan: (file: File): Promise<{ url: string }> => {
    const form = new FormData()
    form.append('file', file)
    return client.post('/map-settings/upload-floor-plan', form, {
      headers: { 'Content-Type': undefined as unknown as string },
    })
  },
}
