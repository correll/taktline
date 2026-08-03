import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { LANGUAGE_CODES, LANGUAGES } from './languages'
import { STRINGS } from './strings'
import { translate } from './index'

/**
 * The dictionary's contract, and the catalogue's agreement with the backend.
 *
 * The backend allowlist (core/languages.py) decides what may be *stored*;
 * this module decides what can be *shown*. If they drift, someone picks a
 * language at signup and gets English with no explanation — so the test reads
 * the Python file the same way pricing.test.ts reads plans.py.
 */

describe('the language catalogue', () => {
  it('matches the backend allowlist', () => {
    const py = readFileSync(
      resolve(__dirname, '../../../backend/app/core/languages.py'), 'utf-8')
    const block = py.split('LANGUAGES: dict[str, str] = {')[1]?.split('}')[0] ?? ''
    const backendCodes = [...block.matchAll(/"([^"]+)":/g)].map((m) => m[1])
    expect(backendCodes.sort()).toEqual([...LANGUAGE_CODES].sort())
    // Guard the guard: an empty parse would "match" an empty frontend list.
    expect(backendCodes.length).toBeGreaterThanOrEqual(5)
  })

  it('names every language in itself', () => {
    for (const code of LANGUAGE_CODES) {
      expect(LANGUAGES[code].length, code).toBeGreaterThan(0)
    }
  })
})

describe('the dictionary', () => {
  it('carries every language for every key', () => {
    // A key missing a language falls back to English silently at runtime —
    // fine for a day, invisible forever. Here it fails instead.
    for (const [key, entry] of Object.entries(STRINGS)) {
      for (const code of LANGUAGE_CODES) {
        expect(entry[code], `${key} is missing ${code}`).toBeTruthy()
      }
    }
  })

  it('every key the operator view uses exists', () => {
    const view = readFileSync(
      resolve(__dirname, '../views/operator/OperatorView.tsx'), 'utf-8')
    const used = [...view.matchAll(/\bt\('([^']+)'/g)].map((m) => m[1])
    expect(used.length).toBeGreaterThan(5)      // the tranche is really wired
    for (const key of used) {
      expect(STRINGS[key], `OperatorView uses unknown key ${key}`).toBeDefined()
    }
  })

  it('substitutes placeholders and falls back sanely', () => {
    expect(translate('es', 'op.moveTo', { dest: 'Pintura' })).toBe('MOVER → Pintura')
    expect(translate('my', 'op.start')).toBe('စတင်ရန်')
    // Unknown key → the key itself, loudly greppable.
    expect(translate('en', 'no.such.key')).toBe('no.such.key')
  })
})
