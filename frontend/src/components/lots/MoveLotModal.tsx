import React, { useState, useMemo } from 'react'
import { useStationsStore, useCardsStore, useProcessesStore } from '../../store'
import { color, font, size, shadow } from '../../theme/tokens'
import type { Card } from '../../models'
import { getValidDestinations } from '../../views/lots/LotsView'

interface Props {
  card:      Card
  fromStationId: string
  onClose:   () => void
}

// Remove zero-count bins after moving (mirror optio convention)
function moveLotBins(
  card:        Card,
  fromStation: string,
  toStation:   string,
  qty:         number
): Card['bins'] {
  const bins = { ...card.bins }
  const fromCount = (bins[fromStation]?.count ?? 0) - qty
  if (fromCount <= 0) {
    const { [fromStation]: _removed, ...rest } = bins
    return { ...rest, [toStation]: { count: (bins[toStation]?.count ?? 0) + qty } }
  }
  return {
    ...bins,
    [fromStation]: { count: fromCount },
    [toStation]:   { count: (bins[toStation]?.count ?? 0) + qty },
  }
}

export default function MoveLotModal({ card, fromStationId, onClose }: Props) {
  const stations   = useStationsStore((s) => s.stations)
  const routes     = useProcessesStore((s) => s.routes)
  const updateCard = useCardsStore((s) => s.update)

  const fromCount  = card.bins[fromStationId]?.count ?? 0
  const [toId, setToId]     = useState('')
  const [qty, setQty]       = useState(fromCount)
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState<string | null>(null)

  // Valid destinations: forward path up to the next merge point
  const destinations = useMemo(() => {
    const ids = getValidDestinations(fromStationId, routes)
    return ids.map((id) => stations[id]).filter(Boolean)
  }, [routes, fromStationId, stations])

  const handleMove = async () => {
    if (!toId) { setError('Select a destination'); return }
    if (qty < 1 || qty > fromCount) { setError(`Qty must be 1–${fromCount}`); return }
    setSaving(true)
    setError(null)
    try {
      await updateCard(card._id, { bins: moveLotBins(card, fromStationId, toId, qty), status: 'idle' })
      onClose()
    } catch (e) {
      setError(String(e))
      setSaving(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0,
        background: color.backdrop,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="tk-modal-card" style={{
        background: color.bgPanel, border: `1px solid ${color.border}`,
        borderRadius: size.radiusMd, padding: size.sp6,
        width: 320, boxShadow: shadow.lg,
        display: 'flex', flexDirection: 'column', gap: size.sp4,
      }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>
          Move Lot
        </div>
        <div style={{ fontSize: 12, color: color.textSecondary }}>
          Moving from station <strong style={{ color: color.textPrimary }}>{stations[fromStationId]?.name}</strong>
          {' '}({fromCount} unit{fromCount !== 1 ? 's' : ''} available)
        </div>

        <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
          <span style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>
            DESTINATION
          </span>
          <select value={toId} onChange={(e) => setToId(e.target.value)} style={inputStyle}>
            <option value="">— select station —</option>
            {destinations.map((s) => (
              <option key={s!._id} value={s!._id}>{s!.name}</option>
            ))}
          </select>
          {destinations.length === 0 && (
            <span style={{ fontSize: 10, color: color.statusWarning }}>
              No outgoing routes from this station.
            </span>
          )}
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
          <span style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>
            QUANTITY
          </span>
          <input
            type="number" min={1} max={fromCount} value={qty}
            onChange={(e) => setQty(parseInt(e.target.value, 10) || 1)}
            style={{ ...inputStyle, fontFamily: font.mono }}
          />
        </label>

        {error && <div style={{ fontSize: 11, color: color.statusFault }}>{error}</div>}

        <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={secondaryBtn}>Cancel</button>
          <button
            onClick={handleMove}
            disabled={saving || !toId}
            style={primaryBtn(saving || !toId)}
          >
            {saving ? 'Moving…' : 'Move'}
          </button>
        </div>
      </div>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  background: color.bgInput, border: `1px solid ${color.border}`,
  borderRadius: '4px', color: color.textPrimary,
  padding: '6px 10px', fontSize: 13, outline: 'none', width: '100%',
}
const secondaryBtn: React.CSSProperties = {
  padding: '6px 16px', background: 'transparent',
  border: `1px solid ${color.border}`, borderRadius: '4px',
  color: color.textSecondary, cursor: 'pointer', fontSize: 12,
}
const primaryBtn = (disabled: boolean): React.CSSProperties => ({
  padding: '6px 16px',
  background: disabled ? '#993C1D30' : '#D85A30',
  border: 'none', borderRadius: '4px',
  color: disabled ? color.textDim : '#fff',
  cursor: disabled ? 'not-allowed' : 'pointer',
  fontSize: 12, fontWeight: 600,
})
