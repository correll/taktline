import React, { useState, useEffect, useMemo } from 'react'
import { useProcessesStore, useCardsStore, useStationsStore } from '../../store'
import { mergeApi, type MergePreview } from '../../api/merge.api'
import { color, font, size, shadow } from '../../theme/tokens'
import { lotLabel } from './LotCard'

const PURPLE = '#8B5CF6'

interface Props {
  stationId: string
  onClose:   () => void
  onMerged?: () => void
}

/** Manual merge: pick the precursor lot cards to consume, grouped by feeding
 * branch, or press AUTO to let the system pick. */
export default function MergeLotModal({ stationId, onClose, onMerged }: Props) {
  const templates = useProcessesStore((s) => s.lotTemplates)
  const routes    = useProcessesStore((s) => s.routes)
  const stations  = useStationsStore((s) => s.stations)
  const cards     = useCardsStore((s) => s.cards)
  const fetchAll  = useCardsStore((s) => s.fetchAll)
  const fetchProcesses = useProcessesStore((s) => s.fetchAll)

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [preview,  setPreview]  = useState<MergePreview | null>(null)
  const [merging,  setMerging]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  useEffect(() => {
    mergeApi.preview(stationId).then(setPreview).catch(() => {})
  }, [stationId])

  const station = stations[stationId]

  // One group per feeding branch: the route's source station + the candidate
  // cards here whose template originates at that source.
  const branches = useMemo(() => {
    const incoming = Object.values(routes).filter((r) => r.unload === stationId)
    return incoming.map((r) => {
      const source = stations[r.load]
      const candidates = Object.values(cards).filter((c) => {
        if ((c.bins[stationId]?.count ?? 0) <= 0) return false
        return templates[c.lotTemplateId]?.startStationId === r.load
      })
      return { route: r, source, candidates, need: Math.max(1, r.quantity) }
    })
  }, [routes, stations, cards, templates, stationId])

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const selectedUnits = (branch: { candidates: { _id: string; bins: Record<string, { count: number }> }[] }) =>
    branch.candidates.reduce((sum, c) => sum + (selected.has(c._id) ? (c.bins[stationId]?.count ?? 0) : 0), 0)

  // How many assemblies the current selection can build (0 = incomplete recipe).
  const selectionCanMake = branches.length
    ? Math.min(...branches.map((b) => Math.floor(selectedUnits(b) / b.need)))
    : 0

  const doMerge = async (auto: boolean) => {
    setMerging(true)
    setError(null)
    try {
      await mergeApi.perform(stationId, auto ? undefined : [...selected])
      await Promise.all([fetchAll(), fetchProcesses()])
      onMerged?.()
      onClose()
    } catch (e) {
      setError(String(e))
      setMerging(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(10, 9, 8, 0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="tk-modal-card" style={{
        background: color.bgPanel, border: `1px solid ${color.border}`,
        borderRadius: size.radiusMd, padding: size.sp6, width: 420,
        maxHeight: '80vh', overflowY: 'auto',
        boxShadow: shadow.lg, display: 'flex', flexDirection: 'column', gap: size.sp4,
      }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>
          Merge — <span style={{ color: color.textSecondary }}>{station?.name ?? stationId}</span>
        </div>

        {preview && preview.requirements.length > 0 && (
          <div style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono }}>
            1 assembly needs {preview.requirements
              .map((r) => `${r.requiredPerAssembly} × ${stations[r.sourceStationId]?.name ?? '?'}`)
              .join('  +  ')}
          </div>
        )}

        {/* One selectable group per feeding branch */}
        {branches.map(({ route, source, candidates, need }) => {
          const got = candidates.reduce((sum, c) => sum + (selected.has(c._id) ? (c.bins[stationId]?.count ?? 0) : 0), 0)
          const ok  = got >= need
          return (
            <div key={route._id}>
              <div style={{
                display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                marginBottom: size.sp1,
              }}>
                <span style={{ fontSize: 10, fontFamily: font.mono, letterSpacing: '0.08em', color: color.textDim }}>
                  FROM {(source?.name ?? '?').toUpperCase()}
                </span>
                <span style={{ fontSize: 10, fontFamily: font.mono, color: ok ? '#639922' : color.textDim }}>
                  {got}/{need}× selected
                </span>
              </div>
              {candidates.length === 0 ? (
                <div style={{ fontSize: 11, color: color.textDim, fontStyle: 'italic', padding: '4px 0' }}>
                  No lots from {source?.name ?? 'this branch'} here yet.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
                  {candidates.map((c) => {
                    const tmpl  = templates[c.lotTemplateId]
                    const count = c.bins[stationId]?.count ?? 0
                    const isSel = selected.has(c._id)
                    return (
                      <div
                        key={c._id}
                        data-testid="merge-candidate"
                        onClick={() => toggle(c._id)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: size.sp2,
                          background: isSel ? `${PURPLE}15` : color.bgCard,
                          border: `1px solid ${isSel ? `${PURPLE}80` : color.border}`,
                          borderLeft: `3px solid ${tmpl?.color ?? PURPLE}`,
                          borderRadius: size.radius, padding: `${size.sp2} ${size.sp3}`,
                          cursor: 'pointer', transition: 'border-color 0.12s, background 0.12s',
                        }}
                      >
                        <div style={{
                          width: 15, height: 15, borderRadius: '50%', flexShrink: 0,
                          border: `2px solid ${isSel ? PURPLE : color.border}`,
                          background: isSel ? PURPLE : 'transparent',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          color: '#fff', fontSize: 9, fontWeight: 700,
                        }}>
                          {isSel ? '✓' : ''}
                        </div>
                        <span style={{ flex: 1, fontSize: 12, color: color.textPrimary, fontWeight: 600 }}>
                          {tmpl?.name ?? 'Lot'}
                          <span style={{ color: color.textSecondary, fontFamily: font.mono, fontWeight: 400 }}> {lotLabel(c)}</span>
                        </span>
                        <span style={{ fontSize: 12, fontFamily: font.mono, fontWeight: 700, color: color.textPrimary }}>
                          {count}
                          <span style={{ fontSize: 9, color: color.textDim, fontWeight: 400 }}> u</span>
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}

        {error && (
          <div style={{
            background: '#E24B4A18', border: '1px solid #E24B4A40',
            borderRadius: size.radius, padding: `${size.sp2} ${size.sp3}`,
            fontSize: 11, color: '#E24B4A',
          }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: size.sp2 }}>
          <button onClick={onClose} style={{
            background: 'transparent', border: `1px solid ${color.border}`,
            borderRadius: size.radius, color: color.textSecondary,
            padding: '7px 14px', fontSize: 12, cursor: 'pointer',
          }}>
            Cancel
          </button>
          <button
            onClick={() => doMerge(true)}
            disabled={merging}
            title="Merge automatically from any available precursors"
            style={{
              marginLeft: 'auto',
              background: 'transparent', border: `1px solid ${PURPLE}60`,
              borderRadius: size.radius, color: PURPLE,
              padding: '7px 14px', fontSize: 12, fontFamily: font.mono, fontWeight: 700,
              cursor: merging ? 'not-allowed' : 'pointer',
            }}
          >
            AUTO
          </button>
          <button
            onClick={() => doMerge(false)}
            disabled={merging || selectionCanMake < 1}
            title={selectionCanMake < 1 ? 'Select enough lots from every branch first' : undefined}
            style={{
              background: merging || selectionCanMake < 1 ? `${PURPLE}30` : PURPLE,
              border: 'none', borderRadius: size.radius, color: '#fff',
              padding: '7px 16px', fontSize: 12, fontFamily: font.mono, fontWeight: 700,
              cursor: merging || selectionCanMake < 1 ? 'not-allowed' : 'pointer',
            }}
          >
            {merging ? 'MERGING…' : `MERGE${selectionCanMake > 0 ? ` ${selectionCanMake}×` : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}
