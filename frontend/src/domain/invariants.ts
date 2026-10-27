// Dev-mode domain assertions.
// In development: throws immediately so bugs are caught at the call site.
// In production: logs to console.error and continues (no user-visible crash).

const DEV = import.meta.env.DEV

export function assert(condition: boolean, message: string): asserts condition {
  if (!condition) {
    const full = `[Taktline] ${message}`
    if (DEV) throw new Error(full)
    else console.error(full)
  }
}

// ─── Numeric invariants ───────────────────────────────────────────────────────

export function assertPositiveInt(value: number, name: string): void {
  assert(Number.isInteger(value) && value >= 1, `${name} must be a positive integer (got ${value})`)
}

export function assertNonNegativeInt(value: number, name: string): void {
  assert(Number.isInteger(value) && value >= 0, `${name} must be a non-negative integer (got ${value})`)
}

export function assertPositiveNumber(value: number, name: string): void {
  assert(Number.isFinite(value) && value > 0, `${name} must be a positive number (got ${value})`)
}

// ─── Domain-specific invariants ───────────────────────────────────────────────

// Card: sum of bin counts must not exceed totalQuantity (conservation of lots).
export function assertCardBinConservation(card: {
  totalQuantity: number
  bins: Record<string, { count: number }>
}): void {
  const binTotal = Object.values(card.bins).reduce((s, b) => s + b.count, 0)
  assert(
    binTotal <= card.totalQuantity,
    `card bin total (${binTotal}) exceeds totalQuantity (${card.totalQuantity}) — lots cannot be created or destroyed`,
  )
}

// Route: a station cannot route to itself.
export function assertNoSelfLoop(load: string, unload: string): void {
  assert(load !== unload, `route self-loop: station ${load} routes to itself`)
}

// Route: quantity must be at least 1.
export function assertRouteQuantity(quantity: number): void {
  assertPositiveInt(quantity, 'route quantity')
}

// Move: the moved quantity must be within the available count at the source.
export function assertMoveQuantity(quantity: number, available: number): void {
  assertPositiveInt(quantity, 'move quantity')
  assert(quantity <= available, `cannot move ${quantity} units — only ${available} available at source`)
}

// Session: duration in seconds must be non-negative.
export function assertSessionDuration(durationSec: number | null | undefined): void {
  if (durationSec != null) {
    assert(durationSec >= 0, `session durationSec must be non-negative (got ${durationSec})`)
  }
}

// Utilisation (field `oee`) is a ratio and must stay in [0, 1].
export function assertOEE(oee: number | null | undefined): void {
  if (oee != null) {
    assert(oee >= 0 && oee <= 1, `utilisation (oee) must be in [0, 1] (got ${oee})`)
  }
}

// Viewport scale must be strictly positive (division by zero otherwise).
export function assertViewportScale(scale: number): void {
  assertPositiveNumber(scale, 'viewport scale')
}

// Map calibration values must be strictly positive.
export function assertMapCalibration(pixelsPerUnit: number, stationSizeUnits: number): void {
  assertPositiveNumber(pixelsPerUnit, 'pixelsPerUnit')
  assertPositiveNumber(stationSizeUnits, 'stationSizeUnits')
}
