import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, NavLink } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { money } from '../../api/billing.api'
import { color, font, size, shadow } from '../../theme/tokens'
import { useSortable } from './useSortable'
import { useFilter } from './useFilter'
import { useAuthStore } from '../../store/auth.store'
import {
  platformApi, type AuditEntry, type PlatformCompany, type PlatformStatus,
  type PlatformUser, type Voucher,
} from '../../api/platform.api'

// Customer-service dashboard. Server-side checks are authoritative — this view
// merely renders what /platform/* returns (404s for anyone else).

export default function PlatformView() {
  const user = useAuthStore((s) => s.user)
  const isOwner = user?.platformRole === 'owner'

  const [status, setStatus]       = useState<PlatformStatus | null>(null)
  const [users, setUsers]         = useState<PlatformUser[]>([])
  const [companies, setCompanies] = useState<PlatformCompany[]>([])
  const [vouchers, setVouchers]   = useState<Voucher[]>([])
  const [audit, setAudit]         = useState<AuditEntry[]>([])
  const [error, setError]         = useState<string | null>(null)
  const [tab, setTab]             = useState<'companies' | 'users' | 'vouchers' | 'audit'>('companies')

  const reload = useCallback(() => {
    platformApi.status().then(setStatus).catch((e) => setError(String(e)))
    platformApi.users().then(setUsers).catch(() => {})
    platformApi.companies().then(setCompanies).catch(() => {})
    platformApi.vouchers().then(setVouchers).catch(() => {})
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
            ['vouchers', `Vouchers (${vouchers.length})`],
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

        {tab === 'companies' && (
          <CompaniesSection companies={companies} isOwner={isOwner} onChanged={reload} />
        )}
        {tab === 'users' && (
          <UsersSection users={users} isOwner={isOwner} selfId={user?.id} onChanged={reload} />
        )}
        {tab === 'vouchers' && (
          <VouchersSection vouchers={vouchers} isOwner={isOwner} onChanged={reload} />
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
    <span style={{ color: tone, whiteSpace: 'nowrap' }}
          title={company.voucherCode
            ? `Voucher ${company.voucherCode}${company.compedUntil
                ? ` · until ${new Date(withZ(company.compedUntil)).toLocaleDateString()}` : ''}`
            : undefined}>
      {company.plan ?? '—'}
      {company.voucherCode && company.compedUntil && (
        <span style={{ fontSize: 10.5, marginLeft: 5, color: color.textDim }}>(voucher)</span>
      )}
      {company.planState && company.planState !== 'ok' && (
        <span style={{ fontSize: 10.5, marginLeft: 5 }}>
          ({company.planState.replace('_', '-')})
        </span>
      )}
    </span>
  )
}

//: What staff may set by hand — mirrors the server's `_STAFF_SETTABLE`.
const STAFF_PLANS = ['free', 'shop', 'plant', 'enterprise']

function StatusSection({ status }: { status: PlatformStatus }) {
  const tiles: [string, string | number][] = [
    // Money first. `fmtCompact` has no currency notion, so these are passed as
    // pre-formatted strings and shown whole.
    ['MRR',                money(status.mrrCents)],
    ['ARR',                money(status.arrCents)],
    ['Paying',             status.payingCompanies],
    ['Comped',             status.compedCompanies],
    ['Free lines',         status.freeCompanies],
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

function CompaniesSection({ companies, isOwner, onChanged }: {
  companies: PlatformCompany[]; isOwner: boolean; onChanged: () => void
}) {
  const navigate = useNavigate()
  const refresh = useAuthStore((s) => s.refresh)
  const setActiveCompany = useAuthStore((s) => s.setActiveCompany)
  const [deleting, setDeleting] = useState<PlatformCompany | null>(null)
  const [confirmName, setConfirmName] = useState('')
  const [planFor, setPlanFor] = useState<PlatformCompany | null>(null)
  const [planChoice, setPlanChoice] = useState('shop')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const savePlan = async () => {
    if (!planFor) return
    setBusy(planFor.id); setError(null)
    try {
      await platformApi.setPlan(planFor.id, planChoice)
      setPlanFor(null)
      onChanged()
    } catch (e) { setError(String(e)) } finally { setBusy(null) }
  }

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
  // Filter first, then sort: sorting a filtered list is what the user means by
  // "sort the results", and it keeps the sort indicator honest about what is
  // actually on screen.
  const filter = useFilter<PlatformCompany>(
    companies,
    (c) => [c.name, c.plan, c.planState, c.id],
    'Filter by name or plan…',
  )
  const sortable = useSortable(filter.rows, [
    { label: 'Company',         value: (c) => c.name },
    // Billing sits next to the name on purpose. It was originally appended
    // after ten operational columns, which put it past the right edge of a
    // 900px table — visible only by scrolling, under a pinned actions column.
    // Plan is the first thing anyone looks at now.
    { label: 'Plan',            value: (c: PlatformCompany) => c.plan ?? '' },
    { label: 'MRR',             value: (c: PlatformCompany) => c.mrrCents, descFirst: true },
    { label: 'Renews',          value: (c: PlatformCompany) => c.renewsAt ?? null },
    { label: 'Active users',    value: (c) => c.activeUsers, descFirst: true },
    { label: 'Stations',        value: (c) => c.stations, descFirst: true },
    { label: 'Lots on floor',   value: (c) => c.cards, descFirst: true },
    { label: 'Devices',         value: (c) => c.devicesConnected, descFirst: true },
    { label: 'API req · month', value: (c) => c.apiRequestsMonth, descFirst: true },
    { label: 'WS msgs · month', value: (c) => c.wsMessagesMonth, descFirst: true },
    { label: 'Last activity',   value: (c) => c.lastActivityAt ?? null, descFirst: true },
    { label: '', sticky: true },
  ], 'Last activity')

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: size.sp4,
                    flexWrap: 'wrap', marginBottom: size.sp2 }}>
        <SectionTitle>Companies ({companies.length})</SectionTitle>
        <div style={{ marginLeft: 'auto' }}>{filter.input}</div>
      </div>
      {error && <div style={{ fontSize: 12, color: color.statusFault, marginBottom: 6 }}>{error}</div>}
      <div style={{ ...cardListStyle, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, minWidth: 900 }}>
          <thead>{sortable.header}</thead>
          <tbody>
            {sortable.rows.map((c) => (
              <tr key={c.id} style={{ borderTop: `1px solid ${color.border}` }}>
                <td style={{ ...tdStyle, color: color.textPrimary, fontWeight: 500 }}>{c.name}</td>
                <td style={tdStyle}><PlanCell company={c} /></td>
                <td style={tdStyle}>{c.mrrCents ? money(c.mrrCents) : '—'}</td>
                <td style={tdStyle}>
                  {c.renewsAt
                    ? formatDistanceToNow(new Date(withZ(c.renewsAt)),
                                          { addSuffix: true })
                    : '—'}
                </td>
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
                  {isOwner && (
                    <button style={{ ...smallBtn, marginLeft: 6 }}
                            onClick={() => {
                              setPlanFor(c)
                              setPlanChoice(STAFF_PLANS.includes(c.plan ?? '') ? c.plan! : 'shop')
                            }}>
                      Plan…
                    </button>
                  )}
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

      {planFor && (
        <div style={backdropStyle} onClick={(e) => { if (e.target === e.currentTarget) setPlanFor(null) }}>
          <div style={modalStyle}>
            <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>
              Set plan for "{planFor.name}"
            </div>
            <p style={{ fontSize: 12.5, color: color.textSecondary, margin: 0, lineHeight: 1.5 }}>
              A hand-set plan has no Stripe subscription and no expiry — the gate
              honours it until you change it, and a webhook never demotes it. This
              is how Plant, Enterprise and comped accounts are set. Any voucher
              clock on the account is cleared.
            </p>
            <select value={planChoice} onChange={(e) => setPlanChoice(e.target.value)}
                    style={{ background: color.bgInput, border: `1px solid ${color.border}`,
                             borderRadius: 4, color: color.textPrimary, padding: '7px 10px',
                             fontSize: 13 }}>
              {STAFF_PLANS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button style={smallBtn} onClick={() => setPlanFor(null)}>Cancel</button>
              <button style={{ ...smallBtn, background: color.bluePrimary, color: '#fff',
                               borderColor: color.bluePrimary }}
                      disabled={busy === planFor.id} onClick={savePlan}>
                {busy === planFor.id ? 'Saving…' : 'Set plan'}
              </button>
            </div>
          </div>
        </div>
      )}

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

  const filter = useFilter<PlatformUser>(
    users,
    // Company names too: "who is at Acme?" is a question support is asked, and
    // the answer is in a cell rather than in the user's own fields.
    (u) => [u.email, u.name, u.platformRole, u.id,
            ...u.companies.map((c) => c.companyName)],
    'Filter by email, name or company…',
  )
  const sortable = useSortable(filter.rows, [
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
      <div style={{ display: 'flex', alignItems: 'center', gap: size.sp4,
                    flexWrap: 'wrap', marginBottom: size.sp2 }}>
        <SectionTitle>Users ({users.length})</SectionTitle>
        <div style={{ marginLeft: 'auto' }}>{filter.input}</div>
      </div>
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

// ─── Vouchers ─────────────────────────────────────────────────────────────────

/** Codes that grant a paid plan free for N months — e.g. CAMA2026 for an
 *  association's members. Owners mint and retire them; support can read the
 *  list to answer "why is this account on Shop for free". */
function VouchersSection({ vouchers, isOwner, onChanged }: {
  vouchers: Voucher[]; isOwner: boolean; onChanged: () => void
}) {
  const [code, setCode] = useState('')
  const [plan, setPlan] = useState('shop')
  const [months, setMonths] = useState('6')
  const [maxRedemptions, setMaxRedemptions] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmId, setConfirmId] = useState<string | null>(null)

  const create = async () => {
    if (!code.trim() || busy) return
    setBusy(true); setError(null)
    try {
      await platformApi.createVoucher({
        code: code.trim(),
        plan,
        months: Math.max(1, parseInt(months, 10) || 1),
        maxRedemptions: maxRedemptions.trim() ? parseInt(maxRedemptions, 10) : null,
        // <input type="date"> yields a bare day; the server reads it as UTC.
        expiresAt: expiresAt ? `${expiresAt}T23:59:59+00:00` : null,
        note: note.trim() || null,
      })
      setCode(''); setNote(''); setMaxRedemptions(''); setExpiresAt('')
      onChanged()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e))
    } finally { setBusy(false) }
  }

  const retire = async (v: Voucher) => {
    setError(null)
    try { await platformApi.deleteVoucher(v.id); setConfirmId(null); onChanged() }
    catch (e) { setError(String(e)) }
  }

  const input: React.CSSProperties = {
    background: color.bgInput, border: `1px solid ${color.border}`, borderRadius: 4,
    color: color.textPrimary, padding: '6px 9px', fontSize: 12.5,
  }

  return (
    <section>
      <SectionTitle>Vouchers ({vouchers.length})</SectionTitle>
      {error && <div style={{ fontSize: 12, color: color.statusFault, marginBottom: 6 }}>{error}</div>}

      {isOwner && (
        <div style={{ ...cardListStyle, padding: size.sp4, marginBottom: size.sp3,
                      display: 'flex', gap: size.sp2, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <label style={voucherLabel}>Code
            <input style={{ ...input, width: 130, fontFamily: font.mono, textTransform: 'uppercase' }}
                   value={code} onChange={(e) => setCode(e.target.value)} placeholder="CAMA2026" />
          </label>
          <label style={voucherLabel}>Plan
            <select style={input} value={plan} onChange={(e) => setPlan(e.target.value)}>
              {['shop', 'plant', 'enterprise'].map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label style={voucherLabel}>Free months
            <input style={{ ...input, width: 60 }} type="number" min={1} max={36}
                   value={months} onChange={(e) => setMonths(e.target.value)} />
          </label>
          <label style={voucherLabel}>Max uses
            <input style={{ ...input, width: 70 }} type="number" min={1} placeholder="∞"
                   value={maxRedemptions} onChange={(e) => setMaxRedemptions(e.target.value)} />
          </label>
          <label style={voucherLabel}>Redeemable until
            <input style={input} type="date"
                   value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
          </label>
          <label style={{ ...voucherLabel, flex: '1 1 160px' }}>Note
            <input style={{ ...input, width: '100%' }} value={note}
                   onChange={(e) => setNote(e.target.value)} placeholder="Who this is for" />
          </label>
          <button style={{ ...smallBtn, background: color.bluePrimary, color: '#fff',
                           borderColor: color.bluePrimary }}
                  disabled={!code.trim() || busy} onClick={create}>
            {busy ? 'Minting…' : 'Mint voucher'}
          </button>
        </div>
      )}

      <div style={{ ...cardListStyle, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              {['Code', 'Plan', 'Free months', 'Redeemed', 'Redeemable until', 'Note', ''].map((h) => (
                <th key={h} style={thStyle}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {vouchers.length === 0 && (
              <tr><td colSpan={7} style={{ ...tdStyle, color: color.textDim }}>
                No vouchers yet{isOwner ? ' — mint one above.' : '.'}
              </td></tr>
            )}
            {vouchers.map((v) => (
              <tr key={v.id} style={{ borderTop: `1px solid ${color.border}` }}>
                <td style={{ ...tdStyle, fontFamily: font.mono, color: color.textPrimary }}>{v.code}</td>
                <td style={tdStyle}>{v.plan}</td>
                <td style={tdStyle}>{v.months}</td>
                <td style={tdStyle}>{v.redeemedCount}{v.maxRedemptions != null && ` of ${v.maxRedemptions}`}</td>
                <td style={tdStyle}>
                  {v.expiresAt ? new Date(withZ(v.expiresAt)).toLocaleDateString() : 'no expiry'}
                </td>
                <td style={{ ...tdStyle, maxWidth: 260, overflow: 'hidden',
                             textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={v.note ?? undefined}>
                  {v.note ?? '—'}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right', whiteSpace: 'nowrap' }}>
                  {isOwner && (
                    confirmId === v.id ? (
                      <button style={{ ...smallBtn, background: color.statusFault, color: '#fff',
                                       borderColor: color.statusFault }}
                              onClick={() => retire(v)}>
                        Confirm retire
                      </button>
                    ) : (
                      <button style={{ ...smallBtn, color: color.statusFault }}
                              onClick={() => setConfirmId(v.id)}
                              onBlur={() => setConfirmId(null)}>
                        Retire
                      </button>
                    )
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: 11.5, color: color.textDim, margin: `${size.sp2} 0 0`, lineHeight: 1.5 }}>
        A company redeems a code in Settings → Billing and gets the plan free for
        the months stated — no card. Codes are case-insensitive and a leading # is
        ignored. Retiring a code stops new redemptions; grants already made keep
        running to their end date.
      </p>
    </section>
  )
}

const voucherLabel: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 4,
  fontSize: 10.5, fontFamily: font.mono, letterSpacing: '0.06em',
  textTransform: 'uppercase', color: color.textDim,
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
  const bits = [d.name, d.email, d.code,
                d.plan != null ? `plan=${d.plan}` : null,
                d.previous != null ? `was ${d.previous}` : null,
                d.months != null ? `${d.months} months` : null,
                d.role != null ? `role=${d.role}` : null,
                d.minutes != null ? `${d.minutes} min` : null]
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
