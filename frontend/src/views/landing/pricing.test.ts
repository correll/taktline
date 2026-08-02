import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * The price on the website must be the price the server charges.
 *
 * The landing page hard-codes its numbers on purpose — it renders for
 * signed-out visitors and for crawlers, and a pricing table that arrives after
 * a round trip is one search engines never see. The cost of that choice is
 * exactly this: two places to change, and a silent, expensive failure if only
 * one of them is. So the numbers are checked against `core/plans.py`, which is
 * what Stripe is actually told to bill.
 */

const plansPy = readFileSync(
  resolve(__dirname, '../../../../backend/app/core/plans.py'), 'utf-8')

function centsFor(code: string): number {
  const block = plansPy.split(`"${code}": Plan(`)[1]
  const m = block?.match(/monthly_cents=(\d+)/)
  if (!m) throw new Error(`no monthly_cents for ${code} in plans.py`)
  return Number(m[1])
}

const landing = readFileSync(resolve(__dirname, 'LandingView.tsx'), 'utf-8')
const indexHtml = readFileSync(resolve(__dirname, '../../../index.html'), 'utf-8')

describe('the advertised price is the charged price', () => {
  it('reads real numbers out of plans.py', () => {
    // Guard the guard: a parser that silently returned 0 would make every
    // assertion below vacuous.
    expect(centsFor('basic_50')).toBeGreaterThan(0)
    expect(centsFor('pro_100')).toBeGreaterThan(centsFor('basic_50'))
  })

  it('matches the landing page', () => {
    for (const code of ['basic_50', 'pro_50', 'pro_100', 'plant_250']) {
      const dollars = centsFor(code) / 100
      expect(landing, `$${dollars} (${code}) missing from the landing page`)
        .toContain(`$${dollars}`)
    }
    for (const konst of ['ONPREM_CENTS', 'CONNECTOR_CENTS']) {
      const dollars = Number(plansPy.match(new RegExp(`${konst} = (\\d+)`))![1]) / 100
      expect(landing, `$${dollars} (${konst}) missing from the landing page`)
        .toContain(`$${dollars}`)
    }
  })

  it('matches the JSON-LD offers a crawler reads', () => {
    const json = JSON.parse(
      indexHtml.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)![1])
    const offers: { name: string; price: string }[] = json.offers.offers
    const byName: Record<string, string> = {
      basic_50: 'Basic', pro_50: 'Professional', pro_100: 'Professional 100',
      plant_250: 'Plant',
    }
    for (const [code, name] of Object.entries(byName)) {
      const offer = offers.find((o) => o.name === name)
      expect(offer, `no JSON-LD offer named ${name}`).toBeDefined()
      expect(Number(offer!.price)).toBe(centsFor(code) / 100)
    }
    expect(Number(json.offers.lowPrice)).toBe(centsFor('basic_50') / 100)
    expect(Number(json.offers.highPrice)).toBe(centsFor('plant_250') / 100)
  })

  it('no longer promises anything free forever', () => {
    // The old claim appeared in fifteen places. It is the kind of thing that
    // gets reintroduced by a copy-paste from an old section.
    for (const [name, text] of [['LandingView', landing], ['index.html', indexHtml]] as const) {
      const prose = text.replace(/^\s*\*.*$/gm, '')   // ignore code comments
      expect(prose.toLowerCase(), `${name} still promises free forever`)
        .not.toContain('free forever')
      expect(prose.toLowerCase(), `${name} still promises free, forever`)
        .not.toContain('free, forever')
    }
  })
})
