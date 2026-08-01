import { client } from './client'

export interface UndoState {
  canUndo: boolean
  canRedo: boolean
  undoLabel: string | null
  redoLabel: string | null
}

export interface UndoResult {
  label: string
  direction: 'undo' | 'redo'
}

export const undoApi = {
  state: (): Promise<UndoState> => client.get('/undo/state'),
  undo: (): Promise<UndoResult> => client.post('/undo', {}),
  redo: (): Promise<UndoResult> => client.post('/redo', {}),
}
