import { describe, expect, it, beforeEach } from 'vitest'
import { operatorId, _resetDeviceId } from './operatorIdentity'

const A = '11111111-2222-3333-4444-555555555555'
const B = '99999999-2222-3333-4444-555555555555'

describe('operator identity', () => {
  beforeEach(() => _resetDeviceId())

  it('is stable for one person on one device', () => {
    expect(operatorId(A)).toBe(operatorId(A))
  })

  it('separates people who share a device', () => {
    expect(operatorId(B)).not.toBe(operatorId(A))
  })

  it('separates one login on two devices', () => {
    const a = operatorId(A)
    _resetDeviceId()
    try { localStorage.removeItem('taktline.deviceId') } catch { /* no storage */ }
    expect(operatorId(A)).not.toBe(a)
  })

  it('is never the shared default', () => {
    expect(operatorId(null)).not.toBe('default')
    expect(operatorId(null)).toMatch(/^anon-[0-9a-z]{8}$/)
  })
})
