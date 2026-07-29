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
  const fetchProcesses = useProcessesStore((s) => s.fetchAll)
  const createTemplate = useProcessesStore((s) => s.createTemplate)

  // Any station with upstream routes is a "pull" station: creating a lot here
  // pulls precursors from the source queues (cascading back to raw materials).
  // Only true source queues (no incoming routes) create lots directly.
  const isPullStation = useMemo(
    () => Object.values(routes).some((r) => r.unload === stationId),
    [routes, stationId],
  )

  // A station that still feeds something downstream is an *intermediate* node —
  // not the end of the line. Pulling here builds work-in-process that then has
  // to travel further; the recommended pull point is the finished-goods leaf.
  // Only PRODUCTION routes count as downstream: a handoff link to a shipper is
  // the end of the line, not a further step.
  const isIntermediate = useMemo(
    () => isPullStation && Object.values(routes).some((r) => {
      const target = stations[r.unload]
      return r.load === stationId && !(target && target.integrationProvider)
    }),
    [isPullStation, routes, stations, stationId],
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
    // A template is only *required* when this source already has some to choose
    // from; with none, we create a default one on the fly. Pulling never needs one.
    if (!isPullStation && validTemplates.length > 0 && !templateId) { setError('Select a template'); return }
    setSaving(true)
    setError(null)
    try {
      if (isPullStation) {
        // Pull precursor lots from the upstream source queues (cascades to leaves).
        // Refetch templates too — the pull auto-provisions source templates
        // server-side; without them lots would display as "Unknown".
        const result = await mergeApi.pull(stationId, quantity)
        await Promise.all([fetchCards(), fetchProcesses()])
        setPullResult(result.sources)
      } else {
        let tid = templateId
        let procId = tid ? (templates[tid]?.processId ?? null) : null
        if (!tid) {
          // No template here yet — provision a sensible default for this station.
          const near = Object.values(routes).find((r) => r.load === stationId || r.unload === stationId)
          const t = await createTemplate({ name: station?.name || 'Lot', startStationId: stationId, processId: near?.processId ?? null })
          tid = t._id
          procId = t.processId
        }
        await createCard({
          lotTemplateId: tid,
          processId:     procId ?? '',
          lotNum:        lotNum.trim() || null,   // null → backend generates a code
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
        background:     color.backdrop,
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        zIndex:         1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="tk-modal-card" style={{
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
          {isPullStation ? 'Pull Precursors' : 'Create Lot'} —{' '}
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
            {isPullStation && (
              <div style={{
                background: '#1A0E3A', border: '1px solid #6D3AED',
                borderRadius: 4, padding: '8px 10px', fontSize: 11,
                color: '#C4B5FD', lineHeight: 1.5,
              }}>
                Lots here are <b>pulled</b>, not created directly. This seeds
                precursor lots in the source queues that feed this station —
                cascading all the way back to raw materials. No template needed.
              </div>
            )}

            {/* WIP warning for intermediate (non-end-of-line) pull points */}
            {isIntermediate && (
              <div style={{
                background: '#3A1E0A', border: '1px solid #C2660A',
                borderRadius: 4, padding: '8px 10px', fontSize: 11,
                color: '#FBBF77', lineHeight: 1.5,
              }}>
                ⚠ Note that creating intermediate products creates excessive
                Work-in-Process. Unless intermediate assemblies are also products,
                you should create work orders by pulling from the <b>end of the line</b>.
              </div>
            )}

            {/* Template selector — shown only when this source has templates to choose. */}
            {!isPullStation && validTemplates.length > 0 && (
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
              </label>
            )}
            {!isPullStation && validTemplates.length === 0 && (
              <div style={{ fontSize: 11, color: color.textSecondary, background: '#0A1628',
                            border: `1px solid ${color.border}`, borderRadius: 4, padding: '8px 10px', lineHeight: 1.5 }}>
                A default lot card will be created for <b style={{ color: color.textPrimary }}>{station?.name}</b>.
                Add a template in Settings → Templates if you want custom fields.
              </div>
            )}

            {/* Quantity */}
            <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
              <span style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>
                {isPullStation ? 'UNITS TO PULL' : 'QUANTITY'}
              </span>
              <input
                type="number"
                min={1}
                value={quantity}
                onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value, 10) || 1))}
                style={inputStyle}
              />
            </label>

            {/* Lot code — only for direct creation */}
            {!isPullStation && (
              <label style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
                <span style={{ fontSize: 10, color: color.textSecondary, fontFamily: font.mono, letterSpacing: '0.08em' }}>
                  LOT CODE (OPTIONAL)
                </span>
                <input
                  type="text"
                  maxLength={24}
                  placeholder="auto-generated if blank, e.g. E4096A"
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
                disabled={saving || (!isPullStation && validTemplates.length > 0 && !templateId)}
                style={primaryBtn(saving || (!isPullStation && validTemplates.length > 0 && !templateId))}
              >
                {saving ? (isPullStation ? 'Pulling…' : 'Creating…')
                        : (isPullStation ? `Pull ${quantity}` : 'Create Lot')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  background:   color.bgInput,
  border:       `1px solid ${color.border}`,
  borderRadius: '4px',
  color:        color.textPrimary,
  padding:      '6px 10px',
  fontSize:     13,
  outline:      'none',
  width:        '100%',
}

const secondaryBtn: React.CSSProperties = {
  padding:      '6px 16px',
  background:   'transparent',
  border:       `1px solid ${color.border}`,
  borderRadius: '4px',
  color:        color.textSecondary,
  cursor:       'pointer',
  fontSize:     12,
}

const primaryBtn = (disabled: boolean): React.CSSProperties => ({
  padding:      '6px 16px',
  background:   disabled ? '#993C1D30' : '#D85A30',
  border:       'none',
  borderRadius: '4px',
  color:        disabled ? color.textDim : '#fff',
  cursor:       disabled ? 'not-allowed' : 'pointer',
  fontSize:     12,
  fontWeight:   600,
})
