import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi } from '../../api/auth.api'
import { AuthCard, AuthFooter, Field, FormError, FormInfo, PrimaryButton, linkStyle } from './authUi'

export default function ForgotPasswordView() {
  const [email, setEmail] = useState('')
  const [done, setDone] = useState(false)
  const [devLink, setDevLink] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(''); setBusy(true)
    try {
      const res = await authApi.forgotPassword(email)
      setDevLink(res.devLink ?? null)
      setDone(true)
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard title="Reset password"
              subtitle={done ? `If an account exists for ${email}, a reset link is on its way.` : 'Enter your email and we’ll send a reset link.'}>
      {done ? (
        <>
          {devLink && <FormInfo>Dev link: <a href={devLink} style={linkStyle}>{devLink}</a></FormInfo>}
          <AuthFooter><Link to="/login" style={linkStyle}>Back to sign in</Link></AuthFooter>
        </>
      ) : (
        <form onSubmit={submit}>
          <Field label="Email" type="email" value={email} autoComplete="email"
                 onChange={(e) => setEmail(e.target.value)} required />
          <FormError>{error}</FormError>
          <PrimaryButton type="submit" disabled={busy}>{busy ? 'Sending…' : 'Send reset link'}</PrimaryButton>
          <AuthFooter><Link to="/login" style={linkStyle}>Back to sign in</Link></AuthFooter>
        </form>
      )}
    </AuthCard>
  )
}
