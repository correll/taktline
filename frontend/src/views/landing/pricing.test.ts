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
 *
 * The model has two halves and this file guards both. **Free and Shop carry a
 * number** and must agree with `plans.py`. **Plant and Enterprise carry none**
 * — and that is a promise as much as a price is, because a number published
 * beside "talk to us" is a negotiating position given away. There is a test
 * below that fails if one appears.
 */

const plansPy = readFileSync(
  resolve(__dirname, '../../../../backend/app/core/plans.py'), 'utf-8')

function constant(name: string): number {
  // Values in plans.py may carry Python digit separators: 20_000.
  const m = plansPy.match(new RegExp(`^${name} = ([\\d_]+)`, 'm'))
  if (!m) throw new Error(`no ${name} in plans.py`)
  return Number(m[1].replace(/_/g, ''))
}

const landing = readFileSync(resolve(__dirname, 'LandingView.tsx'), 'utf-8')
const indexHtml = readFileSync(resolve(__dirname, '../../../index.html'), 'utf-8')

// Every other surface that quotes the offer. The ghost check below ran only
// against the landing page for a while, and "Two weeks free" survived on
// exactly the pages it did not read.
const otherSurfaces: Array<[string, string]> = [
  ['ShareView', resolve(__dirname, '../share/ShareView.tsx')],
  ['ManualView', resolve(__dirname, 'ManualView.tsx')],
  ['network.py', resolve(__dirname, '../../../../backend/app/core/network.py')],
].map(([name, path]) => [name as string, readFileSync(path as string, 'utf-8')])

/** What a Shop line of this size costs — mirrored from `plans.monthly_cents_for`
 *  so the test derives the endpoints rather than restating them. */
function shopCents(stations: number): number {
  const base = constant('SHOP_BASE_CENTS')
  const baseStations = constant('SHOP_BASE_STATIONS')
  const step = constant('SHOP_PER_STATION_CENTS')
  const cap = constant('SHOP_STATIONS')
  const billable = Math.min(Math.max(stations, baseStations), cap)
  return base + (billable - baseStations) * step
}

describe('the advertised price is the charged price', () => {
  it('reads real numbers out of plans.py', () => {
    // Guard the guard: a parser that silently returned 0 would make every
    // assertion below vacuous.
    expect(constant('FREE_STATIONS')).toBeGreaterThan(0)
    expect(constant('SHOP_BASE_CENTS')).toBeGreaterThan(0)
    expect(constant('SHOP_PER_STATION_CENTS')).toBeGreaterThan(0)
    expect(constant('SHOP_STATIONS')).toBeGreaterThan(constant('SHOP_BASE_STATIONS'))
  })

  it('matches the landing page', () => {
    const free = constant('FREE_STATIONS')
    const base = constant('SHOP_BASE_CENTS') / 100
    const baseStations = constant('SHOP_BASE_STATIONS')
    const step = constant('SHOP_PER_STATION_CENTS') / 100
    const cap = constant('SHOP_STATIONS')

    for (const [what, needle] of [
      ['the free tier', `up to ${free} stations`],
      ['the Shop base', `$${base}`],
      ['the Shop band', `${baseStations}–${cap} stations`],
      ['the per-station step', `$${step}`],
    ] as Array<[string, string]>) {
      expect(landing, `${what} (${needle}) missing from the landing page`)
        .toContain(needle)
    }
  })

  it('matches the JSON-LD offers a crawler reads', () => {
    const json = JSON.parse(
      indexHtml.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)![1])
    const offers: { name: string; price: string }[] = json.offers.offers
    const shop = offers.find((o) => o.name === 'Shop')
    const free = offers.find((o) => o.name === 'Free')
    expect(free, 'no JSON-LD offer named Free').toBeDefined()
    expect(Number(free!.price)).toBe(0)
    expect(shop, 'no JSON-LD offer named Shop').toBeDefined()
    expect(Number(shop!.price)).toBe(constant('SHOP_BASE_CENTS') / 100)
    expect(Number(json.offers.lowPrice)).toBe(0)
    // The top of what is *published*, which is a full Shop line — not the top
    // of what anyone can pay, because Plant and Enterprise have no number.
    expect(Number(json.offers.highPrice))
      .toBe(shopCents(constant('SHOP_STATIONS')) / 100)
  })

  it('puts no number on the tiers that are a conversation', () => {
    // The whole point of "talk to us" is that the number is set with the
    // customer. A figure printed beside it — even an "up to" or a "from" — is
    // the negotiating position given away, and it is the single most likely
    // thing to be helpfully added by someone tidying the page later.
    const section = landing.slice(landing.indexOf('const TIERS'),
                                  landing.indexOf('const ADD_ONS'))
    expect(section, 'the tier table lost its contact tiers')
      .toMatch(/name: 'Plant'[\s\S]*name: 'Enterprise'/)

    for (const tier of ['Plant', 'Enterprise']) {
      const start = section.indexOf(`name: '${tier}'`)
      const end = section.indexOf('  },', start)
      const block = section.slice(start, end)
      expect(block, `the ${tier} tier quotes a price`).not.toMatch(/\$[\d,]/)
      expect(block, `the ${tier} tier is not marked as a conversation`)
        .toContain('contact: true')
    }
  })

  it('never promises a retired price again', () => {
    // The old model is the copy-paste most likely to come back. A page quoting
    // "$2 a station" or "capped at $399" is quoting a price list that no
    // longer exists — and the flat-rate promise is the one that would be
    // quoted back at us hardest.
    for (const ghost of ['$58', '$116', '$290', 'up to 50 stations',
                         'up to 100 stations', 'up to 250 stations',
                         'Two weeks free', 'two weeks free', 'after two weeks',
                         'up to 3 stations', 'for three stations',
                         '$2 a station', '$2 per station', '$399', '$29 minimum',
                         'never more than']) {
      expect(landing, `the landing page still quotes ${ghost}`).not.toContain(ghost)
      expect(indexHtml, `index.html still quotes ${ghost}`).not.toContain(ghost)
      for (const [name, text] of otherSurfaces) {
        expect(text, `${name} still quotes ${ghost}`).not.toContain(ghost)
      }
    }
  })

  it('never quotes the step without saying what the base covers', () => {
    // "$45 a station" reads as "a 10-station line pays $450" — it pays $290.
    // The step is meaningless without the base it steps from, so every mention
    // has to carry one in the same breath. (The flat-rate model had the same
    // failure with its floor, caught live by the founder.)
    for (const [name, text] of [['LandingView', landing], ['index.html', indexHtml]] as const) {
      for (const line of text.split('\n')) {
        if (/\$45 (a|per|for each|each)/.test(line) || /\$45 for each/.test(line)) {
          expect(/\$200|first eight|first 8|after that|base/i.test(line),
            `${name} quotes the $45 step without the $200 base: "${line.trim()}"`)
            .toBe(true)
        }
      }
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
