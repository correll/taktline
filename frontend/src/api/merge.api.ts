import { client } from './client'

export interface RequirementInfo {
  routeId: string
  sourceStationId: string
  requiredPerAssembly: number
  availableUnits: number
  canMake: number
  /** Which products count as this branch's precursor — authoritative, so a
   *  client never re-derives the matching and offers a sibling line's lots. */
  precursorTemplateIds: string[]
  /** The lot cards an unguided merge would draw from: the opening selection. */
  proposedCardIds: string[]
}

export interface MergeProcessInfo {
  id: string
  name: string
  feeds: number
}

export interface MergePreview {
  isMergeStation: boolean
  hasAssemblyTemplate: boolean
  assemblyTemplateId: string | null
  assemblyTemplateName: string | null
  assembliesPossible: number
  requirements: RequirementInfo[]
  /** The line this preview describes, and every line that merges here. */
  processId: string | null
  processes: MergeProcessInfo[]
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
  preview: (stationId: string, processId?: string): Promise<MergePreview> =>
    client.get(`/merge/${stationId}`, processId ? { params: { processId } } : undefined),

  // No cardIds → auto mode (consume any available precursors);
  // with cardIds → consume only from the worker-selected lot cards.
  perform: (stationId: string, cardIds?: string[], processId?: string): Promise<MergeResult> =>
    client.post(`/merge/${stationId}`, {
      ...(cardIds && cardIds.length ? { cardIds } : {}),
      ...(processId ? { processId } : {}),
    }),

  pull: (stationId: string, quantity: number, processId?: string): Promise<PullResult> =>
    client.post(`/merge/${stationId}/pull`,
                processId ? { quantity, processId } : { quantity }),
}
