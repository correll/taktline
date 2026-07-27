import React, { useEffect, useState } from 'react'
import { membersApi, type Member, type Invitation } from '../../api/members.api'
import { type Role, ROLE_LABEL } from '../../api/auth.api'
import { useAuthStore } from '../../store/auth.store'
import { color, font, size } from '../../theme/tokens'

const ROLE_HINT: Record<Role, string> = {
  user:        'Operator: run work sessions, merge, advance lots, set status. Read-only lot board.',
  admin:       'Everything a user can do, plus create lots, pull precursors, and release/cancel orders.',
  super_admin: 'Full access: process & floor config, member management, and structural lot ops.',
}

export default function MembersTab() {
  const companyId = useAuthStore((s) => s.activeCompanyId)
  const currentUserId = useAuthStore((s) => s.user?.id)
  const refresh = useAuthStore((s) => s.refresh)

  const [members, setMembers] = useState<Member[]>([])
  const [invites, setInvites] = useState<Invitation[]>([])
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('user')
  const [msg, setMsg] = useState<string>('')
  const [devLink, setDevLink] = useState<string | null>(null)
  const [err, setErr] = useState('')

  async function load() {
    if (!companyId) return
    try {
      setMembers(await membersApi.list(companyId))
      setInvites(await membersApi.listInvitations(companyId))
    } catch (e) { setErr(String(e)) }
  }

  useEffect(() => { load() }, [companyId])

  async function invite(e: React.FormEvent) {
    e.preventDefault()
    if (!companyId) return
    setErr(''); setMsg(''); setDevLink(null)
    try {
      const inv = await membersApi.invite(companyId, email, role)
      setMsg(`Invitation sent to ${email}.`)
      setDevLink(inv.devLink ?? null)
      setEmail('')
      await load()
    } catch (e) { setErr(String(e)) }
  }

  async function changeRole(userId: string, newRole: Role) {
    if (!companyId) return
    setErr('')
    try {
      await membersApi.changeRole(companyId, userId, newRole)
      await load()
      if (userId === currentUserId) await refresh()  // my own role changed
    } catch (e) { setErr(String(e)) }
  }

  async function remove(userId: string) {
    if (!companyId) return
    setErr('')
    try {
      await membersApi.remove(companyId, userId)
      await load()
      if (userId === currentUserId) await refresh()
    } catch (e) { setErr(String(e)) }
  }

  async function revoke(id: string) {
    if (!companyId) return
    try { await membersApi.revokeInvitation(companyId, id); await load() }
    catch (e) { setErr(String(e)) }
  }

  const cellStyle: React.CSSProperties = { padding: `${size.sp2} ${size.sp3}`, fontSize: 13, color: color.textPrimary }
  const headStyle: React.CSSProperties = { ...cellStyle, color: color.textSecondary, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', textAlign: 'left' }
  const btn = (bg: string): React.CSSProperties => ({
    background: 'transparent', border: `1px solid ${color.border}`, color: bg, borderRadius: size.radius,
    padding: `${size.sp1} ${size.sp2}`, fontSize: 12, cursor: 'pointer', marginLeft: size.sp1,
  })

  return (
    <div style={{ padding: size.sp6, overflow: 'auto', height: '100%', boxSizing: 'border-box' }}>
      <h2 style={{ color: color.textPrimary, fontSize: 16, marginTop: 0, fontFamily: font.sans }}>Team members</h2>

      {/* Invite form */}
      <form onSubmit={invite} style={{ display: 'flex', gap: size.sp2, alignItems: 'center', marginBottom: size.sp5, flexWrap: 'wrap' }}>
        <input
          type="email" placeholder="teammate@company.com" value={email} required
          onChange={(e) => setEmail(e.target.value)}
          style={{ flex: 1, minWidth: 240, padding: `${size.sp2} ${size.sp3}`, background: color.bgCard, border: `1px solid ${color.border}`, borderRadius: size.radius, color: color.textPrimary, fontSize: 13, outline: 'none' }}
        />
        <select value={role} onChange={(e) => setRole(e.target.value as Role)}
                title={ROLE_HINT[role]}
                style={{ padding: `${size.sp2} ${size.sp3}`, background: color.bgCard, border: `1px solid ${color.border}`, borderRadius: size.radius, color: color.textPrimary, fontSize: 13 }}>
          <option value="user">{ROLE_LABEL.user}</option>
          <option value="admin">{ROLE_LABEL.admin}</option>
          <option value="super_admin">{ROLE_LABEL.super_admin}</option>
        </select>
        <button type="submit" style={{ padding: `${size.sp2} ${size.sp4}`, background: color.bluePrimary, color: color.white, border: 'none', borderRadius: size.radius, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
          Invite
        </button>
      </form>
      {msg && <div style={{ color: color.statusRunning, fontSize: 13, marginBottom: size.sp3 }}>{msg}</div>}
      {devLink && <div style={{ color: color.textSecondary, fontSize: 12, marginBottom: size.sp3, wordBreak: 'break-all' }}>Dev invite link: <a href={devLink} style={{ color: color.blueBright }}>{devLink}</a></div>}
      {err && <div style={{ color: color.statusFault, fontSize: 13, marginBottom: size.sp3 }}>{err}</div>}

      {/* Members table */}
      <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: size.sp8 }}>
        <thead><tr style={{ borderBottom: `1px solid ${color.border}` }}>
          <th style={headStyle}>Email</th><th style={headStyle}>Name</th><th style={headStyle}>Role</th><th style={headStyle}></th>
        </tr></thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.userId} style={{ borderBottom: `1px solid ${color.border}` }}>
              <td style={cellStyle}>{m.email}{m.userId === currentUserId && <span style={{ color: color.textDim }}> (you)</span>}</td>
              <td style={cellStyle}>{m.name ?? '—'}</td>
              <td style={cellStyle}>
                <span style={{ color: m.role === 'super_admin' ? color.blueBright : m.role === 'admin' ? color.textPrimary : color.textSecondary }}>
                  {ROLE_LABEL[m.role as Role] ?? m.role}
                </span>
              </td>
              <td style={{ ...cellStyle, textAlign: 'right' }}>
                <select
                  value={m.role}
                  title={ROLE_HINT[m.role as Role]}
                  onChange={(e) => changeRole(m.userId, e.target.value as Role)}
                  style={{ padding: '3px 6px', background: color.bgCard, border: `1px solid ${color.border}`, borderRadius: size.radius, color: color.textPrimary, fontSize: 12, marginRight: size.sp2 }}
                >
                  <option value="user">{ROLE_LABEL.user}</option>
                  <option value="admin">{ROLE_LABEL.admin}</option>
                  <option value="super_admin">{ROLE_LABEL.super_admin}</option>
                </select>
                <button style={btn(color.statusFault)} onClick={() => remove(m.userId)}>Remove</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Pending invitations */}
      <h3 style={{ color: color.textPrimary, fontSize: 14, fontFamily: font.sans }}>Pending invitations</h3>
      {invites.length === 0
        ? <div style={{ color: color.textDim, fontSize: 13 }}>No pending invitations.</div>
        : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: `1px solid ${color.border}` }}>
              <th style={headStyle}>Email</th><th style={headStyle}>Role</th><th style={headStyle}>Expires</th><th style={headStyle}></th>
            </tr></thead>
            <tbody>
              {invites.map((inv) => (
                <tr key={inv.id} style={{ borderBottom: `1px solid ${color.border}` }}>
                  <td style={cellStyle}>{inv.email}</td>
                  <td style={cellStyle}>{ROLE_LABEL[inv.role as Role] ?? inv.role}</td>
                  <td style={{ ...cellStyle, color: color.textSecondary }}>{new Date(inv.expiresAt).toLocaleDateString()}</td>
                  <td style={{ ...cellStyle, textAlign: 'right' }}>
                    <button style={btn(color.statusFault)} onClick={() => revoke(inv.id)}>Revoke</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  )
}
