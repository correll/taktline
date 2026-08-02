import { useCallback, useEffect, useRef, useState } from 'react'
import { ordersApi, type ImportResult, type OutboxEvent, type ProductionOrder }
  from '../../api/integrations.api'
import { useGlobalSettingsStore } from '../../store/globalSettings.store'
import { color, font, size } from '../../theme/tokens'

/**
 * Orders, on the Lots board rather than in Settings.
 *
 * They were under Settings → Integrations, which is where they came *from* and
 * not where anybody looks for them: an order is work on the floor, so it belongs
 * beside the lots it released. It also hid the customer tracking link somewhere
 * nobody running the shop would find it.
 */

const MAX_ROWS = 25

export default function OrdersPanel() {
  const [orders, setOrders] = useState<ProductionOrder[]>([])
  const [outbox, setOutbox] = useState<OutboxEvent[]>([])
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const trackingOn = useGlobalSettingsStore((s) => s.settings.orderTracking)
  const fetchSettings = useGlobalSettingsStore((s) => s.fetch)

  const reload = useCallback(async () => {
    setError(null)
    try {
      setOrders(await ordersApi.list())
      setOutbox(await ordersApi.outbox(''))
    } catch (e) { setError(String(e)) }
  }, [])

  useEffect(() => { void reload(); void fetchSettings() }, [reload, fetchSettings])

  const onFile = async (file: File) => {
    setImporting(true); setError(null); setResult(null)
    try {
      setResult(await ordersApi.importCsv(file))
      await reload()
    } catch (e) { setError(String(e)) } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const failed = outbox.filter((e) => e.status === 'failed').length

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: size.sp6 }}>
      <div style={{ maxWidth: 980, display: 'flex', flexDirection: 'column', gap: size.sp6 }}>
        {error && (
          <div style={{ fontSize: 12.5, color: color.statusFault }}>{error}</div>
        )}

        <Section
          title="Orders"
          right={<span style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono }}>
            {orders.length} total
          </span>}
        >
          <p style={note}>
            An order is a release of N units of a product onto the floor — from your
            ERP or shop system, a CSV, or the API. It seeds every precursor lot the
            product needs and follows them to completion.
          </p>
          {orders.length === 0 ? (
            <div style={{ color: color.textDim, fontSize: 13 }}>
              No production orders yet. Lots created by hand on the board are not
              orders — they are still trackable, from the lot itself.
            </div>
          ) : (
            <table style={table}>
              <thead><tr style={{ borderBottom: `1px solid ${color.border}` }}>
                <th style={head}>Source</th><th style={head}>Ext. ref</th>
                <th style={head}>Qty</th><th style={head}>Done</th>
                <th style={head}>Status</th><th style={head}>Customer link</th>
              </tr></thead>
              <tbody>{orders.slice(0, MAX_ROWS).map((o) => (
                <tr key={o.id} style={{ borderBottom: `1px solid ${color.border}` }}>
                  <td style={cell}>{o.source}</td>
                  <td style={{ ...cell, ...mono, color: color.textSecondary }}>{o.externalRef ?? '—'}</td>
                  <td style={cell}>{o.quantity}</td>
                  <td style={cell}>{o.quantityDone}</td>
                  <td style={cell}><StatusPill s={o.status} /></td>
                  <td style={cell}><TrackingLink url={o.trackingUrl} enabled={trackingOn} /></td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Section>

        <Section title="Import orders (CSV)">
          <p style={note}>
            The no-API on-ramp — release a batch from a spreadsheet. Columns:
            <span style={mono}> product</span> (template name or id),
            <span style={mono}> quantity</span>, optional
            <span style={mono}> source</span>,<span style={mono}> externalRef</span>,
            <span style={mono}> note</span>. Anything else becomes order data printed
            on the card. Each row is imported on its own, so one bad row is reported
            rather than fatal, and re-importing the same file changes nothing.
          </p>
          <input ref={fileRef} type="file" accept=".csv,text/csv" disabled={importing}
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) void onFile(f) }}
                 style={{ fontSize: 13, color: color.textSecondary }} />
          {result && (
            <div style={{ marginTop: size.sp3, fontSize: 12.5, color: color.textSecondary }}>
              {result.summary.released} released · {result.summary.duplicate} already
              known · {result.summary.errors} failed
              {result.rows.filter((r) => r.status === 'error').map((r) => (
                <div key={r.row} style={{ color: color.statusFault, marginTop: 4 }}>
                  row {r.row}{r.externalRef ? ` (${r.externalRef})` : ''}: {r.error}
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section
          title="Completion outbox"
          right={<span style={{ fontSize: 11, fontFamily: font.mono }}>
            {failed > 0 && (
              <span style={{ color: color.statusFault, marginRight: size.sp2 }}>
                {failed} failed
              </span>
            )}
            <span style={{ color: color.textDim }}>{outbox.length} events</span>
          </span>}
        >
          <p style={note}>
            What Taktline has told your ERP. An event is written in the same
            transaction as the movement that caused it, so a completion is never
            lost and never sent twice.
          </p>
          {outbox.length === 0 ? (
            <div style={{ color: color.textDim, fontSize: 13 }}>Nothing to deliver.</div>
          ) : (
            <table style={table}>
              <thead><tr style={{ borderBottom: `1px solid ${color.border}` }}>
                <th style={head}>Event</th><th style={head}>Ext. ref</th>
                <th style={head}>Attempts</th><th style={head}>Status</th>
              </tr></thead>
              <tbody>{outbox.slice(0, MAX_ROWS).map((e) => (
                <tr key={e.id} style={{ borderBottom: `1px solid ${color.border}` }}>
                  <td style={{ ...cell, ...mono }}>{e.eventType}</td>
                  <td style={{ ...cell, ...mono, color: color.textSecondary }}>
                    {String((e.payload as Record<string, unknown>).externalRef ?? '—')}
                  </td>
                  <td style={cell}>{e.attempts}</td>
                  <td style={cell}><StatusPill s={e.status} /></td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Section>
      </div>
    </div>
  )
}

/** The read-only link for the customer who placed this order.
 *
 *  Shown as "off" rather than hidden when tracking is disabled: somebody looking
 *  for the link needs to discover that the switch exists, and a control that is
 *  simply absent teaches them nothing. */
export function TrackingLink({ url, enabled }: { url?: string | null; enabled: boolean }) {
  const [copied, setCopied] = useState(false)
  if (!url) return <span style={{ color: color.textDim }}>—</span>
  if (!enabled) {
    return (
      <span style={{ fontSize: 11, color: color.textDim }}
            title="Switch on customer order tracking in Settings → Global">
        off
      </span>
    )
  }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true); setTimeout(() => setCopied(false), 1800)
    } catch { window.prompt('Copy this link', url) }
  }
  return (
    <button onClick={copy} style={{
      background: 'none', border: `1px solid ${color.border}`, borderRadius: size.radius,
      color: copied ? color.statusRunning : color.textSecondary,
      fontSize: 11, padding: '2px 8px', cursor: 'pointer', fontFamily: 'inherit',
    }}>
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function Section({ title, right, children }: {
  title: string; right?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp3,
                    marginBottom: size.sp3 }}>
        <h3 style={{ margin: 0, fontSize: 13, fontWeight: 600, color: color.textPrimary }}>
          {title}
        </h3>
        <div style={{ marginLeft: 'auto' }}>{right}</div>
      </div>
      {children}
    </section>
  )
}

function StatusPill({ s }: { s: string }) {
  const tone = s === 'failed' ? color.statusFault
             : s === 'completed' || s === 'delivered' ? color.statusRunning
             : s === 'cancelled' ? color.textDim
             : color.statusWarning
  return (
    <span style={{
      fontSize: 10.5, fontFamily: font.mono, color: tone,
      border: `1px solid ${tone}55`, borderRadius: size.radiusFull, padding: '1px 8px',
    }}>{s}</span>
  )
}

const table = { width: '100%', borderCollapse: 'collapse' } as const
const head = { textAlign: 'left', fontSize: 10.5, fontFamily: font.mono,
               color: color.textDim, padding: '6px 8px', fontWeight: 400 } as const
const cell = { fontSize: 12.5, padding: '7px 8px', color: color.textPrimary } as const
const mono = { fontFamily: font.mono } as const
const note = { color: color.textSecondary, fontSize: 12.5, lineHeight: 1.6,
               margin: `0 0 ${size.sp3}` } as const
