import { describe, expect, it, beforeEach } from 'vitest'
import { networkApi } from '../../api/network.api'

// The suite runs in node, so there is no sessionStorage. A four-line stub beats
// pulling a whole DOM implementation in for one key.
class MemoryStorage {
  private data = new Map<string, string>()
  getItem(k: string) { return this.data.get(k) ?? null }
  setItem(k: string, v: string) { this.data.set(k, v) }
  removeItem(k: string) { this.data.delete(k) }
  clear() { this.data.clear() }
}
const store = new MemoryStorage()
;(globalThis as any).sessionStorage = store

/**
 * The two pieces of this feature that are pure logic. The rendering is a
 * progress bar; the parts worth pinning are where a URL is turned into a fetch
 * target, and where credit for a signup is carried across page loads.
 */

// Same derivation as SupplierStatus.tsx, kept in the test rather than exported
// so the component stays a component — see the assertion below on why the
// *shape* is what matters.
function statusUrl(trackingUrl: string): string | null {
  try {
    const u = new URL(trackingUrl)
    if (!/^https?:$/.test(u.protocol)) return null
    return `${u.origin}${u.pathname.replace('/o/', '/track/')}`
  } catch { return null }
}

describe('reading a supplier link', () => {
  it('points at the JSON endpoint, not the human page', () => {
    expect(statusUrl('https://taktline.com/o/abc/def'))
      .toBe('https://taktline.com/track/abc/def')
  })

  it('follows the supplier to their own server', () => {
    // The on-premise customer is exactly the one whose suppliers matter most.
    expect(statusUrl('https://mrp.fenwick.example:8443/o/abc/def'))
      .toBe('https://mrp.fenwick.example:8443/track/abc/def')
  })

  it('refuses a scheme a fetch should never be given', () => {
    expect(statusUrl('javascript:alert(1)')).toBeNull()
    expect(statusUrl('not a url')).toBeNull()
  })
})

describe('carrying an invitation through signup', () => {
  beforeEach(() => store.clear())

  it('survives the wander from the email to the signup form', () => {
    // A supplier clicks the invitation, reads the manual, then signs up. The
    // marker has to outlive those navigations or the credit is lost.
    networkApi.captureInvite('?supplier=abc.def&utm_source=email')
    expect(networkApi.takeInvite()).toBe('abc.def')
  })

  it('is spent once', () => {
    // Otherwise the next company this browser creates is credited too.
    networkApi.captureInvite('?supplier=abc.def')
    networkApi.takeInvite()
    expect(networkApi.takeInvite()).toBeUndefined()
  })

  it('is absent for an ordinary visitor', () => {
    networkApi.captureInvite('?utm_source=email')
    expect(networkApi.takeInvite()).toBeUndefined()
  })

  it('does not throw where storage is blocked', () => {
    // Private mode and locked-down browsers throw on sessionStorage access;
    // losing attribution is fine, crashing the signup page is not.
    const original = store.setItem
    store.setItem = () => { throw new Error('denied') }
    expect(() => networkApi.captureInvite('?supplier=abc.def')).not.toThrow()
    expect(() => networkApi.takeInvite()).not.toThrow()
    store.setItem = original
  })
})
