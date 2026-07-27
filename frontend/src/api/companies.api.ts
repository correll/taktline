import { client } from './client'
import type { Role } from './auth.api'

export interface Company {
  id: string
  name: string
  slug: string | null
  timezone: string
  role?: Role | null
}

export const companiesApi = {
  create: (name: string, timezone = 'UTC'): Promise<Company> =>
    client.post('/companies/', { name, timezone }),
  listMine: (): Promise<Company[]> => client.get('/companies/'),
  get: (id: string): Promise<Company> => client.get(`/companies/${id}`),
}
