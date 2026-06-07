import axios from 'axios'
import { client } from './client'

export interface MapSettingsData {
  _id:              string
  floorPlanUrl:     string | null
  pixelsPerUnit:    number
  unit:             'ft' | 'm'
  stationSizeUnits: number
  mapWidthPx:       number | null
  mapHeightPx:      number | null
  updatedAt:        string
}

export const mapSettingsApi = {
  get:    (): Promise<MapSettingsData> =>
    client.get('/map-settings/'),

  update: (patch: Partial<MapSettingsData>): Promise<MapSettingsData> =>
    client.put('/map-settings/', patch),

  uploadFloorPlan: async (file: File): Promise<{ url: string }> => {
    const form = new FormData()
    form.append('file', file)
    const res = await axios.post('/api/map-settings/upload-floor-plan', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res.data
  },
}
