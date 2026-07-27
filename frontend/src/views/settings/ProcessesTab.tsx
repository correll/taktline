import React, { useState, useMemo, useEffect, useRef } from 'react'
import { useProcessesStore, useStationsStore } from '../../store'
import { color, font, size } from '../../theme/tokens'
import type { Process, Route } from '../../models'
import { Modal, FieldLabel, inputStyle, primaryBtn, secondaryBtn, dangerBtn, ErrorMsg, ListRow } from './shared'
import { wouldCreateCycle } from '../../domain/graph'

// ─── Process list tab ─────────────────────────────────────────────────────────

export default function ProcessesTab() {
  const processes      = useProcessesStore((s) => s.processes)
  const routes         = useProcessesStore((s) => s.routes)
  const createProcess  = useProcessesStore((s) => s.createProcess)
  const updateProcess  = useProcessesStore((s) => s.updateProcess)
  const deleteProcess  = useProcessesStore((s) => s.deleteProcess)

  const [editTarget, setEditTarget]         = useState<Process | null>(null)
  const [creating, setCreating]             = useState(false)
  const [name, setName]                     = useState('')
  const [description, setDescription]       = useState('')
  const [saving, setSaving]                 = useState(false)
  const [error, setError]                   = useState<string | null>(null)
  const [routeEditor, setRouteEditor]       = useState<Process | null>(null)
  const [confirmDelete, setConfirmDelete]   = useState<Process | null>(null)

  const openCreate = () => { setName(''); setDescription(''); setCreating(true); setError(null) }
  const openEdit   = (p: Process) => { setName(p.name); setDescription(p.description); setEditTarget(p); setError(null) }
  const closeModal = () => { setCreating(false); setEditTarget(null) }

  const handleSave = async () => {
    if (!name.trim()) { setError('Name is required'); return }
    setSaving(true); setError(null)
    try {
      if (editTarget) {
        await updateProcess(editTarget._id, { name: name.trim(), description: description.trim() })
      } else {
        await createProcess({ name: name.trim(), description: description.trim() })
      }
      closeModal()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (p: Process) => {
    await deleteProcess(p._id)
    setConfirmDelete(null)
  }

  const routeCountByProcess = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const r of Object.values(routes)) {
      counts[r.processId] = (counts[r.processId] ?? 0) + 1
    }
    return counts
  }, [routes])

  const list = Object.values(processes).sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{
        padding: `${size.sp3} ${size.sp6}`,
        borderBottom: `1px solid ${color.border}`,
        display: 'flex', alignItems: 'center', flexShrink: 0,
      }}>
        <span style={{ flex: 1, fontSize: 11, color: color.textDim }}>
          {list.length} process{list.length !== 1 ? 'es' : ''}
        </span>
        <button data-tour="add-process" onClick={openCreate} style={primaryBtn()}>+ Add Process</button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {list.length === 0 ? (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: 200, color: color.textDim, fontSize: 12, fontFamily: font.mono, letterSpacing: '0.08em',
          }}>
            NO PROCESSES — ADD ONE ABOVE
          </div>
        ) : (
          list.map((p) => (
            <div key={p._id} style={{ borderBottom: `1px solid ${color.border}` }}>
              <div style={{ display: 'flex', alignItems: 'center', padding: `${size.sp3} ${size.sp4}`, gap: size.sp3 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: color.textPrimary, fontWeight: 500 }}>{p.name}</div>
                  {p.description && (
                    <div style={{ fontSize: 11, color: color.textDim, marginTop: 2 }}>{p.description}</div>
                  )}
                </div>
                <span style={{
                  fontSize: 10, fontFamily: font.mono, color: color.textSecondary,
                  background: color.bgElevated, border: `1px solid ${color.border}`,
                  borderRadius: size.radiusFull, padding: '1px 8px',
                }}>
                  {routeCountByProcess[p._id] ?? 0} routes
                </span>
                <button
                  data-tour="process-routes"
                  onClick={() => setRouteEditor(p)}
                  style={{
                    background: 'none', border: `1px solid ${color.borderActive}50`,
                    borderRadius: size.radius, color: color.blueBright,
                    cursor: 'pointer', fontSize: 11, padding: '3px 10px',
                  }}
                >
                  Routes
                </button>
                <button onClick={() => openEdit(p)} style={{
                  background: 'none', border: `1px solid ${color.border}`,
                  borderRadius: size.radius, color: color.textSecondary,
                  cursor: 'pointer', fontSize: 11, padding: '3px 10px',
                }}>Edit</button>
                <button onClick={() => setConfirmDelete(p)} style={{
                  background: 'none', border: `1px solid ${color.statusFault}50`,
                  borderRadius: size.radius, color: color.statusFault,
                  cursor: 'pointer', fontSize: 11, padding: '3px 10px',
                }}>Delete</button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Create/Edit process modal */}
      {(creating || editTarget) && (
        <Modal title={editTarget ? `Edit — ${editTarget.name}` : 'New Process'} onClose={closeModal}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>NAME *</FieldLabel>
            <input value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} autoFocus />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>DESCRIPTION</FieldLabel>
            <input value={description} onChange={(e) => setDescription(e.target.value)} style={inputStyle} />
          </label>
          <ErrorMsg msg={error} />
          <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end' }}>
            <button onClick={closeModal} style={secondaryBtn}>Cancel</button>
            <button onClick={handleSave} disabled={saving} style={primaryBtn(saving)}>
              {saving ? 'Saving…' : (editTarget ? 'Save Changes' : 'Create Process')}
            </button>
          </div>
        </Modal>
      )}

      {/* Route editor modal */}
      {routeEditor && (
        <RouteEditorModal process={routeEditor} onClose={() => setRouteEditor(null)} />
      )}

      {/* Confirm delete */}
      {confirmDelete && (
        <Modal title="Delete Process?" onClose={() => setConfirmDelete(null)} width={360}>
          <p style={{ fontSize: 13, color: color.textSecondary, margin: 0 }}>
            Delete <strong style={{ color: color.textPrimary }}>{confirmDelete.name}</strong> and all its routes?
          </p>
          <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end' }}>
            <button onClick={() => setConfirmDelete(null)} style={secondaryBtn}>Cancel</button>
            <button onClick={() => handleDelete(confirmDelete)} style={dangerBtn}>Delete</button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ─── Quantity stepper (edge weight) with up/down arrows ──────────────────────

function QtyStepper({ value, onChange, min = 1, title }: {
  value: number; onChange: (n: number) => void; min?: number; title?: string
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => { setDraft(String(value)) }, [value])

  const step = (delta: number) => {
    const base = parseInt(draft, 10)
    const next = Math.max(min, (isNaN(base) ? value : base) + delta)
    setDraft(String(next))
    onChange(next)
  }
  const btn: React.CSSProperties = {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    width: 18, height: 11, padding: 0, lineHeight: 1, fontSize: 8,
    background: color.bgElevated, border: 'none', color: color.textSecondary, cursor: 'pointer',
  }
  return (
    <div title={title} style={{
      display: 'flex', alignItems: 'stretch', flexShrink: 0, height: 24,
      border: `1px solid ${color.border}`, borderRadius: size.radius, overflow: 'hidden',
      background: color.bgCard,
    }}>
      <input
        value={draft}
        inputMode="numeric"
        onChange={(e) => {
          const raw = e.target.value.replace(/[^0-9]/g, '')
          setDraft(raw)
          const n = parseInt(raw, 10)
          if (!isNaN(n) && n >= min) onChange(n)
        }}
        onBlur={() => { const n = parseInt(draft, 10); if (isNaN(n) || n < min) setDraft(String(value)) }}
        style={{
          width: 34, border: 'none', background: 'transparent', color: color.textPrimary,
          fontFamily: font.mono, fontSize: 12, textAlign: 'center', outline: 'none', padding: 0,
        }}
      />
      <div style={{ display: 'flex', flexDirection: 'column', borderLeft: `1px solid ${color.border}` }}>
        <button type="button" aria-label="Increase" onClick={() => step(1)} style={btn}>▲</button>
        <button type="button" aria-label="Decrease" onClick={() => step(-1)}
                style={{ ...btn, borderTop: `1px solid ${color.border}` }}>▼</button>
      </div>
    </div>
  )
}

// ─── Route editor for a single process ───────────────────────────────────────

function RouteRow({ route, label, selected, isMergeFeed, onEditEndpoints }: {
  route: Route; label: React.ReactNode; selected: boolean; isMergeFeed: boolean; onEditEndpoints: () => void
}) {
  const updateRoute = useProcessesStore((s) => s.updateRoute)
  const deleteRoute = useProcessesStore((s) => s.deleteRoute)
  const timer = useRef<ReturnType<typeof setTimeout>>()

  // Debounce weight saves so holding the arrow / typing doesn't spam the API.
  const saveQty = (q: number) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => { updateRoute(route._id, { quantity: q }).catch(() => {}) }, 300)
  }
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: size.sp2,
      padding: `${size.sp2} ${size.sp3}`, borderBottom: `1px solid ${color.border}`,
      background: selected ? color.bgElevated : undefined,
      borderLeft: `2px solid ${selected ? color.borderActive : 'transparent'}`,
    }}>
      <span
        onClick={onEditEndpoints}
        title="Click to change the from/to locations"
        style={{ flex: 1, fontSize: 12, color: color.textPrimary, fontFamily: font.mono, cursor: 'pointer' }}
      >
        {label}
      </span>
      {isMergeFeed ? (
        <QtyStepper value={route.quantity} onChange={saveQty} title="Edge weight — upstream units required per cycle" />
      ) : (
        <span
          title="Weights apply only to routes that are one of multiple feeds into a merge station"
          style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono, padding: '0 8px' }}
        >
          ×1
        </span>
      )}
      <button
        onClick={() => deleteRoute(route._id)}
        title="Delete route"
        style={{ background: 'none', border: 'none', color: color.statusFault, cursor: 'pointer', fontSize: 14, padding: '0 4px' }}
      >×</button>
    </div>
  )
}

function RouteEditorModal({ process, onClose }: { process: Process; onClose: () => void }) {
  const routes       = useProcessesStore((s) => s.routes)
  const createRoute  = useProcessesStore((s) => s.createRoute)
  const updateRoute  = useProcessesStore((s) => s.updateRoute)
  const stations     = useStationsStore((s) => s.stations)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [fromId,  setFromId]  = useState('')
  const [toId,    setToId]    = useState('')
  const [qty,     setQty]     = useState(1)
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState<string | null>(null)

  const processRoutes = Object.values(routes).filter((r) => r.processId === process._id)
  const stationList   = Object.values(stations).sort((a, b) => a.name.localeCompare(b.name))
  const stationName   = (id: string) => stations[id]?.name ?? id

  // Weights only exist on merge feeds: a station with ≥2 incoming routes
  // (counted across all processes, matching the backend rule).
  const incomingCount = (stationId: string, excludeRouteId?: string | null) =>
    Object.values(routes).filter((r) => r.unload === stationId && r._id !== excludeRouteId).length
  const formWeightEditable = !!toId && incomingCount(toId, editingId) >= 1

  const resetForm = () => { setEditingId(null); setFromId(''); setToId(''); setQty(1); setError(null) }
  const loadForEdit = (r: Route) => { setEditingId(r._id); setFromId(r.load); setToId(r.unload); setQty(r.quantity); setError(null) }

  const handleSubmit = async () => {
    if (!fromId || !toId) { setError('Select both locations'); return }
    if (fromId === toId)  { setError('From and To must differ'); return }
    if (qty < 1)          { setError('Weight must be at least 1'); return }

    const dup = processRoutes.find((r) => r.load === fromId && r.unload === toId && r._id !== editingId)
    if (dup) { setError('A route between those locations already exists'); return }

    // Cycle check ignores the edge currently being edited.
    const edges = processRoutes.filter((r) => r._id !== editingId).map((r) => ({ load: r.load, unload: r.unload }))
    if (wouldCreateCycle(edges, fromId, toId)) {
      setError('This route would create a cycle in the process graph')
      return
    }

    setSaving(true); setError(null)
    const effQty = formWeightEditable ? qty : 1   // weights only exist on merge feeds
    try {
      if (editingId) {
        await updateRoute(editingId, { load: fromId, unload: toId, quantity: effQty })
      } else {
        await createRoute({ processId: process._id, load: fromId, unload: toId, quantity: effQty })
      }
      resetForm()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={`Routes — ${process.name}`} onClose={onClose} width={520}>
      {/* Existing routes */}
      <div>
        <FieldLabel>EXISTING ROUTES ({processRoutes.length})</FieldLabel>
        {processRoutes.length === 0 ? (
          <div style={{ fontSize: 11, color: color.textDim, padding: '8px 0' }}>No routes yet.</div>
        ) : (
          <>
            <div style={{ border: `1px solid ${color.border}`, borderRadius: size.radius, overflow: 'hidden' }}>
              {processRoutes.map((r) => (
                <RouteRow
                  key={r._id}
                  route={r}
                  selected={editingId === r._id}
                  isMergeFeed={incomingCount(r.unload) >= 2}
                  onEditEndpoints={() => loadForEdit(r)}
                  label={<>
                    {stationName(r.load)}
                    <span style={{ color: color.textDim, margin: '0 6px' }}>→</span>
                    {stationName(r.unload)}
                  </>}
                />
              ))}
            </div>
            <div style={{ fontSize: 10, color: color.textDim, marginTop: 4 }}>
              Use the <span style={{ fontFamily: font.mono }}>▲▼</span> arrows to set each route's weight
              (upstream units required per cycle); click a route to change its from/to locations.
            </div>
          </>
        )}
      </div>

      {/* Add / edit route */}
      <div>
        <FieldLabel>{editingId ? 'EDIT ROUTE' : 'ADD ROUTE'}</FieldLabel>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr auto', gap: size.sp2, alignItems: 'center' }}>
          <select value={fromId} onChange={(e) => setFromId(e.target.value)} style={inputStyle}>
            <option value="">From location…</option>
            {stationList.map((s) => <option key={s._id} value={s._id}>{s.name}</option>)}
          </select>
          <span style={{ color: color.textDim, fontFamily: font.mono }}>→</span>
          <select value={toId} onChange={(e) => setToId(e.target.value)} style={inputStyle}>
            <option value="">To location…</option>
            {stationList.map((s) => <option key={s._id} value={s._id}>{s.name}</option>)}
          </select>
          {formWeightEditable ? (
            <QtyStepper value={qty} onChange={setQty} title="Edge weight — upstream units required per cycle" />
          ) : (
            <span
              title="Weights apply only to routes that are one of multiple feeds into a merge station"
              style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono, padding: '0 8px' }}
            >
              ×1
            </span>
          )}
        </div>
        <div style={{ fontSize: 10, color: color.textDim, marginTop: 4 }}>
          {formWeightEditable
            ? 'Weight = units of the upstream product required per assembly cycle.'
            : 'Weights become editable once the target station has a second incoming route (a merge).'}
        </div>
        <ErrorMsg msg={error} />
        <div style={{ marginTop: size.sp2, display: 'flex', justifyContent: 'flex-end', gap: size.sp2 }}>
          {editingId && <button onClick={resetForm} style={secondaryBtn}>Cancel</button>}
          <button onClick={handleSubmit} disabled={saving} style={primaryBtn(saving)}>
            {saving ? 'Saving…' : (editingId ? 'Save Changes' : 'Add Route')}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button onClick={onClose} style={secondaryBtn}>Done</button>
      </div>
    </Modal>
  )
}
