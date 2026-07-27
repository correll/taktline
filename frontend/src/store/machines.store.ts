import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { devtools } from 'zustand/middleware'
import type { MachineState } from '../models'

// 'live'         — event stream open, data is current
// 'reconnecting' — stream lost (server rebooting/unreachable), retrying with
//                  backoff; UI shows amber + the cached-data banner
// 'off'          — deliberately closed (logout / auth failure), no retries
export type ConnectionState = 'live' | 'reconnecting' | 'off'

interface MachinesState {
  states:     Record<string, MachineState>   // stationId → MachineState
  connected:  boolean                        // convenience: connection === 'live'
  connection: ConnectionState
  staleSince: string | null                  // set when rendering cached data

  upsertState:   (state: MachineState) => void
  setConnection: (connection: ConnectionState) => void
  setStaleSince: (iso: string | null) => void
}

export const useMachinesStore = create<MachinesState>()(
  devtools(
    immer((set) => ({
      states:     {},
      connected:  false,
      connection: 'off',
      staleSince: null,

      upsertState:   (state) => set((s) => { s.states[state.stationId] = state }),
      setConnection: (connection) => set((s) => {
        s.connection = connection
        s.connected = connection === 'live'
      }),
      setStaleSince: (iso) => set((s) => { s.staleSince = iso }),
    })),
    { name: 'taktline/machines' }
  )
)
