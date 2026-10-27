// Who is working, as the server counts it. A station's crew is the number of
// distinct operator identifiers with a session open there, and the server
// keeps one open session per station and identifier, so two tablets at one
// bench must never send the same one. The identifier is the signed-in person
// on this device: people who share a tablet under their own logins count
// separately, and one login on two tablets counts as two operators. It is
// pseudonymous -- a fragment of the user id and of a random per-device id --
// because the crew count needs only that operators are distinct.

const KEY = 'taktline.deviceId'
let memo: string | null = null

function randomId(): string {
  try {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  } catch { /* fall through */ }
  return Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2)
}

export function deviceId(): string {
  if (memo) return memo
  try {
    const kept = localStorage.getItem(KEY)
    if (kept) return (memo = kept)
    const fresh = randomId()
    localStorage.setItem(KEY, fresh)
    return (memo = fresh)
  } catch {
    // Storage blocked (private window, kiosk policy): stable for this page's life.
    return (memo = randomId())
  }
}

export function operatorId(userId: string | null | undefined): string {
  const who = userId ? userId.replace(/-/g, '').slice(0, 8) : 'anon'
  return `${who}-${deviceId().replace(/-/g, '').slice(0, 8)}`
}

/** Test hook: forget the cached device id. */
export function _resetDeviceId(): void { memo = null }
