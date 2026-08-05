import { client } from './client'

export interface ApiKey {
  id: string
  name: string
  prefix: string
  scopes: string[]
  createdAt: string
  lastUsedAt: string | null
  revoked: boolean
}
export interface ApiKeyCreated extends ApiKey { key: string }

export interface ProductionOrder {
  id: string
  source: string
  externalRef: string | null
  productTemplateId: string | null
  mergeStationId: string | null
  quantity: number
  quantityDone: number
  trackingUrl?: string | null
  status: string
  note: string
  createdAt: string
  updatedAt: string
}

export interface OutboxEvent {
  id: string
  orderId: string | null
  eventType: string
  payload: Record<string, unknown>
  status: string
  attempts: number
  createdAt: string
}

export interface ScopeInfo { scope: string; description: string }

export const apiKeysApi = {
  list:   (): Promise<ApiKey[]> => client.get('/api-keys/'),
  scopes: (): Promise<ScopeInfo[]> => client.get('/api-keys/scopes'),
  create: (name: string, scopes: string[] = ['orders']): Promise<ApiKeyCreated> =>
    client.post('/api-keys/', { name, scopes }),
  revoke: (id: string): Promise<void> => client.delete(`/api-keys/${id}`),
}

export interface ImportResult {
  summary: { total: number; released: number; duplicate: number; errors: number }
  rows: { row: number; status: string; externalRef: string | null; orderId?: string; error?: string }[]
}

export const ordersApi = {
  list:   (): Promise<ProductionOrder[]> => client.get('/orders/'),
  outbox: (status = ''): Promise<OutboxEvent[]> => client.get(`/orders/outbox?status=${status}`),
  importCsv: (file: File): Promise<ImportResult> => {
    const form = new FormData()
    form.append('file', file)
    // Clear Content-Type so the browser sets the multipart boundary itself.
    return client.post('/orders/import', form, { headers: { 'Content-Type': undefined as unknown as string } })
  },
}

export interface TemplateRef { _id: string; name: string; color?: string | null }

/** Template ids an admin drops into a connector's PRODUCT_MAPPING. */
export const templatesApi = {
  list: (): Promise<TemplateRef[]> => client.get('/lot-templates/'),
}
