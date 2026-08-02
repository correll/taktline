import { client } from './client'

export interface ImprovementPreview {
  available: boolean
  reason?: string | null
  metric?: string | null
  before?: string | null
  after?: string | null
  delta?: string | null
  caption?: string | null
  headline?: string | null
  improved?: boolean | null
  window?: string | null
}

export interface PublishedImprovement {
  id: string
  url: string
  metric: string
  before: string
  after: string
  delta: string
  caption: string
  headline: string
}

// `client` unwraps `response.data` in a response interceptor, so these return
// the body directly. Adding the usual `.then(r => r.data)` on top resolves to
// undefined — silently, since nothing throws and the caller just sees "no
// improvement to report".
export const shareApi = {
  /** What this line could honestly claim right now. Publishes nothing. */
  improvement: (window = '1w'): Promise<ImprovementPreview> =>
    client.get('/share/improvement', { params: { window } }),

  /** Mint the permanent public URL. The server recomputes the numbers — the
   *  card must never be able to say something the database does not. */
  publishImprovement: (window = '1w'): Promise<PublishedImprovement> =>
    client.post('/share/improvement', { window }),
}
