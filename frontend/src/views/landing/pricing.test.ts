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

function constant(name: string): number {
  // Values in plans.py may carry Python digit separators: 39_900.
  const m = plansPy.match(new RegExp(`${name} = ([\\d_]+)`))
  if (!m) throw new Error(`no ${name} in plans.py`)
  return Number(m[1].replace(/_/g, ''))
}

const landing = readFileSync(resolve(__dirname, 'LandingView.tsx'), 'utf-8')
const indexHtml = readFileSync(resolve(__dirname, '../../../index.html'), 'utf-8')

describe('the advertised price is the charged price', () => {
  it('reads real numbers out of plans.py', () => {
    // Guard the guard: a parser that silently returned 0 would make every
    // assertion below vacuous.
    expect(constant('PER_STATION_CENTS')).toBeGreaterThan(0)
    expect(constant('CAP_CENTS')).toBeGreaterThan(constant('MIN_CENTS'))
  })

  it('matches the landing page', () => {
    const perStation = constant('PER_STATION_CENTS') / 100
    const min = constant('MIN_CENTS') / 100
    const cap = constant('CAP_CENTS') / 100
    const free = constant('FREE_STATIONS')
    const onprem = constant('ONPREM_CENTS') / 100

    for (const [what, needle] of [
      ['the per-station price', `$${perStation} per station`],
      ['the floor', `$${min}`],
      ['the cap', `$${cap}`],
      ['the free tier', `up to ${free} stations`],
      ['on-premise', `$${onprem}/month`],
    ] as Array<[string, string]>) {
      expect(landing, `${what} (${needle}) missing from the landing page`)
        .toContain(needle)
    }
  })

  it('matches the JSON-LD offers a crawler reads', () => {
    const json = JSON.parse(
      indexHtml.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)![1])
    const offers: { name: string; price: string }[] = json.offers.offers
    const paid = offers.find((o) => o.name === 'Taktline')
    const free = offers.find((o) => o.name === 'Free')
    expect(free, 'no JSON-LD offer named Free').toBeDefined()
    expect(Number(free!.price)).toBe(0)
    expect(paid, 'no JSON-LD offer named Taktline').toBeDefined()
    expect(Number(paid!.price)).toBe(constant('PER_STATION_CENTS') / 100)
    expect(Number(json.offers.lowPrice)).toBe(0)
    expect(Number(json.offers.highPrice)).toBe(constant('CAP_CENTS') / 100)
  })

  it('never promises a banded plan again', () => {
    // The retired tiers are the copy-paste most likely to come back. A page
    // quoting "$116/month" or "up to 50 stations" is quoting a price list
    // that no longer exists.
    for (const ghost of ['$58', '$116', '$290', 'up to 50 stations',
                         'up to 100 stations', 'up to 250 stations']) {
      expect(landing, `the landing page still quotes ${ghost}`).not.toContain(ghost)
      expect(indexHtml, `index.html still quotes ${ghost}`).not.toContain(ghost)
    }
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
