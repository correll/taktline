import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { LEAN_TIPS } from './leanTips'
import { CONCEPTS } from './concepts'
import { MANUAL_ANCHORS } from './manualAnchors'

/**
 * The share catalogue: one source of truth, two languages.
 *
 * The tips and the flow-science concepts are authored in TypeScript because
 * that is where they are read — the daily tip, the manual, the landing page.
 * But the *share card* is rendered by the backend, because LinkedIn's crawler
 * does not run JavaScript: the OG tags and the PNG have to exist as bytes at a
 * URL before any browser is involved.
 *
 * So the catalogue is generated into `backend/app/data/share_catalog.json` and
 * checked in, and this test fails the moment the two drift. Regenerate with:
 *
 *     UPDATE_SHARE_CATALOG=1 npm test
 *
 * The alternative — the backend re-deriving the text — would mean maintaining
 * ninety-four tips twice, and the copy on the card is the entire product here.
 */

const CATALOG = resolve(__dirname, '../../../backend/app/data/share_catalog.json')

function build() {
  return {
    _comment:
      'GENERATED from frontend/src/help/{leanTips,concepts}.ts. Do not edit by hand — ' +
      'run `UPDATE_SHARE_CATALOG=1 npm test` in frontend/ instead.',
    version: 1,
    tips: LEAN_TIPS.map((t) => ({ id: t.id, category: t.category, text: t.text })),
    concepts: CONCEPTS.map((c) => ({
      id: c.id,
      anchor: c.anchor,
      title: c.title,
      claim: c.claim,
      formula: c.formula ?? null,
      body: c.body,
    })),
  }
}

describe('the share catalogue', () => {
  it('matches the checked-in JSON the backend renders cards from', () => {
    const want = JSON.stringify(build(), null, 2) + '\n'
    if (process.env.UPDATE_SHARE_CATALOG) {
      writeFileSync(CATALOG, want, 'utf-8')
      return
    }
    expect(readFileSync(CATALOG, 'utf-8')).toBe(want)
  })
})

describe('share ids', () => {
  it('are unique across every shareable thing', () => {
    // Tips and concepts share one URL namespace (`/i/<id>`), so a collision
    // silently serves the wrong card rather than 404ing, which is worse.
    const ids = [...LEAN_TIPS.map((t) => t.id), ...CONCEPTS.map((c) => c.id)]
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('are URL-safe', () => {
    for (const id of [...LEAN_TIPS.map((t) => t.id), ...CONCEPTS.map((c) => c.id)]) {
      expect(id).toMatch(/^[a-z0-9-]{3,80}$/)
    }
  })

  it('every tip has one', () => {
    // A tip with no id has no share card, and the button would 404 on a URL
    // the user has already posted.
    for (const t of LEAN_TIPS) expect(t.id, t.text.slice(0, 50)).toBeTruthy()
  })
})

describe('concepts', () => {
  it('each point at a manual section that exists', () => {
    for (const c of CONCEPTS) {
      expect(MANUAL_ANCHORS[c.anchor], `${c.id} → #${c.anchor}`).toBeDefined()
    }
  })

  it('have a claim short enough to fit the card and to read as a headline', () => {
    for (const c of CONCEPTS) {
      expect(c.claim.length, c.id).toBeLessThanOrEqual(160)
      expect(c.claim.length, c.id).toBeGreaterThan(30)
    }
  })
})

describe('the sitemap', () => {
  it('lists every flow-science share page', () => {
    // These are indexable content pages with unique text and their own
    // animation. Adding a concept and forgetting the sitemap costs nothing
    // visible, which is exactly why it needs a test rather than a habit.
    const xml = readFileSync(resolve(__dirname, '../../public/sitemap.xml'), 'utf-8')
    for (const c of CONCEPTS) {
      expect(xml, c.id).toContain(`https://taktline.com/i/${c.id}`)
    }
  })
})
