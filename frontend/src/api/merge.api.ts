import { client } from './client'

export interface RequirementInfo {
  routeId: string
  sourceStationId: string
  requiredPerAssembly: number
  availableUnits: number
  canMake: number
}

export interface MergePreview {
  isMergeStation: boolean
  hasAssemblyTemplate: boolean
  assemblyTemplateId: string | null
  assemblyTemplateName: string | null
  assembliesPossible: number
  requirements: RequirementInfo[]
}

export interface MergeResult {
  assemblies: number
  createdCardId: string
}

export interface PullSourceInfo {
  stationId:    string
  stationName:  string
  templateId:   string
  templateName: string
  quantity:     number
}

export interface PullResult {
  sources:        PullSourceInfo[]
  createdCardIds: string[]
}

export const mergeApi = {
  preview: (stationId: string): Promise<MergePreview> =>
    client.get(`/merge/${stationId}`),

  // No cardIds → auto mode (consume any available precursors);
  // with cardIds → consume only from the worker-selected lot cards.
  perform: (stationId: string, cardIds?: string[]): Promise<MergeResult> =>
    client.post(`/merge/${stationId}`, cardIds && cardIds.length ? { cardIds } : {}),

  pull: (stationId: string, quantity: number): Promise<PullResult> =>
    client.post(`/merge/${stationId}/pull`, { quantity }),
}
