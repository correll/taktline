import React, { useState } from 'react'
import { useStationsStore } from '../../store'
import { STATION_ICONS } from './StationNode'
import { color } from '../../theme/tokens'

const LOT_COLORS = ['#F0997B', '#639922', '#EF9F27', '#8B5CF6', '#E24B4A', '#06B6D4', '#F97316', '#EC4899']

/** Compact edit modal reached from the map's right-click context menu. */
export default function MapStationEditModal({ stationId, onClose }: { stationId: string; onClose: () => void }) {
  const station       = useStationsStore((s) => s.stations[stationId])
  const updateStation = useStationsStore((s) => s.update)
  const [name, setName] = useState(station?.name ?? '')
  const [icon, setIcon] = useState<string | null>(station?.icon ?? null)
  const [col,  setCol]  = useState<string | null>(station?.color ?? null)
  const [storage, setStorage] = useState<boolean>(station?.isStorage ?? false)
  const [saving, setSaving] = useState(false)
  if (!station) return null

  const save = async () => {
    if (!name.trim()) return
    setSaving(true)
    try { await updateStation(stationId, { name: name.trim(), icon, color: col, isStorage: storage }); onClose() }
    finally { setSaving(false) }
  }

  return (
    <div onPointerDown={onClose} style={{ position: 'absolute', inset: 0, zIndex: 80,
      background: color.backdrop, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div className="tk-modal-card" onPointerDown={(e) => e.stopPropagation()} style={{ background: color.bgPanel,
        border: `1px solid ${color.border}`, borderRadius: 8, padding: 20, width: 360,
        display: 'flex', flexDirection: 'column', gap: 14, boxShadow: 'var(--tk-shadow-lg)' }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>Edit location</div>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={LABEL}>NAME</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus style={INPUT}
                 onFocus={(e) => e.target.select()}
                 onKeyDown={(e) => { if (e.key === 'Enter') save() }} />
        </label>

        {/* Storage is declared, not inferred. A final test bench is a leaf too,
            and hiding it from the heatmap loses the queue that matters most. */}
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer' }}>
          <input type="checkbox" checked={storage} onChange={(e) => setStorage(e.target.checked)}
                 style={{ marginTop: 2, width: 15, height: 15, flexShrink: 0, cursor: 'pointer' }} />
          <span style={{ fontSize: 11.5, color: color.textDim, lineHeight: 1.5 }}>
            <b style={{ color: color.textSecondary }}>Storage, not work</b> — finished goods rest
            here by design. Kept out of the heatmap (which it would otherwise flatten), reports no
            OEE or cycle time, and never flagged for accumulating. Leave this off for anywhere work
            actually happens, including the last location on a line.
          </span>
        </label>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <span style={LABEL}>ICON</span>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(9, 1fr)', gap: 5 }}>
            {STATION_ICONS.map(({ id, Icon, label }) => (
              <button key={id} title={label} onClick={() => setIcon(id)} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 6, borderRadius: 5,
                cursor: 'pointer', background: icon === id ? '#D85A3033' : 'transparent',
                border: `1px solid ${icon === id ? '#D85A30' : color.border}` }}>
                <Icon size={16} color={col ?? color.textSecondary} />
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <span style={LABEL}>COLOR</span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button onClick={() => setCol(null)} title="Default" style={{ width: 22, height: 22, borderRadius: 5,
              cursor: 'pointer', background: 'transparent', border: `1px solid ${col === null ? color.textPrimary : color.border}` }} />
            {LOT_COLORS.map((c) => (
              <button key={c} onClick={() => setCol(c)} style={{ width: 22, height: 22, borderRadius: 5,
                cursor: 'pointer', background: c, border: `2px solid ${col === c ? color.textPrimary : 'transparent'}` }} />
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button onClick={onClose} style={BTN_SEC}>Cancel</button>
          <button onClick={save} disabled={saving || !name.trim()} style={BTN_PRIMARY(saving || !name.trim())}>Save</button>
        </div>
      </div>
    </div>
  )
}

const LABEL: React.CSSProperties = { fontSize: 10, color: color.textSecondary, fontFamily: 'JetBrains Mono, monospace', letterSpacing: '0.08em' }
const INPUT: React.CSSProperties = { background: color.bgInput, border: `1px solid ${color.border}`, borderRadius: 4, color: color.textPrimary, padding: '6px 10px', fontSize: 13, outline: 'none' }
const BTN_SEC: React.CSSProperties = { padding: '6px 14px', background: 'transparent', border: `1px solid ${color.border}`, borderRadius: 4, color: color.textSecondary, cursor: 'pointer', fontSize: 12 }
const BTN_PRIMARY = (d: boolean): React.CSSProperties => ({ padding: '6px 14px', background: d ? '#993C1D30' : '#D85A30', border: 'none', borderRadius: 4, color: d ? color.textDim : '#fff', cursor: d ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 600 })
