import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import type { PlanRefusal } from '../api/client'
import { usePlan } from '../auth/usePlan'
import { useRole } from '../auth/useRole'
import { color, font, shadow, size } from '../theme/tokens'

/**
 * Everything the app says about a plan, in two components.
 *
 * `PlanBanner` is standing state — trial ending, read-only, locked — modelled
 * on `OutageBanner`: a full-width strip above the view, words and an action,
 * never colour alone. Deliberately **not** a toast: `Toast` sets
 * `pointerEvents: 'none'`, so it cannot hold the link that makes it useful, and
 * a refusal should be a sentence someone can act on rather than a notification
 * that something failed.
 *
 * `PlanRefusalDialog` is the reply to a specific action — the 402 or 403 the
 * server just returned. It comes up where the user is, rather than bouncing
 * them to Settings and losing their place.
 */

// ─── Standing state ──────────────────────────────────────────────────────────

export function PlanBanner() {
  const plan = usePlan()
  const { isSuperAdmin } = useRole()
  const [dismissed, setDismissed] = useState(false)

  if (plan.isSandbox) return null                 // the sandbox chip says it already

  let tone: string = color.statusWarning
  let text: string | null = null

  if (plan.locked) {
    tone = color.statusFault
    text = 'This account is paused because a payment did not go through. Your data is safe.'
  } else if (plan.readOnly) {
    text = 'Read-only until a payment goes through. You can still see and export everything.'
  } else if (plan.atStationLimit) {
    text = plan.isFree
      ? `The free tier covers ${plan.stationLimit} stations — the next one is $2/month each.`
      : `You are at your plan's limit of ${plan.stationLimit} stations.`
  }

  // A locked account cannot dismiss its way out — there is nothing else to see.
  if (!text || (dismissed && !plan.locked)) return null

  return (
    <div role="status" style={{
      display: 'flex', alignItems: 'center', gap: size.sp3,
      padding: `${size.sp2} ${size.sp5}`,
      background: `${tone}1A`, borderBottom: `1px solid ${tone}55`,
      fontSize: 13, color: color.textPrimary,
    }}>
      <span aria-hidden="true" style={{ color: tone, fontSize: 15, lineHeight: 1 }}>●</span>
      <span>{text}</span>
      {isSuperAdmin ? (
        <Link to="/settings?tab=billing" style={{
          color: color.blueBright, fontWeight: 600, textDecoration: 'none',
        }}>
          {plan.locked || plan.readOnly ? 'Fix billing' : 'See pricing'}
        </Link>
      ) : (
        <span style={{ color: color.textDim, fontSize: 12 }}>
          Ask an administrator to update the plan.
        </span>
      )}
      {!plan.locked && (
        <button onClick={() => setDismissed(true)} aria-label="Dismiss" style={{
          marginLeft: 'auto', background: 'none', border: 'none', color: color.textDim,
          cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0,
        }}>
          ×
        </button>
      )}
    </div>
  )
}

// ─── The reply to one refused action ─────────────────────────────────────────

export function PlanRefusalDialog() {
  const [refusal, setRefusal] = useState<PlanRefusal | null>(null)
  const { isSuperAdmin } = useRole()

  useEffect(() => {
    const onRefusal = (e: Event) => setRefusal((e as CustomEvent<PlanRefusal>).detail)
    window.addEventListener('taktline:plan-refusal', onRefusal)
    return () => window.removeEventListener('taktline:plan-refusal', onRefusal)
  }, [])

  if (!refusal) return null
  const close = () => setRefusal(null)

  const heading =
    refusal.code === 'plan_limit' && refusal.resource === 'integrations'
      ? 'Integrations come with the paid plan'
      : refusal.code === 'plan_limit' ? 'The free tier stops here'
      : refusal.code === 'read_only' ? 'This account is read-only'
      : 'This account is paused'

  return createPortal(
    <div onClick={close} style={{
      position: 'fixed', inset: 0, zIndex: 9600, background: 'rgba(0,0,0,0.55)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: size.sp4,
    }}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-label={heading}
           style={{
             width: 460, maxWidth: '100%', background: color.bgPanel,
             border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
             boxShadow: shadow.lg, padding: size.sp5,
           }}>
        <div style={{
          fontSize: 10, fontFamily: font.mono, letterSpacing: '0.12em',
          textTransform: 'uppercase', color: color.textDim,
        }}>
          Plan
        </div>
        <h2 style={{ margin: `${size.sp2} 0 0`, fontSize: 18, fontWeight: 600,
                     color: color.textPrimary, lineHeight: 1.3 }}>
          {heading}
        </h2>
        <p style={{ margin: `${size.sp3} 0 0`, fontSize: 13.5, lineHeight: 1.6,
                    color: color.textSecondary }}>
          {refusal.message}
        </p>

        {refusal.limit !== undefined && refusal.used !== undefined && (
          <div style={{
            marginTop: size.sp4, padding: `${size.sp2} ${size.sp3}`,
            background: color.bgCard, borderRadius: size.radius,
            fontSize: 12, fontFamily: font.mono, color: color.textDim,
          }}>
            {refusal.used} used · {refusal.limit} included
          </div>
        )}

        <div style={{ display: 'flex', gap: size.sp2, marginTop: size.sp5 }}>
          {isSuperAdmin && (
            <Link to="/settings?tab=billing" onClick={close} style={{
              background: color.bluePrimary, color: '#fff', textDecoration: 'none',
              borderRadius: size.radius, padding: '8px 18px', fontSize: 13, fontWeight: 600,
            }}>
              See pricing
            </Link>
          )}
          <button onClick={close} style={{
            background: 'none', border: `1px solid ${color.border}`,
            borderRadius: size.radius, color: color.textSecondary, fontSize: 13,
            padding: '8px 16px', cursor: 'pointer', fontFamily: 'inherit',
          }}>
            {isSuperAdmin ? 'Not now' : 'Close'}
          </button>
        </div>

        {!isSuperAdmin && (
          <p style={{ margin: `${size.sp3} 0 0`, fontSize: 12, color: color.textDim }}>
            An administrator can change the plan in Settings → Billing.
          </p>
        )}
      </div>
    </div>,
    document.body,
  )
}
