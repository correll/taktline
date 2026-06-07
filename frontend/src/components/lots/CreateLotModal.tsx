import React, { useState, useMemo } from 'react'
import { useProcessesStore, useCardsStore, useStationsStore } from '../../store'
import { mergeApi, type PullSourceInfo } from '../../api/merge.api'
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
  const fetchCards  = useCardsStore((s) => s.fetchAll)

  // Merge station = ≥2 incoming routes
  const isMergeStation = useMemo(
    () => Object.values(routes).filter((r) => r.unload === stationId).length >= 2,
    [routes, stationId],
  )

  const validTemplates = useMemo(
    () => Object.values(templates).filter((t) => t.startStationId === stationId),
    [templates, stationId],
  )

  const [templateId, setTemplateId]   = useState(() => {
    const valid = Object.values(templates).filter((t) => t.startStationId === stationId)
    return valid.length === 1 ? valid[0]._id : ''
  })
  const [quantity, setQuantity]       = useState(1)
  const [lotNum, setLotNum]           = useState('')
  const [saving, setSaving]           = useState(false)
  const [error, setError]             = useState<string | null>(null)
  const [pullResult, setPullResult]   = useState<PullSourceInfo[] | null>(null)

  const station = stations[stationId]

  const handleCreate = async () => {
    if (!templateId) { setError('Select a template'); return }
    setSaving(true)
    setError(null)
    try {
      if (isMergeStation) {
        // Pull precursor lots from upstream source stations
        const result = await mergeApi.pull(stationId, quantity)
        await fetchCards()
        setPullResult(result.sources)
      } else {
        const tmpl = templates[templateId]
        if (!tmpl) return
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
      }
    } catch (e) {
      setError(String(e))
    } finally {
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
          {isMergeStation ? 'Pull Precursors' : 'Create Lot'} —{' '}
          <span style={{ color: color.textSecondary }}>{station?.name ?? stationId}</span>
        </div>

        {/* Pull confirmation screen */}
        {pullResult ? (
          <>
            <div style={{ fontSize: 12, color: color.textSecondary, lineHeight: 1.6 }}>
              Created precursor lots at:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {pullResult.map((s) => (
                <div key={s.stationId} style={{
                  background: '#0A1628', border: `1px solid ${color.border}`,
                  borderRadius: 4, padding: '6px 10px', fontSize: 12,
                }}>
                  <span style={{ color: color.textPrimary, fontWeight: 600 }}>{s.quantity}×</span>
                  {' '}<span style={{ color: color.textSecondary }}>{s.templateName}</span>
                  {' '}at <span style={{ color: color.textPrimary }}>{s.stationName}</span>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button onClick={onClose} style={primaryBtn(false)}>Done</button>
            </div>
          </>
        ) : (
          <>
            {/* Merge station: pull info banner */}
            {isMergeStation && (
              <div style={{
                background: '#1A0E3A', border: '1px solid #6D3AED',
                borderRadius: 4, padding: '8px 10px', fontSize: 11,
                color: '#C4B5FD', lineHeight: 1.5,
              }}>
                This is a merge station. Creating lots here will pull precursor
                lots from all upstream source queues.
              </div>
            )}

            {/* Template selector — hidden for merge stations (pull uses all upstream templates) */}
            {!isMergeStation && (
              <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
                <span style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>
                  TEMPLATE
                </span>
                <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} style={inputStyle}>
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
            )}

            {/* Quantity */}
            <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
              <span style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>
                {isMergeStation ? 'ASSEMBLIES TO PULL' : 'QUANTITY'}
              </span>
              <input
                type="number"
                min={1}
                value={quantity}
                onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value, 10) || 1))}
                style={inputStyle}
              />
            </label>

            {/* Lot number — only for direct creation */}
            {!isMergeStation && (
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
            )}

            {error && (
              <div style={{ fontSize: 11, color: color.statusFault }}>{error}</div>
            )}

            <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end' }}>
              <button onClick={onClose} style={secondaryBtn}>Cancel</button>
              <button
                onClick={handleCreate}
                disabled={saving || (!isMergeStation && !templateId)}
                style={primaryBtn(saving || (!isMergeStation && !templateId))}
              >
                {saving ? (isMergeStation ? 'Pulling…' : 'Creating…')
                        : (isMergeStation ? `Pull ${quantity}` : 'Create Lot')}
              </button>
            </div>
          </>
        )}
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
