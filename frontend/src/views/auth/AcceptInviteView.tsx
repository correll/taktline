import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { invitesApi, type InvitePreview } from '../../api/members.api'
import { browserLanguage, isLang } from '../../i18n/languages'
import { useAuthStore } from '../../store/auth.store'
import { AuthCard, AuthFooter, Field, FormError, LanguageSelect, PrimaryButton, linkStyle } from './authUi'

export default function AcceptInviteView() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const navigate = useNavigate()
  const status = useAuthStore((s) => s.status)
  const refresh = useAuthStore((s) => s.refresh)

  const [preview, setPreview] = useState<InvitePreview | null>(null)
  const [password, setPassword] = useState('')
  const [language, setLanguage] = useState<string>('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!token) { setPreview({ valid: false, reason: 'missing' }); return }
    invitesApi.preview(token).then((p) => {
      setPreview(p)
      // Default to the browser's language when the company offers it,
      // otherwise the first language the company runs in.
      const offered = p.supportedLanguages ?? []
      const guess = browserLanguage()
      setLanguage(offered.includes(guess) ? guess : offered[0] ?? 'en')
    }).catch(() => setPreview({ valid: false, reason: 'error' }))
  }, [token])

  async function acceptExisting() {
    setError(''); setBusy(true)
    try {
      await invitesApi.accept(token)
      await refresh()
      navigate('/', { replace: true })
    } catch (err) { setError(String(err)) } finally { setBusy(false) }
  }

  async function acceptNew(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (password.length < 10) { setError('Password must be at least 10 characters.'); return }
    setBusy(true)
    try {
      await invitesApi.acceptSignup(token, password, undefined,
                                    isLang(language) ? language : undefined)
      await refresh()
      navigate('/', { replace: true })
    } catch (err) { setError(String(err)) } finally { setBusy(false) }
  }

  if (!preview) return <AuthCard title="Loading invitation…" />

  if (!preview.valid) {
    return (
      <AuthCard title="Invitation unavailable"
                subtitle="This invitation is invalid, expired, or has already been used.">
        <AuthFooter><Link to="/login" style={linkStyle}>Go to sign in</Link></AuthFooter>
      </AuthCard>
    )
  }

  const sub = <>You’ve been invited to join <b>{preview.companyName}</b> as a <b>{preview.role}</b>.</>

  // Logged-in user → one-click accept.
  if (status === 'authed') {
    return (
      <AuthCard title="Accept invitation" subtitle={sub}>
        <FormError>{error}</FormError>
        <PrimaryButton onClick={acceptExisting} disabled={busy}>
          {busy ? 'Joining…' : `Join ${preview.companyName}`}
        </PrimaryButton>
      </AuthCard>
    )
  }

  // New user → set a password to create the account and join.
  return (
    <AuthCard title="Accept invitation" subtitle={<>{sub}<br />Set a password for <b>{preview.email}</b> to continue.</>}>
      <form onSubmit={acceptNew}>
        <Field label="Password (min 10 characters)" type="password" value={password} autoComplete="new-password"
               onChange={(e) => setPassword(e.target.value)} required />
        {(preview.supportedLanguages?.length ?? 0) > 1 && (
          <LanguageSelect value={language} onChange={setLanguage}
                          codes={preview.supportedLanguages!} />
        )}
        <FormError>{error}</FormError>
        <PrimaryButton type="submit" disabled={busy}>{busy ? 'Joining…' : 'Create account & join'}</PrimaryButton>
      </form>
      <AuthFooter>Already registered? <Link to="/login" style={linkStyle}>Sign in first</Link></AuthFooter>
    </AuthCard>
  )
}
