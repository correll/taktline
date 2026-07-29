import React, { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { platformApi, type ClientErrorReport } from '../../api/platform.api'
import { color, font, size } from '../../theme/tokens'

/** Crashes that reached a customer's screen.
 *
 *  The error boundary shows the person a message and a Reload button, which is
 *  right for them but useless afterwards: the console dies with the tab, and
 *  reloading is the first thing anyone does. These are the reports it sends
 *  before that happens.
 *
 *  The page is built around one action — **Copy for support**. The component
 *  stack is what actually locates a crash (it names the React component, which
 *  names the file), and it is the part nobody retypes. One button puts the
 *  whole report on the clipboard in a form that can be pasted straight into a
 *  support conversation.
 */

function timeAgo(iso: string): string {
  const raw = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z'
  const mins = Math.floor((Date.now() - new Date(raw).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const h = Math.floor(mins / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

/** Everything needed to diagnose, and nothing that needs retyping. */
function asSupportText(e: ClientErrorReport): string {
  const when = e.createdAt.endsWith('Z') || e.createdAt.includes('+') ? e.createdAt : e.createdAt + 'Z'
  return [
    `Taktline client error`,
    `when:    ${new Date(when).toISOString()}`,
    `url:     ${e.url || '—'}`,
    `user:    ${e.userEmail || '(not signed in)'}`,
    `company: ${e.companyId || '—'}`,
    `browser: ${e.userAgent || '—'}`,
    ``,
    `message: ${e.message}`,
    ``,
    `component stack:`,
    e.componentStack || '(none)',
    ``,
    `stack:`,
    e.stack || '(none)',
  ].join('\n')
}

const mono: React.CSSProperties = { fontFamily: font.mono, fontSize: 11.5 }

export default function ClientErrorsView() {
  const [rows, setRows] = useState<ClientErrorReport[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<string>>(new Set())

  useEffect(() => {
    platformApi.clientErrors()
      .then(setRows)
      .catch((e) => setErr(String((e as Error)?.message ?? e)))
  }, [])

  const copy = async (e: ClientErrorReport) => {
    try {
      await navigator.clipboard.writeText(asSupportText(e))
      setCopied(e.id)
      setTimeout(() => setCopied(null), 2000)
    } catch { /* clipboard blocked — the details are still on screen to select */ }
  }

  const toggle = (id: string) =>
    setOpen((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  return (
    <div style={{ padding: size.sp6, overflow: 'auto', height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp4, marginBottom: size.sp2 }}>
        <h2 style={{ margin: 0, fontSize: 18, color: color.textPrimary }}>Client errors</h2>
        <NavLink to="/platform" style={{ fontSize: 12, color: color.blueBright, textDecoration: 'none' }}>
          ← Platform
        </NavLink>
      </div>
      <p style={{ fontSize: 12, color: color.textDim, margin: `0 0 ${size.sp5}`, maxWidth: 680, lineHeight: 1.6 }}>
        Crashes that reached a customer&rsquo;s screen, newest first. The error boundary sends these
        before the person reloads, which is why they still exist.{' '}
        <b style={{ color: color.textSecondary }}>Copy for support</b> puts the whole report —
        message, component stack, URL, browser — on the clipboard, ready to paste. The component
        stack is the part that actually locates the bug. Kept for 30 days.
      </p>

      {err && <div style={{ color: color.statusFault, fontSize: 13 }}>{err}</div>}
      {rows === null && !err && <div style={{ color: color.textDim, fontSize: 13 }}>Loading…</div>}
      {rows?.length === 0 && (
        <div style={{
          border: `1px dashed ${color.border}`, borderRadius: size.radius,
          padding: size.sp6, textAlign: 'center', color: color.textDim, fontSize: 13,
        }}>
          No crashes recorded. This is the good outcome.
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp3 }}>
        {rows?.map((e) => (
          <div key={e.id} style={{
            background: color.bgCard, border: `1px solid ${color.border}`,
            borderRadius: size.radius, padding: size.sp4,
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: size.sp3 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ ...mono, color: color.textPrimary, wordBreak: 'break-word' }}>
                  {e.message}
                </div>
                <div style={{ fontSize: 11, color: color.textDim, marginTop: 4 }}>
                  {timeAgo(e.createdAt)} · {e.url || '—'} · {e.userEmail || 'not signed in'}
                </div>
              </div>
              <button onClick={() => copy(e)} style={{
                flexShrink: 0, background: copied === e.id ? color.statusRunning : color.bluePrimary,
                color: '#fff', border: 'none', borderRadius: size.radius,
                padding: `6px ${size.sp4}`, fontSize: 12, fontWeight: 600, cursor: 'pointer',
              }}>
                {copied === e.id ? 'Copied' : 'Copy for support'}
              </button>
              <button onClick={() => toggle(e.id)} style={{
                flexShrink: 0, background: 'transparent', border: `1px solid ${color.border}`,
                borderRadius: size.radius, color: color.textSecondary,
                padding: `6px ${size.sp3}`, fontSize: 12, cursor: 'pointer',
              }}>
                {open.has(e.id) ? 'Hide' : 'Stack'}
              </button>
            </div>
            {open.has(e.id) && (
              <pre style={{
                ...mono, marginTop: size.sp3, marginBottom: 0, color: color.textSecondary,
                background: color.bgDeep, border: `1px solid ${color.border}`,
                borderRadius: size.radius, padding: size.sp3,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflow: 'auto',
              }}>{asSupportText(e)}</pre>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
