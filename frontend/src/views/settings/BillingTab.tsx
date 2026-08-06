import { useCallback, useEffect, useState } from 'react'
import { billingApi, money, monthlyCentsFor, type Pricing, type Subscription }
  from '../../api/billing.api'
import { companiesApi } from '../../api/companies.api'
import { useAuthStore } from '../../store/auth.store'
import { color, font, size } from '../../theme/tokens'

/**
 * Settings → Billing: what this line costs, and why.
 *
 * There is no plan picker, because there is no plan to pick. The price IS the
 * station count — $2 a station, never less than the floor, never more than
 * the cap — so this screen's job is to show that arithmetic honestly: your N
 * stations × $2, clamped, with the two boundary numbers stated. Drawing a
 * station changes the price next period; nothing here needs a decision beyond
 * "start paying" and, later, the on-premise add-on and the portal.
 */
export default function BillingTab() {
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)
  const refreshMe = useAuthStore((s) => s.refresh)
  const [sub, setSub] = useState<Subscription | null>(null)
  const [pricing, setPricing] = useState<Pricing | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [wantOnPremise, setWantOnPremise] = useState(false)

  const load = useCallback(async () => {
    if (!activeCompanyId) return
    try {
      const [s, p] = await Promise.all([
        billingApi.subscription(activeCompanyId),
        billingApi.pricing(),
      ])
      setSub(s)
      setPricing(p)
      setWantOnPremise(s.onPremise)
    } catch (e) {
      setError(String(e))
    }
  }, [activeCompanyId])

  useEffect(() => { void load() }, [load])

  if (!activeCompanyId) return null
  if (!sub || !pricing) {
    return <p style={{ color: color.textDim, fontSize: 13 }}>{error ?? 'Loading…'}</p>
  }

  const paying = sub.plan === 'taktline' && sub.hasPaymentMethod
  const stations = sub.usage.stations
  const wouldPay = monthlyCentsFor(stations, pricing)
    + (wantOnPremise ? pricing.onpremCents : 0)

  const go = async (fn: () => Promise<{ url: string }>, key: string) => {
    setBusy(key); setError(null)
    try {
      const { url } = await fn()
      window.location.href = url
    } catch (e) {
      setError(String(e)); setBusy(null)
    }
  }

  const toggleOnPremise = async (enabled: boolean) => {
    setBusy('onprem'); setError(null)
    try {
      setSub(await billingApi.setOnPremise(activeCompanyId, enabled))
      setWantOnPremise(enabled)
      await refreshMe()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div style={{ maxWidth: 760 }}>
      <CurrentPlan sub={sub} pricing={pricing} />

      {sub.billingEnabled ? (
        sub.plan === 'free' ? (
          <>
            <h3 style={h3}>Go beyond {pricing.freeStations} stations</h3>
            <PriceExplainer pricing={pricing} stations={stations} />
            <label style={{
              display: 'flex', alignItems: 'center', gap: size.sp2,
              margin: `${size.sp4} 0`, fontSize: 13, color: color.textSecondary,
              cursor: 'pointer',
            }}>
              <input type="checkbox" checked={wantOnPremise}
                     onChange={(e) => setWantOnPremise(e.target.checked)} />
              Run on our own hardware (+{money(pricing.onpremCents)}/month)
            </label>
            <button onClick={() => go(() => billingApi.checkout(activeCompanyId, wantOnPremise),
                                      'checkout')}
                    disabled={busy === 'checkout'} style={primary}>
              {busy === 'checkout' ? 'Opening…'
                : `Subscribe — ${money(wouldPay)}/month for your ${stations || 'first'} station${stations === 1 ? '' : 's'}`}
            </button>
            <p style={note}>
              Handled by Stripe. Card and US bank transfer (ACH) are both accepted.
              The price follows your floor by itself: add a station and next
              month costs {money(pricing.perStationCents)} more, remove one and
              it costs {money(pricing.perStationCents)} less. Nothing to renegotiate.
            </p>
          </>
        ) : (
          <>
            {paying && (
              <label style={{
                display: 'flex', alignItems: 'center', gap: size.sp2,
                margin: `0 0 ${size.sp4}`, fontSize: 13, color: color.textSecondary,
                cursor: busy === 'onprem' ? 'wait' : 'pointer',
              }}>
                <input type="checkbox" checked={sub.onPremise}
                       disabled={busy === 'onprem'}
                       onChange={(e) => toggleOnPremise(e.target.checked)} />
                On-premise add-on (+{money(pricing.onpremCents)}/month) —{' '}
                {sub.onPremise ? 'removing credits your next invoice'
                               : 'adding is charged today, pro-rated'}
              </label>
            )}
            <div>
              <button
                onClick={() => go(() => billingApi.portal(activeCompanyId), 'portal')}
                disabled={busy === 'portal'}
                style={ghost}
              >
                {busy === 'portal' ? 'Opening…' : 'Payment method, invoices and cancellation'}
              </button>
              <p style={note}>
                Handled by Stripe. Cancelling stops the subscription
                immediately and returns the unused time to your card, less the
                processing fee the card network does not return to us. Nothing
                is ever deleted — a line of {pricing.freeStations} stations or
                fewer simply becomes a free account again, and a bigger one
                pauses until you come back.
              </p>
            </div>
          </>
        )
      ) : (
        <p style={note}>
          This deployment is not connected to a payment provider, so nothing here is
          metered or billed. That is how a self-hosted install runs.
        </p>
      )}

      {error && (
        <div style={{
          marginTop: size.sp4, padding: size.sp3, borderRadius: size.radius,
          border: `1px solid ${color.statusFault}55`, color: color.statusFault, fontSize: 13,
        }}>
          {error}
        </div>
      )}

      <DangerZone companyId={activeCompanyId} />
    </div>
  )
}

// ─── Deleting the company ────────────────────────────────────────────────────

/** Lives on the Billing tab on purpose: it is the one company page that stays
 *  reachable when an account is paused, so deletion is never locked behind the
 *  paywall it might be trying to escape. The server requires the exact name
 *  and a super_admin; this mirrors both so the refusals are predictable. */
function DangerZone({ companyId }: { companyId: string }) {
  const companies = useAuthStore((s) => s.companies)
  const refreshMe = useAuthStore((s) => s.refresh)
  const me = companies.find((c) => c.id === companyId)
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!me || me.role !== 'super_admin') return null
  const armed = typed.trim() === me.name

  const doDelete = async () => {
    setBusy(true); setError(null)
    try {
      await companiesApi.delete(companyId, typed.trim())
      localStorage.removeItem('taktline.activeCompanyId')
      await refreshMe()
      window.location.href = '/'
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e))
      setBusy(false)
    }
  }

  return (
    <div style={{
      marginTop: size.sp8, padding: size.sp4, borderRadius: size.radiusMd,
      border: `1px solid ${color.statusFault}55`,
    }}>
      <div style={{ fontSize: 12, fontFamily: font.mono, letterSpacing: '0.1em',
                    color: color.statusFault, marginBottom: size.sp2 }}>
        DANGER ZONE
      </div>
      {!open ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3 }}>
          <span style={{ fontSize: 13, color: color.textSecondary }}>
            Delete this company and everything in it.
          </span>
          <button onClick={() => setOpen(true)} style={{
            background: 'transparent', border: `1px solid ${color.statusFault}88`,
            color: color.statusFault, borderRadius: size.radius, padding: '6px 12px',
            fontSize: 12.5, cursor: 'pointer',
          }}>
            Delete company…
          </button>
        </div>
      ) : (
        <div style={{ fontSize: 13, color: color.textSecondary, lineHeight: 1.6 }}>
          <p style={{ margin: 0 }}>
            This deletes <b style={{ color: color.textPrimary }}>{me.name}</b>{' '}
            permanently: every station, route, lot, work session, statistic,
            production order and member — for everyone, not just you. There is
            no undo and no restore. A paid subscription is cancelled and the
            unused time refunded.
          </p>
          <p style={{ margin: `${size.sp3} 0 ${size.sp2}` }}>
            Type the company&apos;s exact name to confirm:
          </p>
          <div style={{ display: 'flex', gap: size.sp2, alignItems: 'center' }}>
            <input
              value={typed} onChange={(e) => setTyped(e.target.value)}
              placeholder={me.name} autoFocus
              style={{
                flex: '0 1 260px', padding: '7px 10px', fontSize: 13,
                background: color.bgInput, color: color.textPrimary,
                border: `1px solid ${armed ? color.statusFault : color.border}`,
                borderRadius: size.radius,
              }}
            />
            <button onClick={doDelete} disabled={!armed || busy} style={{
              background: armed ? color.statusFault : 'transparent',
              border: `1px solid ${color.statusFault}${armed ? '' : '55'}`,
              color: armed ? '#fff' : color.textDisabled,
              borderRadius: size.radius, padding: '7px 14px', fontSize: 12.5,
              cursor: armed && !busy ? 'pointer' : 'default',
            }}>
              {busy ? 'Deleting…' : 'Delete forever'}
            </button>
            <button onClick={() => { setOpen(false); setTyped('') }} style={{
              background: 'none', border: 'none', color: color.textDim,
              fontSize: 12.5, cursor: 'pointer',
            }}>
              Cancel
            </button>
          </div>
          {error && (
            <div style={{ marginTop: size.sp2, color: color.statusFault, fontSize: 12.5 }}>
              {String(error)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Current plan ────────────────────────────────────────────────────────────

function CurrentPlan({ sub, pricing }: { sub: Subscription; pricing: Pricing }) {
  const used = sub.usage.stations
  const limit = sub.usage.stationLimit
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0
  const over = limit !== null && used > limit
  const near = limit !== null && !over && used >= limit * 0.8

  return (
    <section style={{
      border: `1px solid ${color.border}`, borderRadius: size.radiusMd,
      padding: size.sp5, marginBottom: size.sp6, background: color.bgCard,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp3, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 20, fontWeight: 600, color: color.textPrimary }}>
          {sub.planLabel}
        </span>
        {sub.onPremise && <Chip>on-premise</Chip>}
        {sub.monthlyCents > 0 && (
          <span style={{ fontSize: 14, color: color.textSecondary }}>
            {money(sub.monthlyCents)}/month
            {' · '}{used} station{used === 1 ? '' : 's'}
          </span>
        )}
        <StateChip sub={sub} />
      </div>

      <Deadline sub={sub} />

      {limit !== null && (
        <div style={{ marginTop: size.sp4 }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between', fontSize: 12.5,
            color: over ? color.statusFault : near ? color.statusWarning : color.textSecondary,
          }}>
            <span>{used} of {limit} stations</span>
            {over && <span>over by {used - limit}</span>}
          </div>
          <div style={{
            marginTop: 6, height: 6, borderRadius: 3, background: color.border,
            overflow: 'hidden',
          }}>
            <div style={{
              width: `${over ? 100 : pct}%`, height: '100%',
              background: over ? color.statusFault
                        : near ? color.statusWarning : color.statusRunning,
              transition: 'width 300ms ease',
            }} />
          </div>
        </div>
      )}

      <div style={{ marginTop: size.sp3, fontSize: 12.5, color: color.textDim }}>
        {sub.integrations
          ? 'Every ERP and shop-system connector is included.'
          : `Integrations come with the paid plan — every connector included, ` +
            `unlimited stations at ${money(pricing.perStationCents)} each.`}
      </div>
    </section>
  )
}

/** The whole model, in one strip the reader can check with a pencil. */
function PriceExplainer({ pricing, stations }: { pricing: Pricing; stations: number }) {
  const rows: Array<[string, string]> = [
    [`Up to ${pricing.freeStations} stations`, 'free, forever'],
    [`${money(pricing.perStationCents)} per station / month`,
     `never less than ${money(pricing.minimumCents)}`],
    [`From ${pricing.capStations} stations`,
     `capped at ${money(pricing.capCents)} — you will never pay more`],
  ]
  return (
    <div style={{
      display: 'grid', gap: 6, margin: `0 0 ${size.sp2}`,
      fontSize: 13, color: color.textSecondary,
    }}>
      {rows.map(([a, b]) => (
        <div key={a} style={{ display: 'flex', gap: size.sp3 }}>
          <span style={{ minWidth: 210, color: color.textPrimary }}>{a}</span>
          <span style={{ color: color.textDim }}>{b}</span>
        </div>
      ))}
      {stations > 0 && (
        <div style={{ marginTop: 4, fontFamily: font.mono, fontSize: 12.5 }}>
          Your line today: {stations} × {money(pricing.perStationCents)} →{' '}
          {money(monthlyCentsFor(stations, pricing))}/month
        </div>
      )}
    </div>
  )
}

function Deadline({ sub }: { sub: Subscription }) {
  const when = sub.state === 'read_only' ? sub.graceEndsAt : sub.currentPeriodEnd
  if (!when) return null
  const date = new Date(when.endsWith('Z') || when.includes('+') ? when : `${when}Z`)
  const days = Math.max(0, Math.ceil((date.getTime() - Date.now()) / 86_400_000))
  const label = sub.state === 'read_only' ? 'Read-only until' : 'Renews'
  return (
    <div style={{ marginTop: size.sp2, fontSize: 13, color: color.textSecondary }}>
      {label} {date.toLocaleDateString()} · {days} day{days === 1 ? '' : 's'}
      {sub.state === 'read_only' &&
        ' — after that the account will be completely paused. Nothing is deleted.'}
    </div>
  )
}

function StateChip({ sub }: { sub: Subscription }) {
  if (sub.settling) {
    return <Chip tone={color.statusWarning}>bank transfer clearing</Chip>
  }
  if (sub.state === 'read_only') return <Chip tone={color.statusWarning}>read-only</Chip>
  if (sub.state === 'locked') return <Chip tone={color.statusFault}>paused</Chip>
  return null
}

function Chip({ children, tone = color.textDim }: { children: React.ReactNode; tone?: string }) {
  return (
    <span style={{
      fontSize: 10.5, fontFamily: font.mono, letterSpacing: '0.06em',
      textTransform: 'uppercase', color: tone,
      border: `1px solid ${tone}55`, borderRadius: size.radiusFull, padding: '1px 8px',
    }}>
      {children}
    </span>
  )
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const h3 = {
  fontSize: 14, fontWeight: 600, color: color.textPrimary,
  margin: `0 0 ${size.sp3}`,
} as const

const note = {
  fontSize: 12, color: color.textDim, lineHeight: 1.5, margin: `${size.sp2} 0 0`,
} as const

const primary = {
  background: color.bluePrimary, color: '#fff', border: 'none',
  borderRadius: size.radius, padding: '10px 20px', fontSize: 13.5, fontWeight: 600,
  cursor: 'pointer', fontFamily: 'inherit',
} as const

const ghost = {
  background: 'none', color: color.textSecondary, border: `1px solid ${color.border}`,
  borderRadius: size.radius, padding: '8px 16px', fontSize: 13, cursor: 'pointer',
  fontFamily: 'inherit',
} as const
