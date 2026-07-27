import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { companiesApi } from '../../api/companies.api'
import { useAuthStore } from '../../store/auth.store'
import { AuthCard, Field, FormError, PrimaryButton } from '../auth/authUi'
import { color, size } from '../../theme/tokens'

export default function CreateCompanyView() {
  const navigate = useNavigate()
  const refresh = useAuthStore((s) => s.refresh)
  const setActiveCompany = useAuthStore((s) => s.setActiveCompany)
  const companies = useAuthStore((s) => s.companies)
  const logout = useAuthStore((s) => s.logout)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(''); setBusy(true)
    try {
      const company = await companiesApi.create(name)
      await refresh()
      setActiveCompany(company.id)
      navigate('/', { replace: true })
    } catch (err) { setError(String(err)) } finally { setBusy(false) }
  }

  return (
    <AuthCard title="Create a company"
              subtitle="A company is your manufacturing workspace. You’ll be its first admin and can invite others.">
      <form onSubmit={submit}>
        <Field label="Company name" type="text" value={name} onChange={(e) => setName(e.target.value)} required />
        <FormError>{error}</FormError>
        <PrimaryButton type="submit" disabled={busy || !name.trim()}>
          {busy ? 'Creating…' : 'Create company'}
        </PrimaryButton>
      </form>
      <div style={{ marginTop: size.sp5, textAlign: 'center' }}>
        <button onClick={() => logout()}
                style={{ background: 'none', border: 'none', color: color.textSecondary, cursor: 'pointer', fontSize: 13 }}>
          {companies.length > 0 ? 'Back to workspace' : 'Sign out'}
        </button>
      </div>
    </AuthCard>
  )
}
