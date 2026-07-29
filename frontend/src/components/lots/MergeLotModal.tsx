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
  const stations  = useStationsStore((s) => s.stations)
  const cards     = useCardsStore((s) => s.cards)
  const fetchAll  = useCardsStore((s) => s.fetchAll)
  const fetchProcesses = useProcessesStore((s) => s.fetchAll)

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [preview,  setPreview]  = useState<MergePreview | null>(null)
  const [merging,  setMerging]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)
  // Which line is being assembled, when several merge at this bench.
  const [procId,   setProcId]   = useState<string | null>(null)

  useEffect(() => {
    mergeApi.preview(stationId, procId ?? undefined).then((p) => {
      setPreview(p)
      setProcId((cur) => cur ?? p.processId)
      // Open on the merge this station would perform on its own, rather than
      // an empty form: the worker reads a proposal and adjusts it, instead of
      // choosing between a blind AUTO and rebuilding the recipe by hand.
      setSelected(new Set(p.requirements.flatMap((r) => r.proposedCardIds)))
    }).catch(() => {})
  }, [stationId, procId])

  const station = stations[stationId]

  // One group per feeding branch, straight from the preview — which is the
  // authority on what this merge consumes. Deriving the branches from the raw
  // route list instead showed every process's feeds at once (each source twice
  // on a two-chemistry bench) and a group for the ERP's demand link, which
  // hands this station nothing: "no lots from Odoo here yet", forever.
  const branches = useMemo(() => {
    if (!preview) return []
    return preview.requirements.map((req) => {
      const allowed = new Set(req.precursorTemplateIds)
      const candidates = Object.values(cards).filter((c) =>
        (c.bins[stationId]?.count ?? 0) > 0 && allowed.has(c.lotTemplateId))
      return {
        key:    req.routeId,
        source: stations[req.sourceStationId],
        candidates,
        need:   Math.max(1, req.requiredPerAssembly),
      }
    })
  }, [preview, cards, stations, stationId])

  const proposedIds = useMemo(
    () => (preview?.requirements ?? []).flatMap((r) => r.proposedCardIds),
    [preview])
  const atProposal = proposedIds.length === selected.size
    && proposedIds.every((id) => selected.has(id))
  const resetToProposal = () => setSelected(new Set(proposedIds))

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

  // Always the worker's selection — which opens as the proposal, so pressing
  // MERGE unchanged does exactly what the old AUTO did.
  const doMerge = async () => {
    setMerging(true)
    setError(null)
    try {
      await mergeApi.perform(stationId, [...selected], procId ?? undefined)
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

        {/* Which line is being assembled. A shared bench holds one recipe per
            process, and they are different assemblies — so this is a choice,
            not a detail. Changing it refetches the preview and clears any
            selection made against the other line's groups. */}
        {preview && preview.processes.length > 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp1 }}>
            <span style={{ fontSize: 10, fontFamily: font.mono, letterSpacing: '0.08em', color: color.textDim }}>
              ASSEMBLING
            </span>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {preview.processes.map((p) => (
                <button
                  key={p.id}
                  onClick={() => { setSelected(new Set()); setProcId(p.id) }}
                  style={{
                    flex: 1, minWidth: 90, padding: '7px 10px', borderRadius: 5, cursor: 'pointer',
                    background: preview.processId === p.id ? `${PURPLE}33` : 'transparent',
                    border: `1px solid ${preview.processId === p.id ? PURPLE : color.border}`,
                    color: preview.processId === p.id ? color.textPrimary : color.textSecondary,
                    fontSize: 12.5, fontWeight: 600,
                  }}
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {preview && preview.requirements.length > 0 && (
          <div style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono }}>
            1 {preview.assemblyTemplateName ?? 'assembly'} needs {preview.requirements
              .map((r) => `${r.requiredPerAssembly} × ${stations[r.sourceStationId]?.name ?? '?'}`)
              .join('  +  ')}
          </div>
        )}

        {/* One selectable group per feeding branch */}
        {branches.map(({ key, source, candidates, need }) => {
          const got = candidates.reduce((sum, c) => sum + (selected.has(c._id) ? (c.bins[stationId]?.count ?? 0) : 0), 0)
          const ok  = got >= need
          return (
            <div key={key}>
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
            onClick={resetToProposal}
            disabled={merging || proposedIds.length === 0 || atProposal}
            title="Go back to the lots this station would consume by default"
            style={{
              marginLeft: 'auto',
              background: 'transparent',
              border: `1px solid ${atProposal ? color.border : `${PURPLE}60`}`,
              borderRadius: size.radius,
              color: atProposal ? color.textDim : PURPLE,
              padding: '7px 14px', fontSize: 12, cursor: atProposal ? 'default' : 'pointer',
            }}
          >
            Reset
          </button>
          <button
            onClick={doMerge}
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
