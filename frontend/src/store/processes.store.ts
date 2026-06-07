import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { devtools } from 'zustand/middleware'
import type { Process, Route, LotTemplate } from '../models'
import { processesApi } from '../api/processes.api'

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
  updateRoute:     (id: string, patch: Partial<Route>)            => Promise<Route>
  deleteRoute:     (id: string)                                    => Promise<void>
  createTemplate:  (body: Partial<LotTemplate>)                   => Promise<LotTemplate>
  updateTemplate:  (id: string, patch: Partial<LotTemplate>)      => Promise<LotTemplate>
  deleteTemplate:  (id: string)                                    => Promise<void>
}

export const useProcessesStore = create<ProcessesState>()(
  devtools(
    immer((set) => ({
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
        } catch (e) {
          set((s) => { s.loading = false; s.error = String(e) })
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
    })),
    { name: 'veridion/processes' }
  )
)
