import React, { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { authApi } from '../../api/auth.api'
import { AuthCard, AuthFooter, Field, FormError, PrimaryButton, linkStyle } from './authUi'

export default function ResetPasswordView() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!token) { setError('Missing or invalid reset token.'); return }
    if (password.length < 10) { setError('Password must be at least 10 characters.'); return }
    setBusy(true)
    try {
      await authApi.resetPassword(token, password)
      setDone(true)
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <AuthCard title="Password updated" subtitle="You can now sign in with your new password.">
        <AuthFooter><Link to="/login" style={linkStyle}>Go to sign in</Link></AuthFooter>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Choose a new password" subtitle="Enter a new password for your account.">
      <form onSubmit={submit}>
        <Field label="New password (min 10 characters)" type="password" value={password} autoComplete="new-password"
               onChange={(e) => setPassword(e.target.value)} required />
        <FormError>{error}</FormError>
        <PrimaryButton type="submit" disabled={busy}>{busy ? 'Updating…' : 'Update password'}</PrimaryButton>
      </form>
      <AuthFooter><Link to="/login" style={linkStyle}>Back to sign in</Link></AuthFooter>
    </AuthCard>
  )
}
