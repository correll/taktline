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

export const mergeApi = {
  preview: (stationId: string): Promise<MergePreview> =>
    client.get(`/merge/${stationId}`),

  perform: (stationId: string): Promise<MergeResult> =>
    client.post(`/merge/${stationId}`, {}),
}
