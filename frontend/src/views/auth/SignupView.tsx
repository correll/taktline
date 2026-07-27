import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { track } from '../../analytics'
import { authApi } from '../../api/auth.api'
import { AuthCard, AuthFooter, Field, FormError, FormInfo, PrimaryButton, linkStyle } from './authUi'
import { useAuthStore } from '../../store/auth.store'
import { useStationsStore } from '../../store'
import { color, size } from '../../theme/tokens'

export default function SignupView() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [devLink, setDevLink] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Someone arriving from the sandbox is still signed in as it, so the browser
  // already proves which line is theirs — no code to copy across.
  const hasSandbox   = useAuthStore((s) => s.user?.isSandbox === true)
  const sandboxName  = useAuthStore((s) => s.companies[0]?.name ?? 'Sandbox factory')
  const stationCount = useStationsStore((s) => Object.keys(s.stations).length)
  const markAnon     = useAuthStore((s) => s.markAnon)
  const [adopt, setAdopt] = useState(true)
  const [companyName, setCompanyName] = useState('')
  const [adoptedOnSubmit, setAdoptedOnSubmit] = useState(false)
  // This page lives outside the app shell, so the stations were never fetched —
  // load them once to say concretely how much is about to move.
  const fetchStations = useStationsStore((s) => s.fetchAll)
  useEffect(() => { if (hasSandbox) fetchStations() }, [hasSandbox, fetchStations])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (password.length < 10) { setError('Password must be at least 10 characters.'); return }
    setBusy(true)
    try {
      const keep = hasSandbox && adopt
      const res = await authApi.signup(email, password, name || undefined,
        keep ? { adoptSandbox: true, companyName: companyName.trim() || undefined } : undefined)
      track('signup_completed', { adopted_sandbox: keep })
      // The sandbox account is gone once its line has been handed over, so the
      // cookie in this browser is dead — don't leave a stale session on screen.
      setAdoptedOnSubmit(keep)
      if (keep) markAnon()
      setDevLink(res.devLink ?? null)
      setDone(true)
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <AuthCard title="Check your email"
                subtitle={adoptedOnSubmit
                  ? `Your line is saved. We sent a verification link to ${email} — click it, sign in, and everything you built is waiting.`
                  : `We sent a verification link to ${email}. Click it to activate your account, then sign in.`}>
        {devLink && (
          <FormInfo>
            Dev link: <a href={devLink} style={linkStyle}>{devLink}</a>
          </FormInfo>
        )}
        <AuthFooter><Link to="/login" style={linkStyle}>Back to sign in</Link></AuthFooter>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Create your account"
              subtitle={hasSandbox && adopt
                ? 'Sign up and the line you just built comes with you.'
                : 'Sign up, then create a company to get started.'}>
      <form onSubmit={submit}>
        <Field label="Name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
        <Field label="Email" type="email" value={email} autoComplete="email"
               onChange={(e) => setEmail(e.target.value)} required />
        <Field label="Password (min 10 characters)" type="password" value={password} autoComplete="new-password"
               onChange={(e) => setPassword(e.target.value)} required />
        {hasSandbox && (
          <div style={{
            margin: `${size.sp4} 0`, padding: size.sp4,
            background: color.blueSubtle, border: `1px solid ${color.borderActive}55`,
            borderRadius: size.radiusMd,
          }}>
            <label style={{ display: 'flex', gap: size.sp3, alignItems: 'flex-start', cursor: 'pointer' }}>
              <input type="checkbox" checked={adopt} onChange={(e) => setAdopt(e.target.checked)}
                     style={{ marginTop: 3, accentColor: color.bluePrimary, width: 15, height: 15 }} />
              <span>
                <span style={{ fontSize: 14, color: color.textPrimary }}>
                  Keep the line I built in the sandbox
                </span>
                <span style={{ display: 'block', fontSize: 12.5, color: color.textSecondary, marginTop: 2 }}>
                  {stationCount > 0
                    ? `${stationCount} location${stationCount !== 1 ? 's' : ''} and everything on the board moves to this account.`
                    : 'Everything on the board moves to this account.'}
                  {' '}Leave it unticked to start clean.
                </span>
              </span>
            </label>
            {adopt && (
              <div style={{ marginTop: size.sp3 }}>
                <Field label="Company name" type="text" value={companyName}
                       placeholder={sandboxName}
                       onChange={(e) => setCompanyName(e.target.value)} />
              </div>
            )}
          </div>
        )}
        <FormError>{error}</FormError>
        <PrimaryButton type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</PrimaryButton>
      </form>
      <AuthFooter>Already have an account? <Link to="/login" style={linkStyle}>Sign in</Link></AuthFooter>
    </AuthCard>
  )
}
