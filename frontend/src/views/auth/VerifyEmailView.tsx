import React, { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { authApi } from '../../api/auth.api'
import { AuthCard, AuthFooter, linkStyle } from './authUi'

export default function VerifyEmailView() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const [state, setState] = useState<'working' | 'ok' | 'fail'>('working')

  useEffect(() => {
    if (!token) { setState('fail'); return }
    authApi.verifyEmail(token).then(() => setState('ok')).catch(() => setState('fail'))
  }, [token])

  const title =
    state === 'working' ? 'Verifying…'
      : state === 'ok' ? 'Email verified'
        : 'Verification failed'
  const subtitle =
    state === 'working' ? 'One moment.'
      : state === 'ok' ? 'Your email is confirmed. You can now sign in.'
        : 'This link is invalid or has expired. Request a new one from the sign-in page.'

  return (
    <AuthCard title={title} subtitle={subtitle}>
      {state !== 'working' && (
        <AuthFooter><Link to="/login" style={linkStyle}>Go to sign in</Link></AuthFooter>
      )}
    </AuthCard>
  )
}
