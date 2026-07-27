import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { devtools } from 'zustand/middleware'
import type { Process, Route, LotTemplate } from '../models'
import { processesApi, type RoutePatch } from '../api/processes.api'
import { loadSlice, saveSlice } from './offlineCache'

interface ProcessesState {
  processes:    Record<string, Process>
  routes:       Record<string, Route>
  lotTemplates: Record<string, LotTemplate>
  loading:      boolean
  error:        string | null

  fetchAll:        ()                                              => Promise<void>
  createProcess:   (body: Partial<Process>)                       => Promise<Process>
  updateProcess:   (id: string, patch: Partial<Process>)          => Promise<Process>
  deleteProcess:   (id: string)                                    => Promise<void>
  createRoute:     (body: Partial<Route>)                         => Promise<Route>
  updateRoute:     (id: string, patch: RoutePatch)                => Promise<Route>
  deleteRoute:     (id: string)                                    => Promise<void>
  createTemplate:  (body: Partial<LotTemplate>)                   => Promise<LotTemplate>
  updateTemplate:  (id: string, patch: Partial<LotTemplate>)      => Promise<LotTemplate>
  deleteTemplate:  (id: string)                                    => Promise<void>
  // Self-healing template cache: the server auto-provisions templates during
  // pulls/merges/order releases, so cards can arrive (fetch or WS) referencing
  // templates this client has never seen. Call with the template ids in use —
  // any unknown id triggers a debounced refetch, so lots never stay "Unknown"
  // and merge-station precursor classification can't silently fail.
  ensureTemplates: (templateIds: (string | undefined)[])           => void
}

let _lastEnsureFetch = 0

export const useProcessesStore = create<ProcessesState>()(
  devtools(
    immer((set, get) => ({
      processes:    {},
      routes:       {},
      lotTemplates: {},
      loading:      false,
      error:        null,

      fetchAll: async () => {
        set((s) => { s.loading = true; s.error = null })
        try {
          const [processes, routes, templates] = await Promise.all([
            processesApi.listProcesses(),
            processesApi.listRoutes(),
            processesApi.listTemplates(),
          ])
          set((s) => {
            s.processes    = Object.fromEntries(processes.map((p) => [p._id, p]))
            s.routes       = Object.fromEntries(routes.map((r) => [r._id, r]))
            s.lotTemplates = Object.fromEntries(templates.map((t) => [t._id, t]))
            s.loading = false
          })
          saveSlice('graph', { processes, routes, templates })
        } catch (e) {
          const cached = loadSlice<{ processes: Process[]; routes: Route[]; templates: LotTemplate[] }>('graph')
          set((s) => {
            if (cached) {
              s.processes    = Object.fromEntries(cached.processes.map((p) => [p._id, p]))
              s.routes       = Object.fromEntries(cached.routes.map((r) => [r._id, r]))
              s.lotTemplates = Object.fromEntries(cached.templates.map((t) => [t._id, t]))
            }
            s.loading = false
            s.error = cached ? null : String(e)
          })
        }
      },

      createProcess: async (body) => {
        const p = await processesApi.createProcess(body)
        set((s) => { s.processes[p._id] = p })
        return p
      },

      updateProcess: async (id, patch) => {
        const p = await processesApi.updateProcess(id, patch)
        set((s) => { s.processes[id] = p })
        return p
      },

      deleteProcess: async (id) => {
        await processesApi.deleteProcess(id)
        set((s) => { delete s.processes[id] })
      },

      createRoute: async (body) => {
        const route = await processesApi.createRoute(body)
        set((s) => { s.routes[route._id] = route })
        return route
      },

      updateRoute: async (id, patch) => {
        const route = await processesApi.updateRoute(id, patch)
        set((s) => { s.routes[id] = route })
        return route
      },

      deleteRoute: async (id) => {
        await processesApi.deleteRoute(id)
        set((s) => { delete s.routes[id] })
      },

      createTemplate: async (body) => {
        const t = await processesApi.createTemplate(body)
        set((s) => { s.lotTemplates[t._id] = t })
        return t
      },

      updateTemplate: async (id, patch) => {
        const t = await processesApi.updateTemplate(id, patch)
        set((s) => { s.lotTemplates[id] = t })
        return t
      },

      deleteTemplate: async (id) => {
        await processesApi.deleteTemplate(id)
        set((s) => { delete s.lotTemplates[id] })
      },

      ensureTemplates: (templateIds) => {
        const known = get().lotTemplates
        if (!templateIds.some((id) => id && !known[id])) return
        if (get().loading) return
        const now = Date.now()
        if (now - _lastEnsureFetch < 4000) return   // debounce refetch storms
        _lastEnsureFetch = now
        void get().fetchAll()
      },
    })),
    { name: 'taktline/processes' }
  )
)
