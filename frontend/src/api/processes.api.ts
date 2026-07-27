import { client } from './client'
import type { Process, Route, LotTemplate } from '../models'

/** Route patch. `clearOutputTemplate` resets a split branch's declared product
 *  (sending outputTemplateId: null would read as "unchanged" server-side). */
export type RoutePatch = Partial<Route> & { clearOutputTemplate?: boolean }

export const processesApi = {
  listProcesses:  ():                                           Promise<Process[]>     => client.get('/processes/'),
  listRoutes:     ():                                           Promise<Route[]>       => client.get('/routes/'),
  listTemplates:  ():                                           Promise<LotTemplate[]> => client.get('/lot-templates/'),

  createProcess:  (body: Partial<Process>):                     Promise<Process>       => client.post('/processes/', body),
  createRoute:    (body: Partial<Route>):                       Promise<Route>         => client.post('/routes/', body),
  createTemplate: (body: Partial<LotTemplate>):                 Promise<LotTemplate>   => client.post('/lot-templates/', body),

  updateProcess:  (id: string, patch: Partial<Process>):        Promise<Process>       => client.put(`/processes/${id}`, patch),
  updateRoute:    (id: string, patch: RoutePatch):               Promise<Route>         => client.put(`/routes/${id}`, patch),
  updateTemplate: (id: string, patch: Partial<LotTemplate>):    Promise<LotTemplate>   => client.put(`/lot-templates/${id}`, patch),

  deleteProcess:  (id: string):                                 Promise<void>          => client.delete(`/processes/${id}`),
  deleteRoute:    (id: string):                                 Promise<void>          => client.delete(`/routes/${id}`),
  deleteTemplate: (id: string):                                 Promise<void>          => client.delete(`/lot-templates/${id}`),
}
