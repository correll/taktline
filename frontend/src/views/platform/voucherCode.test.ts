import { describe, it, expect } from 'vitest'
import { generateVoucherCode, VOUCHER_CODE_PATTERN, VOUCHER_CODE_MAX } from './voucherCode'

// Pressing "Mint voucher" with the Code field blank used to do nothing at all:
// the button was disabled, but its inline colours hid that, and no request
// left the page. A blank code now mints a generated one, so the code the
// generator produces must be one the server will take.
describe('generateVoucherCode', () => {
  it('produces a code the server pattern accepts, every time', () => {
    for (let i = 0; i < 500; i++) {
      const code = generateVoucherCode()
      expect(code).toMatch(VOUCHER_CODE_PATTERN)
      expect(code.length).toBeGreaterThanOrEqual(3)
      expect(code.length).toBeLessThanOrEqual(VOUCHER_CODE_MAX)
    }
  })

  it('never uses a glyph that reads two ways off paper', () => {
    for (let i = 0; i < 500; i++) expect(generateVoucherCode()).not.toMatch(/[01OIL]/)
  })

  it('is already uppercase, matching how the server stores it', () => {
    const code = generateVoucherCode()
    expect(code).toBe(code.toUpperCase())
  })

  it('covers the whole alphabet, not one corner of it', () => {
    // A modulo bias or an off-by-one on the alphabet would show up here as
    // a symbol that never appears.
    const seen = new Set<string>()
    for (let i = 0; i < 2000; i++) for (const ch of generateVoucherCode()) seen.add(ch)
    expect(seen.size).toBe(31)
  })

  it('is deterministic given the bytes, so the mapping itself is testable', () => {
    expect(generateVoucherCode(() => new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7]))).toBe('ABCDEFGH')
    expect(generateVoucherCode(() => new Uint8Array(8).fill(30))).toBe('99999999')
    expect(generateVoucherCode(() => new Uint8Array(8).fill(31))).toBe('AAAAAAAA')
  })
})
