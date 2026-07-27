import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi } from '../../api/auth.api'
import { AuthCard, AuthFooter, Field, FormError, FormInfo, PrimaryButton, linkStyle } from './authUi'

export default function SignupView() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [devLink, setDevLink] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (password.length < 10) { setError('Password must be at least 10 characters.'); return }
    setBusy(true)
    try {
      const res = await authApi.signup(email, password, name || undefined)
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
                subtitle={`We sent a verification link to ${email}. Click it to activate your account, then sign in.`}>
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
    <AuthCard title="Create your account" subtitle="Sign up, then create a company to get started.">
      <form onSubmit={submit}>
        <Field label="Name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
        <Field label="Email" type="email" value={email} autoComplete="email"
               onChange={(e) => setEmail(e.target.value)} required />
        <Field label="Password (min 10 characters)" type="password" value={password} autoComplete="new-password"
               onChange={(e) => setPassword(e.target.value)} required />
        <FormError>{error}</FormError>
        <PrimaryButton type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</PrimaryButton>
      </form>
      <AuthFooter>Already have an account? <Link to="/login" style={linkStyle}>Sign in</Link></AuthFooter>
    </AuthCard>
  )
}
