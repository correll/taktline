import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { billingApi, type TrialStop } from '../../api/billing.api'
import { TaktlineLogo } from '../../components/TaktlineLogo'
import { color, font, size } from '../../theme/tokens'

/**
 * Where the "stop these emails" link in a trial email lands.
 *
 * It describes before it destroys. The link in the email is a GET, and a GET
 * that deletes an account is deleted by the first corporate mail filter that
 * prefetches links — the customer never sees the message, and their line is
 * gone. So this page loads, says exactly what will be lost, and asks.
 *
 * Public: the token in the URL is the authorisation, and all it can do is show
 * this page or delete a company that is still on a trial.
 */
export default function TrialStopView() {
  const [params] = useSearchParams()
  const company = params.get('company') ?? ''
  const token = params.get('token') ?? ''

  const [info, setInfo] = useState<TrialStop | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'gone' | 'error'>('loading')
  const [message, setMessage] = useState('')

  useEffect(() => {
    billingApi.describeTrialStop(company, token)
      .then((r) => { setInfo(r); setState('ready') })
      .catch((e) => { setMessage(String(e)); setState('error') })
  }, [company, token])

  const stop = async () => {
    try {
      await billingApi.stopTrial(company, token)
      setState('gone')
    } catch (e) {
      setMessage(String(e)); setState('error')
    }
  }

  return (
    <div style={{
      minHeight: '100vh', background: color.bgDeep, display: 'flex',
      alignItems: 'center', justifyContent: 'center', padding: size.sp6,
      fontFamily: font.sans,
    }}>
      <div style={{
        width: 520, maxWidth: '100%', background: color.bgPanel,
        border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
        padding: size.sp6,
      }}>
        <Link to="/" style={{ display: 'inline-flex', color: color.textPrimary }}>
          <TaktlineLogo height={22} color={color.textPrimary} />
        </Link>

        {state === 'loading' && <p style={body}>Checking…</p>}

        {state === 'error' && (
          <>
            <h1 style={h1}>This link is no longer valid</h1>
            <p style={body}>
              It may already have been used, or the account may have moved onto a
              paid plan. {message}
            </p>
            <Link to="/" style={link}>Go to Taktline</Link>
          </>
        )}

        {state === 'gone' && (
          <>
            <h1 style={h1}>Deleted</h1>
            <p style={body}>
              The account and everything in it has been removed, and the emails have
              stopped. Nothing further is needed from you.
            </p>
            <Link to="/" style={link}>Go to Taktline</Link>
          </>
        )}

        {state === 'ready' && info && (
          <>
            <h1 style={h1}>Delete {info.companyName}?</h1>
            <p style={body}>
              This stops the trial emails and removes the account. It cannot be undone.
            </p>
            <ul style={{
              margin: `${size.sp4} 0`, padding: `${size.sp3} ${size.sp5}`,
              background: color.bgCard, borderRadius: size.radius,
              fontSize: 13.5, color: color.textSecondary, lineHeight: 1.9,
            }}>
              <li>{info.stations} station{info.stations === 1 ? '' : 's'} and every route between them</li>
              <li>{info.lots} lot{info.lots === 1 ? '' : 's'} on the floor, with their history</li>
              <li>Every work session, statistic and floor plan</li>
              <li>Any share links you have posted publicly</li>
            </ul>
            <div style={{ display: 'flex', gap: size.sp3, flexWrap: 'wrap' }}>
              <button onClick={stop} style={danger}>Delete the account</button>
              <Link to="/settings?tab=billing" style={primary}>Keep it — see plans</Link>
            </div>
            <p style={{ ...body, fontSize: 12, color: color.textDim }}>
              Changed your mind about the emails only? Choosing a plan stops them too.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

const h1 = {
  fontSize: 24, fontWeight: 600, color: color.textPrimary,
  margin: `${size.sp5} 0 0`, lineHeight: 1.3,
} as const

const body = {
  fontSize: 14, lineHeight: 1.65, color: color.textSecondary,
  margin: `${size.sp3} 0 0`,
} as const

const link = {
  display: 'inline-block', marginTop: size.sp5, color: color.blueBright, fontSize: 14,
} as const

const primary = {
  background: color.bluePrimary, color: '#fff', textDecoration: 'none',
  borderRadius: size.radius, padding: '10px 20px', fontSize: 14, fontWeight: 600,
} as const

const danger = {
  background: 'none', border: `1px solid ${color.statusFault}`,
  color: color.statusFault, borderRadius: size.radius, padding: '10px 20px',
  fontSize: 14, cursor: 'pointer', fontFamily: 'inherit',
} as const
