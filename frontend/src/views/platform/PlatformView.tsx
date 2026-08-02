import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, NavLink } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { money } from '../../api/billing.api'
import { color, font, size, shadow } from '../../theme/tokens'
import { useSortable } from './useSortable'
import { useAuthStore } from '../../store/auth.store'
import {
  platformApi, type AuditEntry, type PlatformCompany, type PlatformStatus, type PlatformUser,
} from '../../api/platform.api'

// Customer-service dashboard. Server-side checks are authoritative — this view
// merely renders what /platform/* returns (404s for anyone else).

export default function PlatformView() {
  const user = useAuthStore((s) => s.user)
  const isOwner = user?.platformRole === 'owner'

  const [status, setStatus]       = useState<PlatformStatus | null>(null)
  const [users, setUsers]         = useState<PlatformUser[]>([])
  const [companies, setCompanies] = useState<PlatformCompany[]>([])
  const [audit, setAudit]         = useState<AuditEntry[]>([])
  const [error, setError]         = useState<string | null>(null)
  const [tab, setTab]             = useState<'companies' | 'users' | 'audit'>('companies')

  const reload = useCallback(() => {
    platformApi.status().then(setStatus).catch((e) => setError(String(e)))
    platformApi.users().then(setUsers).catch(() => {})
    platformApi.companies().then(setCompanies).catch(() => {})
    platformApi.audit().then(setAudit).catch(() => {})
  }, [])

  useEffect(() => {
    reload()
    const t = setInterval(() => { platformApi.status().then(setStatus).catch(() => {}) }, 30_000)
    return () => clearInterval(t)
  }, [reload])

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: size.sp6, background: color.bgDeep }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: size.sp6 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp3 }}>
          <h2 style={{ margin: 0, fontSize: 18, color: color.textPrimary }}>Platform</h2>
          <span style={{ fontSize: 11, fontFamily: font.mono, color: color.blueBright, letterSpacing: '0.08em' }}>
            {isOwner ? 'OWNER' : 'SUPPORT'}
          </span>
          {error && <span style={{ fontSize: 12, color: color.statusFault }}>{error}</span>}
        </div>

        {status && <StatusSection status={status} />}

        {/* Three long tables stacked made a page nobody scrolled to the end of,
            and the audit trail — the one you reach for when something has gone
            wrong — was furthest down. Status stays above the tabs: it is the
            "is anything on fire" glance and belongs on every view. */}
        <nav style={{ display: 'flex', gap: size.sp1, borderBottom: `1px solid ${color.border}` }}>
          {([
            ['companies', `Companies (${companies.length})`],
            ['users', `Users (${users.length})`],
            ['audit', 'Audit trail'],
          ] as const).map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
                    aria-current={tab === id ? 'page' : undefined}
                    style={{
                      background: 'transparent', border: 'none', cursor: 'pointer',
                      padding: `${size.sp2} ${size.sp4}`, fontSize: 13,
                      color: tab === id ? color.textPrimary : color.textSecondary,
                      fontWeight: tab === id ? 600 : 400,
                      borderBottom: `2px solid ${tab === id ? color.bluePrimary : 'transparent'}`,
                      marginBottom: -1,
                    }}>
              {label}
            </button>
          ))}
        </nav>

        {tab === 'companies' && <CompaniesSection companies={companies} onChanged={reload} />}
        {tab === 'users' && (
          <UsersSection users={users} isOwner={isOwner} selfId={user?.id} onChanged={reload} />
        )}
        {tab === 'audit' && <AuditSection audit={audit} />}

        {/* Crashes that reached a customer's screen. Bottom of the page on
            purpose: it is the thing you go looking for after a support
            conversation starts, not something to watch. */}
        <NavLink to="/platform/client-errors" style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: size.sp4, textDecoration: 'none',
          background: color.bgCard, border: `1px solid ${color.border}`,
          borderRadius: size.radiusMd, padding: `${size.sp4} ${size.sp5}`,
        }}>
          <span>
            <span style={{ color: color.textPrimary, fontSize: 14, fontWeight: 600 }}>
              Client errors
            </span>
            <span style={{ display: 'block', color: color.textDim, fontSize: 11.5, marginTop: 2 }}>
              Crashes reported from customers&rsquo; browsers, with a copy-for-support button.
            </span>
          </span>
          <span style={{ color: color.blueBright, fontSize: 13, whiteSpace: 'nowrap' }}>View →</span>
        </NavLink>
      </div>
    </div>
  )
}

// ─── Status ───────────────────────────────────────────────────────────────────

function fmtUptime(s: number): string {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`
}

// 1234 → "1.2k", 23 456 789 → "23.5M" — one decimal below 100 of a unit,
// whole numbers above; exact values stay available via tooltips.
export function fmtCompact(n: number): string {
  const abs = Math.abs(n)
  if (abs < 1000) return String(n)
  const units: [number, string][] = [[1e9, 'B'], [1e6, 'M'], [1e3, 'k']]
  for (const [div, suffix] of units) {
    // 0.9995: values that would round up to "1000k" promote to "1M" instead
    if (abs >= div * 0.9995) {
      const v = n / div
      const s = Math.abs(v) < 100 ? v.toFixed(1).replace(/\.0$/, '') : String(Math.round(v))
      return s + suffix
    }
  }
  return String(n)
}

/** Plan plus its effective state. The state matters more than the plan: a
 *  Professional account that is locked is worth nothing and needs a call. */
function PlanCell({ company }: { company: PlatformCompany }) {
  const tone = company.planState === 'locked' ? color.statusFault
             : company.planState === 'read_only' ? color.statusWarning
             : color.textSecondary
  return (
    <span style={{ color: tone, whiteSpace: 'nowrap' }}>
      {company.plan ?? '—'}
      {company.planState && company.planState !== 'ok' && (
        <span style={{ fontSize: 10.5, marginLeft: 5 }}>
          ({company.planState.replace('_', '-')})
        </span>
      )}
    </span>
  )
}

function StatusSection({ status }: { status: PlatformStatus }) {
  const tiles: [string, string | number][] = [
    // Money first. `fmtCompact` has no currency notion, so these are passed as
    // pre-formatted strings and shown whole.
    ['MRR',                money(status.mrrCents)],
    ['ARR',                money(status.arrCents)],
    ['Paying',             status.payingCompanies],
    ['On trial',           status.trialingCompanies],
    ['Past due or paused', status.atRiskCompanies],
    ['Live connections',   status.wsConnections],
    ['Signed-in sessions', status.authSessionsActive],
    ['Open work sessions', status.workSessionsOpen],
    ['Card events · 24 h', status.cardEvents24h],
    ['Users',              status.usersTotal],
    ['Companies',          status.companiesTotal],
    ['Active support grants', status.supportGrantsActive],
    ['Uptime',             fmtUptime(status.uptimeSeconds)],
  ]
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: size.sp3 }}>
      <TrafficTile perMinute={status.requestsPerMinute} total={status.requestsTotal} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: size.sp3 }}>
        {tiles.map(([label, value]) => (
          <div key={label} style={tileStyle} title={typeof value === 'number' ? value.toLocaleString() : undefined}>
            <div style={{ fontSize: 11, color: color.textSecondary }}>{label}</div>
            <div style={{ fontSize: 22, fontWeight: 500, color: color.textPrimary, fontFamily: font.mono }}>
              {typeof value === 'number' ? fmtCompact(value) : value}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

// Requests-per-minute sparkline: single series (title names it — no legend),
// 2px coral line + soft area, ink text, hover readout on the nearest minute.
function TrafficTile({ perMinute, total }: {
  perMinute: { minute: number; requests: number }[]; total: number
}) {
  const [hover, setHover] = useState<number | null>(null)   // index into perMinute
  const svgRef = useRef<SVGSVGElement>(null)

  const W = 600, H = 56, PAD = 2
  const max = Math.max(1, ...perMinute.map((p) => p.requests))
  const pts = useMemo(() => perMinute.map((p, i) => ({
    x: PAD + (i / Math.max(1, perMinute.length - 1)) * (W - PAD * 2),
    y: H - PAD - (p.requests / max) * (H - PAD * 2),
  })), [perMinute, max])

  const linePath = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const areaPath = `${linePath} L${W - PAD},${H - PAD} L${PAD},${H - PAD} Z`

  const current = perMinute[perMinute.length - 1]?.requests ?? 0
  const shown = hover != null ? perMinute[hover] : null
  const minuteLabel = (m: number) => {
    const d = new Date(m * 60_000)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }

  const onMove = (e: React.MouseEvent) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect || perMinute.length === 0) return
    const frac = (e.clientX - rect.left) / rect.width
    setHover(Math.max(0, Math.min(perMinute.length - 1, Math.round(frac * (perMinute.length - 1)))))
  }

  return (
    <div style={{ ...tileStyle, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp3 }}>
        <span style={{ fontSize: 11, color: color.textSecondary }}>Requests per minute · last hour</span>
        <span style={{ fontSize: 20, fontWeight: 500, fontFamily: font.mono, color: color.textPrimary }}
              title={(shown ? shown.requests : current).toLocaleString()}>
          {fmtCompact(shown ? shown.requests : current)}
        </span>
        <span style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono }} title={total.toLocaleString()}>
          {shown ? `at ${minuteLabel(shown.minute)}` : 'now'} · {fmtCompact(total)} since start
        </span>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: H, display: 'block', cursor: 'crosshair' }}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <path d={areaPath} fill={color.bluePrimary} opacity={0.12} />
        <path d={linePath} fill="none" stroke={color.bluePrimary} strokeWidth={2}
              vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {hover != null && pts[hover] && (
          <>
            <line x1={pts[hover].x} y1={PAD} x2={pts[hover].x} y2={H - PAD}
                  stroke={color.textDim} strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.6} />
            <circle cx={pts[hover].x} cy={pts[hover].y} r={3.5} fill={color.bluePrimary}
                    stroke={color.bgCard} strokeWidth={2} />
          </>
        )}
      </svg>
    </div>
  )
}

// ─── Companies ────────────────────────────────────────────────────────────────

function CompaniesSection({ companies, onChanged }: {
  companies: PlatformCompany[]; onChanged: () => void
}) {
  const navigate = useNavigate()
  const refresh = useAuthStore((s) => s.refresh)
  const setActiveCompany = useAuthStore((s) => s.setActiveCompany)
  const [deleting, setDeleting] = useState<PlatformCompany | null>(null)
  const [confirmName, setConfirmName] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const impersonate = async (c: PlatformCompany) => {
    setBusy(c.id); setError(null)
    try {
      await platformApi.impersonate(c.id, 60)
      await refresh()                 // pulls the flagged membership into the switcher
      setActiveCompany(c.id)
      navigate('/map')
    } catch (e) { setError(String(e)) } finally { setBusy(null) }
  }

  const doDelete = async () => {
    if (!deleting) return
    setBusy(deleting.id); setError(null)
    try {
      await platformApi.deleteCompany(deleting.id, confirmName)
      setDeleting(null); setConfirmName('')
      onChanged()
    } catch (e) { setError(String(e)) } finally { setBusy(null) }
  }

  // Sorted on the underlying values, never the formatted text — "1.2k" must
  // not sort before "900".
  const sortable = useSortable(companies, [
    { label: 'Company',         value: (c) => c.name },
    { label: 'Active users',    value: (c) => c.activeUsers, descFirst: true },
    { label: 'Stations',        value: (c) => c.stations, descFirst: true },
    { label: 'Lots on floor',   value: (c) => c.cards, descFirst: true },
    { label: 'Devices',         value: (c) => c.devicesConnected, descFirst: true },
    { label: 'API req · month', value: (c) => c.apiRequestsMonth, descFirst: true },
    { label: 'WS msgs · month', value: (c) => c.wsMessagesMonth, descFirst: true },
    { label: 'Last activity',   value: (c) => c.lastActivityAt ?? null, descFirst: true },
    { label: 'Plan', value: (c: PlatformCompany) => c.plan ?? '' },
    { label: 'MRR', value: (c: PlatformCompany) => c.mrrCents, descFirst: true },
    { label: 'Renews', value: (c: PlatformCompany) => c.renewsAt ?? c.trialEndsAt ?? null },
    { label: '', sticky: true },
  ], 'Last activity')

  return (
    <section>
      <SectionTitle>Companies ({companies.length})</SectionTitle>
      {error && <div style={{ fontSize: 12, color: color.statusFault, marginBottom: 6 }}>{error}</div>}
      <div style={{ ...cardListStyle, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, minWidth: 900 }}>
          <thead>{sortable.header}</thead>
          <tbody>
            {sortable.rows.map((c) => (
              <tr key={c.id} style={{ borderTop: `1px solid ${color.border}` }}>
                <td style={{ ...tdStyle, color: color.textPrimary, fontWeight: 500 }}>{c.name}</td>
                <td style={tdStyle} title={`${c.activeUsers} signed in now of ${c.members} members`}>
                  {c.activeUsers} <span style={{ color: color.textDim }}>/ {c.members}</span>
                </td>
                <td style={tdStyle}>{c.stations}</td>
                <td style={tdStyle} title={c.cards.toLocaleString()}>{fmtCompact(c.cards)}</td>
                <td style={tdStyle} title="Live WebSocket connections">{c.devicesConnected}</td>
                <td style={tdStyle} title={c.apiRequestsMonth.toLocaleString()}>{fmtCompact(c.apiRequestsMonth)}</td>
                <td style={tdStyle} title={c.wsMessagesMonth.toLocaleString()}>{fmtCompact(c.wsMessagesMonth)}</td>
                <td style={tdStyle}>
                  {c.lastActivityAt ? formatDistanceToNow(new Date(withZ(c.lastActivityAt)), { addSuffix: true }) : '—'}
                </td>
                <td style={tdStyle}>
                  <PlanCell company={c} />
                </td>
                <td style={tdStyle}>{c.mrrCents ? money(c.mrrCents) : '—'}</td>
                <td style={tdStyle}>
                  {(c.renewsAt ?? c.trialEndsAt)
                    ? formatDistanceToNow(new Date(withZ((c.renewsAt ?? c.trialEndsAt)!)), { addSuffix: true })
                    : '—'}
                </td>
                {/* Pinned to the right edge. The table is 900px wide inside a
                    box that clips, so on any narrower window the actions sat
                    past the edge and had to be scrolled to — on a scrollbar
                    that is easy to miss. Padding did not help, because the
                    column was not merely tight, it was off-screen. Now the
                    data scrolls underneath and Impersonate/Delete stay put. */}
                <td style={{ ...tdStyle, textAlign: 'right', whiteSpace: 'nowrap',
                             position: 'sticky', right: 0, zIndex: 1,
                             background: color.bgCard,
                             borderLeft: `1px solid ${color.border}` }}>
                  <button style={smallBtn} disabled={busy === c.id} onClick={() => impersonate(c)}>
                    Impersonate
                  </button>
                  <button style={{ ...smallBtn, color: color.statusFault, marginLeft: 6 }}
                          onClick={() => { setDeleting(c); setConfirmName('') }}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {deleting && (
        <div style={backdropStyle} onClick={(e) => { if (e.target === e.currentTarget) setDeleting(null) }}>
          <div style={modalStyle}>
            <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>
              Delete company "{deleting.name}"?
            </div>
            <p style={{ fontSize: 12.5, color: color.textSecondary, margin: 0, lineHeight: 1.5 }}>
              This permanently removes the company and everything in it — {deleting.members} member{deleting.members !== 1 && 's'},
              {' '}{deleting.stations} stations, {deleting.cards} lots. Type the company's exact name to confirm.
            </p>
            <input
              value={confirmName} onChange={(e) => setConfirmName(e.target.value)}
              placeholder={deleting.name} autoFocus
              style={{ background: color.bgInput, border: `1px solid ${color.border}`, borderRadius: 4,
                       color: color.textPrimary, padding: '7px 10px', fontSize: 13, outline: 'none' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button style={smallBtn} onClick={() => setDeleting(null)}>Cancel</button>
              <button
                disabled={confirmName.trim() !== deleting.name || busy === deleting.id}
                onClick={doDelete}
                style={{ ...smallBtn,
                         background: confirmName.trim() === deleting.name ? color.statusFault : 'transparent',
                         color: confirmName.trim() === deleting.name ? '#fff' : color.textDisabled,
                         borderColor: color.statusFault }}>
                Delete permanently
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

// ─── Users ────────────────────────────────────────────────────────────────────

function UsersSection({ users, isOwner, selfId, onChanged }: {
  users: PlatformUser[]; isOwner: boolean; selfId?: string; onChanged: () => void
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const del = async (u: PlatformUser) => {
    setError(null)
    try { await platformApi.deleteUser(u.id); setConfirmId(null); onChanged() }
    catch (e) { setError(String(e)) }
  }
  const toggleSupport = async (u: PlatformUser) => {
    setError(null)
    try { await platformApi.setPlatformRole(u.id, u.platformRole === 'support' ? null : 'support'); onChanged() }
    catch (e) { setError(String(e)) }
  }

  const sortable = useSortable(users, [
    { label: 'User',      value: (u) => u.email },
    // By how many companies they belong to: the cell lists names, but "which
    // user is in the most companies" is the question this column answers.
    { label: 'Companies', value: (u) => u.companies.length, descFirst: true },
    { label: 'Last seen', value: (u) => u.lastSeenAt ?? null, descFirst: true },
    { label: 'Platform',  value: (u) => u.platformRole ?? null },
    { label: '' },
  ], 'Last seen')

  return (
    <section>
      <SectionTitle>Users ({users.length})</SectionTitle>
      {error && <div style={{ fontSize: 12, color: color.statusFault, marginBottom: 6 }}>{error}</div>}
      <div style={cardListStyle}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>{sortable.header}</thead>
          <tbody>
            {sortable.rows.map((u) => (
              <tr key={u.id} style={{ borderTop: `1px solid ${color.border}` }}>
                <td style={{ ...tdStyle, color: color.textPrimary }}>
                  {u.email}
                  {u.name && <span style={{ color: color.textDim }}> · {u.name}</span>}
                </td>
                <td style={tdStyle} title={u.companies.map((c) => `${c.companyName} (${c.role})`).join(', ')}>
                  {u.companies.map((c) => `${c.companyName} · ${c.role}`).join(', ') || '—'}
                </td>
                <td style={tdStyle}>
                  {u.lastSeenAt ? formatDistanceToNow(new Date(withZ(u.lastSeenAt)), { addSuffix: true }) : 'never'}
                </td>
                <td style={tdStyle}>
                  {u.platformRole && (
                    <span style={{ fontSize: 10, fontFamily: font.mono, letterSpacing: '0.06em',
                                   color: color.blueBright, border: `1px solid ${color.borderActive}55`,
                                   borderRadius: size.radiusFull, padding: '1px 7px' }}>
                      {u.platformRole}
                    </span>
                  )}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right', whiteSpace: 'nowrap' }}>
                  {isOwner && u.platformRole !== 'owner' && (
                    <button style={smallBtn} onClick={() => toggleSupport(u)}>
                      {u.platformRole === 'support' ? 'Revoke support' : 'Make support'}
                    </button>
                  )}
                  {u.platformRole !== 'owner' && u.id !== selfId && (
                    confirmId === u.id ? (
                      <button style={{ ...smallBtn, background: color.statusFault, color: '#fff',
                                       borderColor: color.statusFault, marginLeft: 6 }}
                              onClick={() => del(u)}>
                        Confirm delete
                      </button>
                    ) : (
                      <button style={{ ...smallBtn, color: color.statusFault, marginLeft: 6 }}
                              onClick={() => setConfirmId(u.id)}
                              onBlur={() => setConfirmId(null)}>
                        Delete
                      </button>
                    )
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// ─── Audit ────────────────────────────────────────────────────────────────────

function AuditSection({ audit }: { audit: AuditEntry[] }) {
  return (
    <section>
      <SectionTitle>Audit trail</SectionTitle>
      <div style={{ ...cardListStyle, maxHeight: 260, overflowY: 'auto' }}>
        {audit.length === 0 && (
          <div style={{ padding: size.sp4, fontSize: 12, color: color.textDim }}>No staff actions recorded yet.</div>
        )}
        {audit.map((a) => (
          <div key={a.id} style={{ display: 'flex', gap: size.sp3, alignItems: 'baseline',
                                   padding: `${size.sp2} ${size.sp4}`, borderTop: `1px solid ${color.border}`,
                                   fontSize: 12 }}>
            <span style={{ fontFamily: font.mono, color: color.blueBright, whiteSpace: 'nowrap' }}>{a.action}</span>
            <span style={{ color: color.textPrimary }}>{a.actorEmail}</span>
            <span style={{ color: color.textSecondary, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {summarizeDetail(a)}
            </span>
            <span style={{ color: color.textDim, whiteSpace: 'nowrap' }}>
              {formatDistanceToNow(new Date(withZ(a.createdAt)), { addSuffix: true })}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}

function summarizeDetail(a: AuditEntry): string {
  const d = a.detail as Record<string, unknown>
  const bits = [d.name, d.email, d.role != null ? `role=${d.role}` : null, d.minutes != null ? `${d.minutes} min` : null]
  return bits.filter(Boolean).join(' · ')
}

// ─── Shared bits ──────────────────────────────────────────────────────────────

// Belt-and-suspenders ISO parsing (see CLAUDE.md datetime rule).
function withZ(raw: string): string {
  return raw.endsWith('Z') || raw.includes('+') ? raw : raw + 'Z'
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 11, fontFamily: font.mono, color: color.textDim,
                  letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: size.sp2 }}>
      {children}
    </div>
  )
}

const tileStyle: React.CSSProperties = {
  background: color.bgCard, border: `1px solid ${color.border}`, borderRadius: size.radiusMd,
  padding: size.sp4, boxShadow: shadow.sm,
}
const cardListStyle: React.CSSProperties = {
  background: color.bgCard, border: `1px solid ${color.border}`, borderRadius: size.radiusMd,
  overflow: 'hidden',
}
const thStyle: React.CSSProperties = {
  textAlign: 'left', padding: `${size.sp2} ${size.sp4}`, fontSize: 10.5, fontFamily: font.mono,
  letterSpacing: '0.08em', color: color.textDim, textTransform: 'uppercase', fontWeight: 500,
}
const tdStyle: React.CSSProperties = {
  padding: `${size.sp2} ${size.sp4}`, color: color.textSecondary, verticalAlign: 'middle',
}
const smallBtn: React.CSSProperties = {
  background: 'transparent', border: `1px solid ${color.border}`, borderRadius: size.radius,
  color: color.textSecondary, padding: '4px 10px', fontSize: 12, cursor: 'pointer',
}
const backdropStyle: React.CSSProperties = {
  position: 'fixed', inset: 0, background: color.backdrop, zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
}
const modalStyle: React.CSSProperties = {
  width: 420, maxWidth: 'calc(100vw - 32px)', background: color.bgPanel,
  border: `1px solid ${color.border}`, borderRadius: size.radiusLg, boxShadow: shadow.lg,
  padding: size.sp6, display: 'flex', flexDirection: 'column', gap: size.sp4,
}
