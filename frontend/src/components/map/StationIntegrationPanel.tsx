import React, { useEffect, useState } from 'react'
import type { Station } from '../../models'
import { useStationsStore, useProcessesStore } from '../../store'
import { ordersApi, type ProductionOrder, type OutboxEvent } from '../../api/integrations.api'
import { integrationProvider, roleLabel } from '../../domain/integrations'
import { color, font, size } from '../../theme/tokens'

/** What a selected integration station shows instead of lots.
 *
 *  An ordinary station answers "what is here?" — this one has nothing here,
 *  ever. The useful questions are different: is it wired to the right place,
 *  what do I still have to fetch from the partner, and is anything actually
 *  flowing? The setup list is the part the product was missing entirely:
 *  people were expected to discover what Odoo wanted by creating an Odoo
 *  account and failing.
 */

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', gap: size.sp3,
                padding: `${size.sp2} 0`, borderBottom: `1px solid ${color.border}`, fontSize: 12 }}>
    <span style={{ color: color.textSecondary, flexShrink: 0 }}>{label}</span>
    <span style={{ color: color.textPrimary, textAlign: 'right', overflowWrap: 'anywhere' }}>{children}</span>
  </div>
)

const SectionLabel = ({ children }: { children: React.ReactNode }) => (
  <div style={{ fontSize: 10, fontFamily: font.mono, letterSpacing: '0.1em',
                color: color.textDim, margin: `${size.sp5} 0 ${size.sp2}` }}>{children}</div>
)

export default function StationIntegrationPanel({ station }: { station: Station }) {
  const provider = integrationProvider(station.integrationProvider)
  const stations = useStationsStore((s) => s.stations)
  const routes   = useProcessesStore((s) => s.routes)
  const [orders, setOrders] = useState<ProductionOrder[] | null>(null)
  const [pending, setPending] = useState<OutboxEvent[] | null>(null)

  useEffect(() => {
    // Both need the orders scope; a plain member simply sees no activity block
    // rather than an error they can do nothing about.
    ordersApi.list().then(setOrders).catch(() => setOrders(null))
    ordersApi.outbox('pending').then(setPending).catch(() => setPending(null))
  }, [station._id])

  if (!provider) return null

  const feeds   = Object.values(routes).filter((r) => r.load === station._id)
  const takes   = Object.values(routes).filter((r) => r.unload === station._id)
  const name    = (id: string) => stations[id]?.name ?? '—'
  const mine    = orders?.filter((o) => o.source === provider.id) ?? []
  const minePending = pending?.filter((e) => (e.payload as { source?: string })?.source === provider.id) ?? []

  return (
    <div style={{ padding: `0 ${size.sp4} ${size.sp6}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3, marginTop: size.sp3 }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 34, height: 34, borderRadius: 8, flexShrink: 0,
          background: provider.color, color: provider.ink, fontWeight: 700,
          fontSize: provider.mark.length > 1 ? 14 : 18,
        }}>{provider.mark}</span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: color.textPrimary }}>{provider.label}</div>
          <div style={{ fontSize: 11, color: color.textDim }}>{roleLabel(station.integrationRole)}</div>
        </div>
      </div>

      <p style={{ fontSize: 11.5, color: color.textDim, lineHeight: 1.6, marginTop: size.sp3 }}>
        {provider.blurb} <b style={{ color: color.textSecondary }}>Lots never sit here.</b> An order
        from {provider.label} asks for one finished product, so a link out of this station points at
        the place <i>that product is made</i> — creating the order there starts a pull, and the pull
        orders every precursor back down to the material queues on its own. A link into this station
        is the reverse: finished goods leave through it when someone sends them.
      </p>

      {/* ── How it is wired ── */}
      <SectionLabel>WIRING</SectionLabel>
      {feeds.length === 0 && takes.length === 0 ? (
        <div style={{ fontSize: 11.5, color: color.warnText, lineHeight: 1.55 }}>
          Not connected to anything yet. Draw a link from here to the station where the product you
          order is made — for an assembled product that is the station it is assembled at, not the
          queues its parts come from. For handoffs, draw one from your last station to here.
        </div>
      ) : (
        <>
          {feeds.map((r) => <Row key={r._id} label="Orders the product made at">{name(r.unload)}</Row>)}
          {takes.map((r) => <Row key={r._id} label="Takes finished goods from">{name(r.load)}</Row>)}
        </>
      )}

      {/* ── Is anything flowing ── */}
      {orders !== null && (
        <>
          <SectionLabel>ACTIVITY</SectionLabel>
          <Row label="Orders released">{mine.length}</Row>
          <Row label="Awaiting delivery">{minePending.length}</Row>
          {mine[0] && (
            <Row label="Latest">
              <span style={{ fontFamily: font.mono, fontSize: 11 }}>
                {mine[0].externalRef ?? mine[0].id.slice(-6)} · {mine[0].status}
              </span>
            </Row>
          )}
        </>
      )}

      {/* ── What you still have to fetch ── */}
      {provider.setup.fields.length > 0 && (
        <>
          <SectionLabel>WHAT YOU NEED FROM {provider.label.toUpperCase()}</SectionLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp3 }}>
            {provider.setup.fields.map((f) => (
              <div key={f.env}>
                <div style={{ fontSize: 12, color: color.textPrimary }}>
                  {f.label}
                  {f.optional && <span style={{ color: color.textDim, fontSize: 10.5 }}> · optional</span>}
                </div>
                <div style={{ fontSize: 11, color: color.textDim, lineHeight: 1.5, marginTop: 1 }}>{f.where}</div>
                <code style={{ fontFamily: font.mono, fontSize: 10.5, color: color.blueBright }}>{f.env}</code>
              </div>
            ))}
          </div>
        </>
      )}

      {provider.setup.inPartner.length > 0 && (
        <>
          <SectionLabel>SET UP IN {provider.label.toUpperCase()}</SectionLabel>
          <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11.5, color: color.textDim, lineHeight: 1.6 }}>
            {provider.setup.inPartner.map((t) => <li key={t}>{t}</li>)}
          </ul>
        </>
      )}

      {/* ── What Taktline needs from you ── */}
      <SectionLabel>WHAT TAKTLINE NEEDS</SectionLabel>
      <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11.5, color: color.textDim, lineHeight: 1.6 }}>
        <li>An API key with the <b style={{ color: color.textSecondary }}>orders</b> scope
          (Settings → Integrations) — the connector authenticates with it.</li>
        <li>A <b style={{ color: color.textSecondary }}>product mapping</b>: each {provider.label} product
          reference → a Taktline product id. Ids are listed under Settings → Integrations.</li>
        {provider.setup.orderStates && (
          <li>Which states mean “make this”: {provider.setup.orderStates}</li>
        )}
      </ul>

      {provider.setup.caveats && provider.setup.caveats.length > 0 && (
        <>
          <SectionLabel>WORTH KNOWING</SectionLabel>
          <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11.5, color: color.textDim, lineHeight: 1.6 }}>
            {provider.setup.caveats.map((t) => <li key={t}>{t}</li>)}
          </ul>
        </>
      )}

      <div style={{ fontSize: 11, color: color.textDim, marginTop: size.sp5, lineHeight: 1.55 }}>
        The connector runs on your side and polls {provider.label}; Taktline never calls it, so no
        inbound firewall rule is needed. Run it with{' '}
        <code style={{ fontFamily: font.mono, color: color.textSecondary }}>
          python -m taktline_connect {provider.id}
        </code>.
      </div>
    </div>
  )
}
