import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../store/auth.store'
import { AuthCard, AuthFooter, Field, FormError, PrimaryButton, linkStyle } from './authUi'

export default function LoginView() {
  const login = useAuthStore((s) => s.login)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [ready, setReady] = useState(false)

  /**
   * Arriving here with a session already open ends it, rather than bouncing
   * back to where you came from.
   *
   * It used to redirect to "/" the moment it saw `status === 'authed'`, so the
   * form appeared for a frame and vanished. The common way to hit that is a
   * **sandbox** session: it lasts a week by design and its owner still gets the
   * marketing site, so "Sign in" was unusable for exactly the visitor most
   * likely to be converting from a trial to a real account. In a private window
   * it worked, which made it look like a browser quirk rather than a session.
   *
   * Opening the sign-in page is an unambiguous statement of intent — you want
   * to sign in, quite possibly as somebody else — so the old session goes.
   * Once, on arrival: keyed to mount rather than to `status`, or it would log
   * you straight back out the instant the login below succeeded.
   */
  useEffect(() => {
    let cancelled = false
    void (async () => {
      if (useAuthStore.getState().status === 'authed') {
        try { await logout() } catch { /* a dead session is already gone */ }
      }
      if (!cancelled) setReady(true)
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(''); setBusy(true)
    try {
      await login(email, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!ready) {
    return <AuthCard title="Sign in" subtitle="Closing your previous session…"><div /></AuthCard>
  }

  return (
    <AuthCard title="Sign in" subtitle="Access your Taktline workspace.">
      <form onSubmit={submit}>
        <Field label="Email" type="email" value={email} autoComplete="email"
               onChange={(e) => setEmail(e.target.value)} required />
        <Field label="Password" type="password" value={password} autoComplete="current-password"
               onChange={(e) => setPassword(e.target.value)} required />
        <FormError>{error}</FormError>
        <PrimaryButton type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</PrimaryButton>
      </form>
      <AuthFooter>
        <Link to="/forgot-password" style={linkStyle}>Forgot password?</Link>
        <div style={{ marginTop: 8 }}>
          No account? <Link to="/signup" style={linkStyle}>Create one</Link>
        </div>
      </AuthFooter>
    </AuthCard>
  )
}
