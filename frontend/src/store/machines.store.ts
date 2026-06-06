import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { devtools } from 'zustand/middleware'
import type { MachineState } from '../models'

interface MachinesState {
  states:    Record<string, MachineState>   // stationId → MachineState
  connected: boolean

  upsertState:  (state: MachineState) => void
  setConnected: (connected: boolean)  => void
}

export const useMachinesStore = create<MachinesState>()(
  devtools(
    immer((set) => ({
      states:    {},
      connected: false,

      upsertState:  (state) => set((s) => { s.states[state.stationId] = state }),
      setConnected: (connected) => set((s) => { s.connected = connected }),
    })),
    { name: 'veridion/machines' }
  )
)
