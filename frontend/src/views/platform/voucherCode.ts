/** Voucher codes that get typed from paper.
 *
 *  The server accepts `^#?[A-Za-z0-9_-]+$`, 3–32 characters, and stores the
 *  code uppercase. A generated one uses a smaller alphabet on purpose: no 0/O,
 *  no 1/I/L, so a code read off a flyer or over the phone has one spelling.
 *  Eight symbols from 31 is ~2^40 codes; a collision is a 409 the form shows,
 *  not a silent overwrite (the column is unique). */
export const VOUCHER_CODE_PATTERN = /^#?[A-Za-z0-9_-]+$/
export const VOUCHER_CODE_MAX = 32

const ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
const LENGTH = 8

export function generateVoucherCode(random: (n: number) => Uint8Array = randomBytes): string {
  const bytes = random(LENGTH)
  let out = ''
  for (let i = 0; i < LENGTH; i++) out += ALPHABET[bytes[i] % ALPHABET.length]
  return out
}

function randomBytes(n: number): Uint8Array {
  const buf = new Uint8Array(n)
  const c = (globalThis as any).crypto
  if (c?.getRandomValues) c.getRandomValues(buf)
  else for (let i = 0; i < n; i++) buf[i] = Math.floor(Math.random() * 256)
  return buf
}
