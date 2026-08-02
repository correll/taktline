import { useCallback, useEffect, useState } from 'react'
import { billingApi, money, type Plan, type Subscription } from '../../api/billing.api'
import { useAuthStore } from '../../store/auth.store'
import { color, font, size } from '../../theme/tokens'

/**
 * Settings → Billing: what you are on, what you are using, and what else there
 * is.
 *
 * Two things this screen is careful about.
 *
 * **It says what a change will cost, before it happens.** Proration is the
 * part of a subscription people distrust, and with reason — most products let
 * you click "downgrade" and then send a bill that does not match. Upgrades are
 * charged now, pro-rated for the days remaining; downgrades credit forward.
 * Both are stated on the button.
 *
 * **It never shows a control that cannot work.** Over your station count for
 * the plan you are picking, the button explains what to remove rather than
 * failing after the click.
 */
export default function BillingTab() {
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)
  const refreshMe = useAuthStore((s) => s.refresh)
  const [sub, setSub] = useState<Subscription | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [onPremise, setOnPremise] = useState(false)

  const load = useCallback(async () => {
    if (!activeCompanyId) return
    try {
      const [s, p] = await Promise.all([
        billingApi.subscription(activeCompanyId),
        billingApi.plans(),
      ])
      setSub(s)
      setPlans(p.filter((x) => x.purchasable))
      setOnPremise(s.onPremise)
    } catch (e) {
      setError(String(e))
    }
  }, [activeCompanyId])

  useEffect(() => { void load() }, [load])

  if (!activeCompanyId) return null
  if (!sub) {
    return <p style={{ color: color.textDim, fontSize: 13 }}>{error ?? 'Loading…'}</p>
  }

  const go = async (fn: () => Promise<{ url: string }>, key: string) => {
    setBusy(key); setError(null)
    try {
      const { url } = await fn()
      window.location.href = url
    } catch (e) {
      setError(String(e)); setBusy(null)
    }
  }

  const switchTo = async (code: string) => {
    setBusy(code); setError(null)
    try {
      if (sub.hasPaymentMethod && sub.plan !== 'trial') {
        setSub(await billingApi.changePlan(activeCompanyId, code, onPremise))
        await refreshMe()
      } else {
        const { url } = await billingApi.checkout(activeCompanyId, code, onPremise)
        window.location.href = url
        return
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div style={{ maxWidth: 760 }}>
      <CurrentPlan sub={sub} />

      {sub.billingEnabled ? (
        <>
          <h3 style={h3}>{sub.plan === 'trial' ? 'Choose a plan' : 'Change plan'}</h3>
          <label style={{
            display: 'flex', alignItems: 'center', gap: size.sp2, margin: `0 0 ${size.sp4}`,
            fontSize: 13, color: color.textSecondary, cursor: 'pointer',
          }}>
            <input type="checkbox" checked={onPremise}
                   onChange={(e) => setOnPremise(e.target.checked)} />
            Run on our own hardware (+$199/month)
          </label>

          <div style={{ display: 'grid', gap: size.sp3 }}>
            {plans.map((p) => (
              <PlanCard
                key={p.code} plan={p} sub={sub} onPremise={onPremise}
                busy={busy === p.code}
                onPick={() => switchTo(p.code)}
              />
            ))}
          </div>

          {sub.hasPaymentMethod && (
            <div style={{ marginTop: size.sp5 }}>
              <button
                onClick={() => go(() => billingApi.portal(activeCompanyId), 'portal')}
                disabled={busy === 'portal'}
                style={ghost}
              >
                {busy === 'portal' ? 'Opening…' : 'Payment method, invoices and cancellation'}
              </button>
              <p style={note}>
                Handled by Stripe. Card and US bank transfer (ACH) are both accepted;
                bank transfer costs us less, so it is the one we prefer on the larger plans.
              </p>
            </div>
          )}
        </>
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
    </div>
  )
}

// ─── Current plan ────────────────────────────────────────────────────────────

function CurrentPlan({ sub }: { sub: Subscription }) {
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
          ? 'ERP and shop-system integrations are included.'
          : 'Integrations are not included on this plan.'}
      </div>
    </section>
  )
}

function Deadline({ sub }: { sub: Subscription }) {
  const when = sub.state === 'read_only' ? sub.graceEndsAt
             : sub.plan === 'trial' ? sub.trialEndsAt
             : sub.currentPeriodEnd
  if (!when) return null
  const date = new Date(when.endsWith('Z') || when.includes('+') ? when : `${when}Z`)
  const days = Math.max(0, Math.ceil((date.getTime() - Date.now()) / 86_400_000))
  const label = sub.state === 'read_only' ? 'Read-only until'
              : sub.plan === 'trial' ? 'Trial ends'
              : 'Renews'
  return (
    <div style={{ marginTop: size.sp2, fontSize: 13, color: color.textSecondary }}>
      {label} {date.toLocaleDateString()} · {days} day{days === 1 ? '' : 's'}
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

// ─── One plan ────────────────────────────────────────────────────────────────

function PlanCard({ plan, sub, onPremise, busy, onPick }: {
  plan: Plan; sub: Subscription; onPremise: boolean; busy: boolean; onPick: () => void
}) {
  const current = plan.code === sub.plan && onPremise === sub.onPremise
  const total = plan.monthlyCents + (onPremise ? 19900 : 0)
  const currentTotal = sub.monthlyCents
  const isUpgrade = total > currentTotal
  const tooSmall = plan.stations !== null && sub.usage.stations > plan.stations

  return (
    <div style={{
      border: `1px solid ${current ? color.bluePrimary : color.border}`,
      borderRadius: size.radiusMd, padding: size.sp4,
      background: current ? `${color.bluePrimary}0D` : 'transparent',
      display: 'flex', alignItems: 'center', gap: size.sp4, flexWrap: 'wrap',
    }}>
      <div style={{ flex: 1, minWidth: 240 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp2 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: color.textPrimary }}>
            {plan.label}
          </span>
          <span style={{ fontSize: 14, color: color.textSecondary }}>
            {money(total)}/month
          </span>
          {current && <Chip tone={color.blueBright}>current</Chip>}
        </div>
        <p style={{ margin: `4px 0 0`, fontSize: 12.5, color: color.textDim, lineHeight: 1.5 }}>
          {plan.blurb}
        </p>
      </div>

      {!current && (
        <div style={{ textAlign: 'right' }}>
          <button onClick={onPick} disabled={busy || tooSmall}
                  style={tooSmall ? ghostDisabled : primary}>
            {busy ? 'Working…'
              : sub.hasPaymentMethod && sub.plan !== 'trial'
                ? (isUpgrade ? 'Upgrade' : 'Switch')
                : 'Choose'}
          </button>
          <div style={{ ...note, marginTop: 4, maxWidth: 260, textAlign: 'right' }}>
            {tooSmall
              ? `Remove ${sub.usage.stations - (plan.stations ?? 0)} stations first`
              : sub.hasPaymentMethod && sub.plan !== 'trial'
                ? (isUpgrade
                    ? 'Charged today for the days left in this month'
                    : 'Credited to your next invoice, to the day')
                : ''}
          </div>
        </div>
      )}
    </div>
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
  borderRadius: size.radius, padding: '8px 18px', fontSize: 13, fontWeight: 600,
  cursor: 'pointer', fontFamily: 'inherit',
} as const

const ghost = {
  background: 'none', color: color.textSecondary, border: `1px solid ${color.border}`,
  borderRadius: size.radius, padding: '8px 16px', fontSize: 13, cursor: 'pointer',
  fontFamily: 'inherit',
} as const

const ghostDisabled = { ...ghost, opacity: 0.5, cursor: 'not-allowed' } as const
