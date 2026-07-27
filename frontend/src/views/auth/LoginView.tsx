import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../store/auth.store'
import { AuthCard, AuthFooter, Field, FormError, PrimaryButton, linkStyle } from './authUi'

export default function LoginView() {
  const login = useAuthStore((s) => s.login)
  const status = useAuthStore((s) => s.status)
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (status === 'authed') navigate('/', { replace: true }) }, [status, navigate])

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
