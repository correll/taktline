import React, { useEffect, useState } from 'react'
import { apiKeysApi, ordersApi, templatesApi, type ApiKey, type ProductionOrder, type OutboxEvent, type TemplateRef, type ScopeInfo, type ImportResult } from '../../api/integrations.api'
import { useGlobalSettingsStore } from '../../store/globalSettings.store'
import { color, font, size } from '../../theme/tokens'
import IntegrationLocations from './IntegrationLocations'

const cell: React.CSSProperties = { padding: `${size.sp2} ${size.sp3}`, fontSize: 13, color: color.textPrimary, textAlign: 'left' }
const head: React.CSSProperties = { ...cell, color: color.textSecondary, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }
const mono: React.CSSProperties = { fontFamily: font.mono, fontSize: 12 }

function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div style={{ marginBottom: size.sp8 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: size.sp3 }}>
        <h3 style={{ color: color.textPrimary, fontSize: 15, margin: 0, fontFamily: font.sans }}>{title}</h3>
        {right}
      </div>
      {children}
    </div>
  )
}

/** The link a shop gives the customer who placed this order.
 *
 *  Shown as disabled rather than hidden when tracking is off: an operator
 *  looking for "where do I get the tracking link" needs to find out that the
 *  switch exists, and a control that is simply absent teaches them nothing. */
function TrackingLink({ order, enabled }: { order: ProductionOrder; enabled: boolean }) {
  const [copied, setCopied] = useState(false)
  if (!order.trackingUrl) return <span style={{ color: color.textDim }}>—</span>
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
      await navigator.clipboard.writeText(order.trackingUrl!)
      setCopied(true); setTimeout(() => setCopied(false), 1800)
    } catch { window.prompt('Copy this link', order.trackingUrl!) }
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

export default function IntegrationsTab() {
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [orders, setOrders] = useState<ProductionOrder[]>([])
  const trackingOn = useGlobalSettingsStore((s) => s.settings.orderTracking)
  const [events, setEvents] = useState<OutboxEvent[]>([])
  const [templates, setTemplates] = useState<TemplateRef[]>([])
  const [scopeCatalog, setScopeCatalog] = useState<ScopeInfo[]>([])
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<string[]>(['orders'])
  const [created, setCreated] = useState<string | null>(null)   // full secret, shown once
  const [copied, setCopied] = useState(false)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const [importing, setImporting] = useState(false)
  const [err, setErr] = useState('')

  async function load() {
    try {
      setKeys(await apiKeysApi.list())
      setOrders(await ordersApi.list())
      setEvents(await ordersApi.outbox(''))   // all statuses
      setTemplates(await templatesApi.list())
      setScopeCatalog(await apiKeysApi.scopes())
    } catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [])

  function toggleScope(s: string) {
    setScopes((cur) => cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s])
  }

  async function createKey(e: React.FormEvent) {
    e.preventDefault(); setErr('')
    if (scopes.length === 0) { setErr('Select at least one scope'); return }
    try {
      const k = await apiKeysApi.create(name.trim() || 'integration', scopes)
      setCreated(k.key); setCopied(false); setName(''); setScopes(['orders'])
      await load()
    } catch (e) { setErr(String(e)) }
  }

  async function onImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setErr(''); setImporting(true); setImportResult(null)
    try {
      setImportResult(await ordersApi.importCsv(file))
      await load()
    } catch (e) { setErr(String(e)) } finally { setImporting(false) }
  }
  async function revoke(id: string) {
    setErr('')
    try { await apiKeysApi.revoke(id); await load() } catch (e) { setErr(String(e)) }
  }

  const pending = events.filter((e) => e.status === 'pending').length
  const failed = events.filter((e) => e.status === 'failed').length

  const btn = (bg: string): React.CSSProperties => ({
    background: 'transparent', border: `1px solid ${color.border}`, color: bg, borderRadius: size.radius,
    padding: `${size.sp1} ${size.sp2}`, fontSize: 12, cursor: 'pointer',
  })

  return (
    <div style={{ padding: size.sp6, overflow: 'auto', height: '100%', boxSizing: 'border-box', maxWidth: 900 }}>
      <p style={{ color: color.textSecondary, fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
        Connect an ERP or automation tool (Odoo, NetSuite, Zapier, a custom script). An integration authenticates with
        a scoped API key and uses the same two-endpoint contract: <b style={{ color: color.textPrimary }}>release orders</b> and
        <b style={{ color: color.textPrimary }}> drain completions</b>.
      </p>

      {err && <div style={{ color: color.statusFault, fontSize: 13, marginBottom: size.sp3 }}>{err}</div>}

      {/* API keys */}
      <Section title="API keys">
        <form onSubmit={createKey} style={{ marginBottom: size.sp3 }}>
          <div style={{ display: 'flex', gap: size.sp2 }}>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Key name (e.g. Odoo production)"
                   style={{ flex: 1, maxWidth: 320, padding: `${size.sp2} ${size.sp3}`, background: color.bgCard,
                            border: `1px solid ${color.border}`, borderRadius: size.radius, color: color.textPrimary, fontSize: 13, outline: 'none' }} />
            <button type="submit" style={{ padding: `${size.sp2} ${size.sp4}`, background: color.bluePrimary, color: color.white,
                                           border: 'none', borderRadius: size.radius, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              Create key
            </button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: size.sp3, marginTop: size.sp2 }}>
            {scopeCatalog.map((s) => (
              <label key={s.scope} title={s.description}
                     style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: color.textSecondary, cursor: 'pointer' }}>
                <input type="checkbox" checked={scopes.includes(s.scope)} onChange={() => toggleScope(s.scope)} />
                <span style={mono}>{s.scope}</span>
                <span style={{ color: color.textDim }}>· {s.description}</span>
              </label>
            ))}
          </div>
        </form>
        {keys.length === 0 ? <div style={{ color: color.textDim, fontSize: 13 }}>No API keys yet.</div> : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: `1px solid ${color.border}` }}>
              <th style={head}>Name</th><th style={head}>Key</th><th style={head}>Scopes</th><th style={head}>Last used</th><th style={head}></th>
            </tr></thead>
            <tbody>{keys.map((k) => (
              <tr key={k.id} style={{ borderBottom: `1px solid ${color.border}`, opacity: k.revoked ? 0.5 : 1 }}>
                <td style={cell}>{k.name}</td>
                <td style={{ ...cell, ...mono, color: color.textSecondary }}>{k.prefix}…{k.revoked && ' (revoked)'}</td>
                <td style={{ ...cell, ...mono, color: color.textDim }}>{k.scopes.join(', ')}</td>
                <td style={{ ...cell, color: color.textDim, fontSize: 12 }}>{k.lastUsedAt ? new Date(k.lastUsedAt).toLocaleString() : '—'}</td>
                <td style={{ ...cell, textAlign: 'right' }}>{!k.revoked && <button style={btn(color.statusFault)} onClick={() => revoke(k.id)}>Revoke</button>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>

      {/* CSV import */}
      <Section title="Import orders (CSV)">
        <p style={{ color: color.textSecondary, fontSize: 13, marginTop: 0, marginBottom: size.sp3 }}>
          The no-API on-ramp — release a batch from a spreadsheet. Columns:
          <span style={mono}> product</span> (template name or id),
          <span style={mono}> quantity</span>, optional
          <span style={mono}> source</span>,<span style={mono}> externalRef</span>,<span style={mono}> note</span>.
        </p>
        <label style={{ display: 'inline-block', padding: `${size.sp2} ${size.sp4}`, background: color.bgCard,
                        border: `1px solid ${color.border}`, borderRadius: size.radius, color: color.textPrimary,
                        fontSize: 13, cursor: importing ? 'default' : 'pointer', opacity: importing ? 0.6 : 1 }}>
          {importing ? 'Importing…' : 'Choose CSV file'}
          <input type="file" accept=".csv,text/csv" onChange={onImport} disabled={importing} style={{ display: 'none' }} />
        </label>
        {importResult && (
          <div style={{ marginTop: size.sp3, fontSize: 13 }}>
            <div style={{ color: color.textPrimary }}>
              <b>{importResult.summary.released}</b> released,{' '}
              <span style={{ color: color.textSecondary }}>{importResult.summary.duplicate} duplicate</span>,{' '}
              <span style={{ color: importResult.summary.errors ? color.statusFault : color.textDim }}>
                {importResult.summary.errors} error{importResult.summary.errors === 1 ? '' : 's'}
              </span>{' '}of {importResult.summary.total}.
            </div>
            {importResult.rows.filter((r) => r.status === 'error').slice(0, 8).map((r) => (
              <div key={r.row} style={{ ...mono, color: color.statusFault, fontSize: 12, marginTop: 2 }}>
                row {r.row}{r.externalRef ? ` (${r.externalRef})` : ''}: {r.error}
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Recent orders */}
      <Section title="Recent orders" right={<span style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono }}>{orders.length} total</span>}>
        {orders.length === 0 ? <div style={{ color: color.textDim, fontSize: 13 }}>No production orders yet.</div> : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: `1px solid ${color.border}` }}>
              <th style={head}>Source</th><th style={head}>Ext. ref</th><th style={head}>Qty</th><th style={head}>Done</th><th style={head}>Status</th><th style={head}>Customer link</th>
            </tr></thead>
            <tbody>{orders.slice(0, 12).map((o) => (
              <tr key={o.id} style={{ borderBottom: `1px solid ${color.border}` }}>
                <td style={cell}>{o.source}</td>
                <td style={{ ...cell, ...mono, color: color.textSecondary }}>{o.externalRef ?? '—'}</td>
                <td style={cell}>{o.quantity}</td>
                <td style={cell}>{o.quantityDone}</td>
                <td style={{ ...cell }}><StatusPill s={o.status} /></td>
                <td style={cell}><TrackingLink order={o} enabled={trackingOn} /></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>

      {/* Outbox */}
      <Section title="Completion outbox" right={
        <span style={{ fontSize: 11, fontFamily: font.mono }}>
          {failed > 0 && <span style={{ color: color.statusFault, marginRight: size.sp2 }}>{failed} failed</span>}
          <span style={{ color: pending ? color.statusWarning : color.textDim }}>{pending} pending</span>
        </span>
      }>
        {failed > 0 && (
          <div style={{ color: color.statusFault, fontSize: 12, marginBottom: size.sp3 }}>
            {failed === 1 ? 'One event' : `${failed} events`} could not be delivered after
            repeated attempts and stopped retrying. Check that the connector is running and
            that the order still exists in the ERP.
          </div>
        )}
        {events.length === 0 ? <div style={{ color: color.textDim, fontSize: 13 }}>No events yet — they appear when finished lots reach a warehouse.</div> : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: `1px solid ${color.border}` }}>
              <th style={head}>Event</th><th style={head}>Source</th><th style={head}>Ext. ref</th>
              <th style={head}>Status</th><th style={head}>When</th>
            </tr></thead>
            <tbody>{events.slice(-12).reverse().map((e) => (
              <tr key={e.id} style={{ borderBottom: `1px solid ${color.border}` }}>
                <td style={{ ...cell, ...mono }}>{e.eventType}</td>
                <td style={{ ...cell, ...mono, color: color.textDim }}>{String((e.payload as any).source ?? '—')}</td>
                <td style={{ ...cell, ...mono, color: color.textSecondary }}>{String((e.payload as any).externalRef ?? '—')}</td>
                <td style={cell}>
                  <StatusPill s={e.status} />
                  {e.attempts > 1 && <span style={{ ...mono, color: color.textDim, fontSize: 11, marginLeft: 6 }}>×{e.attempts}</span>}
                </td>
                <td style={{ ...cell, color: color.textDim, fontSize: 12 }}>{new Date(e.createdAt).toLocaleString()}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>

      {/* Product ids — for building a connector's PRODUCT_MAPPING */}
      <Section title="Product ids" right={
        templates.length > 0 ? (
          <button style={btn(color.blueBright)} onClick={() => {
            const map = Object.fromEntries(templates.map((t) => [t.name, t._id]))
            navigator.clipboard?.writeText(JSON.stringify(map))
          }}>Copy PRODUCT_MAPPING</button>
        ) : undefined
      }>
        <p style={{ color: color.textSecondary, fontSize: 13, marginTop: 0, marginBottom: size.sp3 }}>
          Map each ERP product ref (Odoo <span style={mono}>default_code</span>, NetSuite <span style={mono}>itemid</span>)
          to a Taktline template id in your connector's <span style={mono}>PRODUCT_MAPPING</span>.
        </p>
        {templates.length === 0 ? <div style={{ color: color.textDim, fontSize: 13 }}>No templates yet.</div> : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: `1px solid ${color.border}` }}>
              <th style={head}>Template</th><th style={head}>Id</th><th style={head}></th>
            </tr></thead>
            <tbody>{templates.map((t) => (
              <tr key={t._id} style={{ borderBottom: `1px solid ${color.border}` }}>
                <td style={cell}>
                  {t.color && <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: t.color, marginRight: 6 }} />}
                  {t.name}
                </td>
                <td style={{ ...cell, ...mono, color: color.textSecondary }}>{t._id}</td>
                <td style={{ ...cell, textAlign: 'right' }}>
                  <button style={btn(color.textSecondary)} onClick={() => navigator.clipboard?.writeText(t._id)}>Copy</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>

      {/* Where work enters and leaves — the boundary made explicit. */}
      <Section title="Integration stations">
        <IntegrationLocations />
      </Section>

      {/* Contract reference */}
      <Section title="Connect an integration">
        <div style={{ background: color.bgCard, border: `1px solid ${color.border}`, borderRadius: size.radius, padding: size.sp4, ...mono, color: color.textSecondary, lineHeight: 1.7, overflowX: 'auto' }}>
          <div><span style={{ color: color.textDim }}># auth (company-scoped key)</span></div>
          <div>Authorization: Bearer &lt;your key&gt;</div>
          <div style={{ marginTop: 8 }}><span style={{ color: color.textDim }}># release an order (idempotent on source+externalRef)</span></div>
          <div><span style={{ color: color.statusRunning }}>POST</span> /orders</div>
          <div>{`{ "productTemplateId": "<id>", "quantity": 5, "source": "odoo", "externalRef": "MO-123" }`}</div>
          <div style={{ marginTop: 8 }}><span style={{ color: color.textDim }}># drain completions, then ack</span></div>
          <div><span style={{ color: color.statusRunning }}>GET</span>  /orders/outbox?status=pending&amp;source=odoo</div>
          <div><span style={{ color: color.statusRunning }}>POST</span> /orders/outbox/&#123;id&#125;/ack</div>
          <div><span style={{ color: color.statusRunning }}>POST</span> /orders/outbox/&#123;id&#125;/fail <span style={{ color: color.textDim }}># retries, then parks</span></div>
        </div>
      </Section>

      {/* Created-key modal */}
      {created && (
        <div onClick={() => setCreated(null)} style={{ position: 'fixed', inset: 0, background: color.backdrop, zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: size.sp6 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ width: 520, maxWidth: '100%', background: color.bgPanel, border: `1px solid ${color.borderActive}`, borderRadius: size.radiusLg, padding: size.sp6 }}>
            <h3 style={{ color: color.textPrimary, marginTop: 0, fontSize: 16 }}>Copy your API key now</h3>
            <p style={{ color: color.textSecondary, fontSize: 13 }}>This is the only time the full key is shown. Store it in your connector's config.</p>
            <div style={{ display: 'flex', gap: size.sp2 }}>
              <code style={{ flex: 1, ...mono, background: color.bgCard, border: `1px solid ${color.border}`, borderRadius: size.radius, padding: size.sp3, color: color.blueBright, wordBreak: 'break-all' }}>{created}</code>
              <button onClick={() => { navigator.clipboard?.writeText(created); setCopied(true) }}
                      style={{ padding: `0 ${size.sp4}`, background: color.bluePrimary, color: color.white, border: 'none', borderRadius: size.radius, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div style={{ textAlign: 'right', marginTop: size.sp5 }}>
              <button onClick={() => setCreated(null)} style={{ background: 'transparent', color: color.textSecondary, border: `1px solid ${color.border}`, borderRadius: size.radius, padding: `${size.sp2} ${size.sp5}`, fontSize: 13, cursor: 'pointer' }}>Done</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StatusPill({ s }: { s: string }) {
  const map: Record<string, string> = {
    completed: color.statusRunning, delivered: color.statusRunning, released: color.blueBright,
    in_progress: color.statusWarning, pending: color.statusWarning, cancelled: color.textDim, failed: color.statusFault,
  }
  const c = map[s] ?? color.textSecondary
  return <span style={{ color: c, fontSize: 12, fontFamily: font.mono }}>{s}</span>
}
