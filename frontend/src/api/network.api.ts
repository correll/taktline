import { client } from './client'

export interface SupplierInvite {
  id: string
  email: string
  supplies: string
  accepted: boolean
  acceptedAt?: string | null
  createdAt: string
}

/** Marker carried from an invitation email through signup, so the inviting
 *  company gets credited when their supplier actually joins. Stashed rather
 *  than passed down through the signup flow because verification happens in
 *  between — the company is created on a later page load than the click. */
const INVITE_KEY = 'taktline.supplierInvite'

export const networkApi = {
  list: (): Promise<SupplierInvite[]> => client.get('/network/suppliers'),

  invite: (body: { email: string; supplies?: string }): Promise<SupplierInvite> =>
    client.post('/network/suppliers', body),

  forget: (id: string): Promise<void> => client.delete(`/network/suppliers/${id}`),

  /** Called on any page that might carry `?supplier=` — the signup and the
   *  landing page both do. */
  captureInvite(search: string): void {
    const marker = new URLSearchParams(search).get('supplier')
    if (marker) { try { sessionStorage.setItem(INVITE_KEY, marker) } catch { /* private mode */ } }
  },

  takeInvite(): string | undefined {
    try {
      const marker = sessionStorage.getItem(INVITE_KEY)
      if (marker) sessionStorage.removeItem(INVITE_KEY)
      return marker ?? undefined
    } catch { return undefined }
  },
}
