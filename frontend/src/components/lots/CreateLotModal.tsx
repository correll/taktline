import React, { useState, useMemo } from 'react'
import { useProcessesStore, useCardsStore, useStationsStore } from '../../store'
import { color, font, size, shadow } from '../../theme/tokens'

interface Props {
  stationId: string
  onClose:   () => void
}

export default function CreateLotModal({ stationId, onClose }: Props) {
  const templates   = useProcessesStore((s) => s.lotTemplates)
  const routes      = useProcessesStore((s) => s.routes)
  const stations    = useStationsStore((s) => s.stations)
  const createCard  = useCardsStore((s) => s.create)

  const [templateId, setTemplateId]   = useState('')
  const [quantity, setQuantity]       = useState(1)
  const [lotNum, setLotNum]           = useState('')
  const [saving, setSaving]           = useState(false)
  const [error, setError]             = useState<string | null>(null)

  // Only templates whose startStationId === this station are valid here.
  // Merge-destination templates (2+ incoming routes) are excluded — they come
  // from merge operations, not direct creation.
  const validTemplates = useMemo(() => {
    return Object.values(templates).filter((t) => t.startStationId === stationId)
  }, [templates, stationId])

  const station = stations[stationId]

  const handleCreate = async () => {
    if (!templateId) { setError('Select a template'); return }
    const tmpl = templates[templateId]
    if (!tmpl) return
    setSaving(true)
    setError(null)
    try {
      await createCard({
        lotTemplateId: templateId,
        processId:     tmpl.processId ?? '',
        lotNum:        lotNum ? parseInt(lotNum, 10) : null,
        totalQuantity: quantity,
        bins:          { [stationId]: { count: quantity } },
        fields:        {},
        flagged:       false,
        description:   '',
        status:        'idle',
      })
      onClose()
    } catch (e) {
      setError(String(e))
      setSaving(false)
    }
  }

  return (
    <div
      style={{
        position:       'fixed',
        inset:          0,
        background:     'rgba(6,14,30,0.75)',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        zIndex:         1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background:   color.bgPanel,
        border:       `1px solid ${color.border}`,
        borderRadius: size.radiusMd,
        padding:      size.sp6,
        width:        360,
        boxShadow:    shadow.lg,
        display:      'flex',
        flexDirection:'column',
        gap:          size.sp4,
      }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>
          Create Lot — <span style={{ color: color.textSecondary }}>{station?.name ?? stationId}</span>
        </div>

        {/* Template selector */}
        <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
          <span style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>
            TEMPLATE
          </span>
          <select
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
            style={inputStyle}
          >
            <option value="">— select —</option>
            {validTemplates.map((t) => (
              <option key={t._id} value={t._id}>{t.name}</option>
            ))}
          </select>
          {validTemplates.length === 0 && (
            <span style={{ fontSize: 10, color: color.statusWarning }}>
              No templates start at this location. Configure templates in Settings.
            </span>
          )}
        </label>

        {/* Quantity */}
        <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
          <span style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>
            QUANTITY
          </span>
          <input
            type="number"
            min={1}
            value={quantity}
            onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value, 10) || 1))}
            style={inputStyle}
          />
        </label>

        {/* Lot number (optional) */}
        <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
          <span style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>
            LOT NUMBER (OPTIONAL)
          </span>
          <input
            type="text"
            placeholder="auto-assigned if blank"
            value={lotNum}
            onChange={(e) => setLotNum(e.target.value)}
            style={{ ...inputStyle, fontFamily: font.mono }}
          />
        </label>

        {error && (
          <div style={{ fontSize: 11, color: color.statusFault }}>{error}</div>
        )}

        <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={secondaryBtn}>Cancel</button>
          <button
            onClick={handleCreate}
            disabled={saving || !templateId}
            style={primaryBtn(saving || !templateId)}
          >
            {saving ? 'Creating…' : 'Create Lot'}
          </button>
        </div>
      </div>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  background:   '#0D1B2E',
  border:       '1px solid #1E3A5F',
  borderRadius: '4px',
  color:        '#EBF1F8',
  padding:      '6px 10px',
  fontSize:     13,
  outline:      'none',
  width:        '100%',
}

const secondaryBtn: React.CSSProperties = {
  padding:      '6px 16px',
  background:   'transparent',
  border:       '1px solid #1E3A5F',
  borderRadius: '4px',
  color:        '#8FA3BC',
  cursor:       'pointer',
  fontSize:     12,
}

const primaryBtn = (disabled: boolean): React.CSSProperties => ({
  padding:      '6px 16px',
  background:   disabled ? '#1D4ED830' : '#2563EB',
  border:       'none',
  borderRadius: '4px',
  color:        disabled ? '#4A6080' : '#fff',
  cursor:       disabled ? 'not-allowed' : 'pointer',
  fontSize:     12,
  fontWeight:   600,
})
