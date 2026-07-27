import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth.store'
import { color, font, size } from '../theme/tokens'

export function CompanySwitcher() {
  const companies = useAuthStore((s) => s.companies)
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)
  const setActiveCompany = useAuthStore((s) => s.setActiveCompany)
  const navigate = useNavigate()

  if (companies.length === 0) return null

  return (
    <select
      value={activeCompanyId ?? ''}
      onChange={(e) => {
        if (e.target.value === '__new__') navigate('/create-company')
        else setActiveCompany(e.target.value)
      }}
      style={{
        background: color.bgCard, color: color.textPrimary,
        border: `1px solid ${color.border}`, borderRadius: size.radius,
        padding: `${size.sp1} ${size.sp2}`, fontSize: 12, fontFamily: font.sans,
        maxWidth: 220, cursor: 'pointer', outline: 'none',
      }}
    >
      {companies.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name} · {c.impersonated ? 'support' : c.role}
        </option>
      ))}
      <option value="__new__">+ New company…</option>
    </select>
  )
}
