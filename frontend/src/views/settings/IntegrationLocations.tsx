import React, { useMemo, useState } from 'react'
import { useStationsStore, useMapSettingsStore } from '../../store'
import { color, font, size } from '../../theme/tokens'
import {
  INTEGRATION_PROVIDERS, allowedRoles, integrationProvider, isIntegrationStation, roleLabel,
  type IntegrationRole,
} from '../../domain/integrations'

/** Binding a partner to a location on the map.
 *
 *  This is where the integration boundary stops being implicit. Before, the
 *  only thing that made a location a source was having no incoming routes, and
 *  the only thing that made it a sink was having no outgoing ones — so the map
 *  could not show you where work entered or left, and a company with a
 *  warehouse *and* a shipping desk had no way to say which one ships.
 *
 *  A bound location is an ordinary station in every other respect: it sits on
 *  the floor plan, you drag it where it belongs, and you draw routes to and
 *  from it. What the binding adds is meaning — a release seeds a source, and a
 *  completion at a sink is delivered to *that partner's* connector rather than
 *  only to whichever one released the order.
 */

const inputStyle: React.CSSProperties = {
  background: color.bgInput, border: `1px solid ${color.border}`, borderRadius: size.radius,
  color: color.textPrimary, padding: `${size.sp2} ${size.sp3}`, fontSize: 13, outline: 'none',
  fontFamily: font.sans,
}

export function IntegrationMark({ providerId, size: px = 26 }: { providerId: string; size?: number }) {
  const p = integrationProvider(providerId)
  if (!p) return null
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: px, height: px, borderRadius: Math.max(4, px * 0.22),
      background: p.color, color: p.ink, fontWeight: 700,
      fontSize: px * (p.mark.length > 1 ? 0.42 : 0.56),
      fontFamily: font.sans, flexShrink: 0, letterSpacing: p.mark.length > 1 ? '-0.02em' : 0,
    }}>{p.mark}</span>
  )
}

export default function IntegrationLocations() {
  const stations   = useStationsStore((s) => s.stations)
  const create     = useStationsStore((s) => s.create)
  const remove     = useStationsStore((s) => s.remove)
  const mapConfig  = useMapSettingsStore((s) => s.settings)

  const [providerId, setProviderId] = useState(INTEGRATION_PROVIDERS[0].id)
  const provider = integrationProvider(providerId)!
  const [role, setRole] = useState<IntegrationRole>(provider.defaultRole)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err,  setErr]  = useState('')

  const roles = useMemo(() => allowedRoles(providerId), [providerId])

  const bound = useMemo(
    () => Object.values(stations).filter(isIntegrationStation)
            .sort((a, b) => a.name.localeCompare(b.name)),
    [stations])

  const pickProvider = (id: string) => {
    setProviderId(id)
    const p = integrationProvider(id)
    if (p) setRole(p.defaultRole)
  }

  /** A first position that is out of the way but obviously connected: sources
   *  to the left of the line, sinks to the right, stacked so two of them never
   *  land on top of each other. The user drags it where it really belongs. */
  const placement = (forRole: IntegrationRole) => {
    const work = Object.values(stations).filter((s) => !isIntegrationStation(s))
    const nodeSize = (mapConfig?.stationSizeUnits ?? 1) * (mapConfig?.pixelsPerUnit ?? 100)
    const gap = nodeSize * 1.7
    if (work.length === 0) return { x: 0, y: 0, width: nodeSize, height: nodeSize }
    const xs = work.map((s) => s.position.x), ys = work.map((s) => s.position.y)
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const midY = (Math.min(...ys) + Math.max(...ys)) / 2
    const onRight = forRole === 'sink'
    const sameSide = bound.filter((s) => (s.integrationRole === 'sink') === onRight).length
    return {
      x: onRight ? maxX + gap : minX - gap,
      y: midY + sameSide * nodeSize * 1.35,
      width: nodeSize, height: nodeSize,
    }
  }

  const add = async () => {
    setErr(''); setBusy(true)
    try {
      await create({
        name: name.trim() || defaultName(provider.label, role),
        description: '', adapterType: null, adapterConfig: {},
        color: null, icon: null,
        integrationProvider: providerId,
        integrationRole: role,
        position: placement(role),
      })
      setName('')
    } catch (e) {
      setErr(String((e as Error)?.message ?? e))
    } finally { setBusy(false) }
  }

  return (
    <div>
      <p style={{ fontSize: 12, color: color.textDim, margin: `0 0 ${size.sp4}`, lineHeight: 1.6, maxWidth: 640 }}>
        A location bound to a partner marks where work <b style={{ color: color.textSecondary }}>enters or
        leaves the business</b>. Add one, drag it where it belongs, then draw a link between it and the
        location it exchanges with. <b style={{ color: color.textSecondary }}>Cards never sit on a
        partner&rsquo;s node.</b> A link <i>from</i> an ERP points at the location where the product it
        orders is <i>made</i> — an order there starts a pull, and the pull orders every precursor
        down to the material queues by itself. (A line can have many places material enters but only
        one finished product, which is why the link follows the product, not the material.) A link
        <i>to</i> a partner is a handoff: the finished lot waits at your own location until someone
        sends it. Because these links carry no material they are ignored by merges, splits, pulls and
        the cycle check — and bound locations stay out of the heatmap, OEE and takt.
      </p>

      {bound.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2, marginBottom: size.sp5 }}>
          {bound.map((s) => (
            <div key={s._id} style={{
              display: 'flex', alignItems: 'center', gap: size.sp3,
              background: color.bgCard, border: `1px solid ${color.border}`,
              borderRadius: size.radius, padding: `${size.sp2} ${size.sp3}`,
            }}>
              <IntegrationMark providerId={s.integrationProvider!} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: color.textPrimary }}>{s.name}</div>
                <div style={{ fontSize: 11, color: color.textDim }}>
                  {integrationProvider(s.integrationProvider)?.label} · {roleLabel(s.integrationRole)}
                </div>
              </div>
              <button
                onClick={() => { if (confirm(`Remove “${s.name}” from the map? Routes to and from it go too.`)) remove(s._id) }}
                style={{ background: 'transparent', border: `1px solid ${color.border}`,
                         borderRadius: size.radius, color: color.textSecondary,
                         padding: `4px ${size.sp3}`, fontSize: 12, cursor: 'pointer' }}>
                Remove
              </button>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: size.sp3, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 10, color: color.textDim, fontFamily: font.mono, letterSpacing: '0.08em' }}>PARTNER</span>
          <select value={providerId} onChange={(e) => pickProvider(e.target.value)} style={inputStyle}>
            {INTEGRATION_PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 10, color: color.textDim, fontFamily: font.mono, letterSpacing: '0.08em' }}>ROLE</span>
          <select value={role} onChange={(e) => setRole(e.target.value as IntegrationRole)}
                  style={inputStyle} disabled={roles.length === 1}>
            {roles.map((r) => (
              <option key={r} value={r}>
                {r === 'source' ? 'Raises demand here'
                 : r === 'sink' ? 'Finished goods leave here'
                 : 'Both'}
              </option>
            ))}
          </select>
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 200 }}>
          <span style={{ fontSize: 10, color: color.textDim, fontFamily: font.mono, letterSpacing: '0.08em' }}>NAME ON THE MAP</span>
          <input value={name} onChange={(e) => setName(e.target.value)}
                 placeholder={defaultName(provider.label, role)} style={inputStyle} />
        </label>

        <button onClick={add} disabled={busy} style={{
          background: color.bluePrimary, color: color.white, border: 'none',
          borderRadius: size.radius, padding: `${size.sp2} ${size.sp5}`,
          fontSize: 13, fontWeight: 600, cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1,
        }}>
          {busy ? 'Adding…' : 'Add to map'}
        </button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: size.sp2, marginTop: size.sp3 }}>
        <IntegrationMark providerId={providerId} size={20} />
        <span style={{ fontSize: 11.5, color: color.textDim }}>{provider.blurb}</span>
      </div>

      {err && <div style={{ color: color.statusFault, fontSize: 12, marginTop: size.sp2 }}>{err}</div>}
    </div>
  )
}

function defaultName(label: string, role: IntegrationRole): string {
  return role === 'sink' ? `${label} Shipping`
       : role === 'source' ? `${label} Goods In`
       : label
}
