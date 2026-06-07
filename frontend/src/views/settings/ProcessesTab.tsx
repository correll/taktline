import React, { useState, useMemo } from 'react'
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
        <button onClick={openCreate} style={primaryBtn()}>+ Add Process</button>
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

// ─── Route editor for a single process ───────────────────────────────────────

function RouteEditorModal({ process, onClose }: { process: Process; onClose: () => void }) {
  const routes       = useProcessesStore((s) => s.routes)
  const createRoute  = useProcessesStore((s) => s.createRoute)
  const deleteRoute  = useProcessesStore((s) => s.deleteRoute)
  const stations     = useStationsStore((s) => s.stations)

  const [fromId,  setFromId]  = useState('')
  const [toId,    setToId]    = useState('')
  const [qty,     setQty]     = useState('1')
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState<string | null>(null)

  const processRoutes = Object.values(routes).filter((r) => r.processId === process._id)
  const stationList   = Object.values(stations).sort((a, b) => a.name.localeCompare(b.name))

  const handleAdd = async () => {
    if (!fromId || !toId) { setError('Select both stations'); return }
    if (fromId === toId)  { setError('From and To must differ'); return }

    const quantity = parseInt(qty, 10)
    if (isNaN(quantity) || quantity < 1) { setError('Quantity must be at least 1'); return }

    const dup = processRoutes.find((r) => r.load === fromId && r.unload === toId)
    if (dup) { setError('Route already exists'); return }

    const edges = processRoutes.map((r) => ({ load: r.load, unload: r.unload }))
    if (wouldCreateCycle(edges, fromId, toId)) {
      setError('This route would create a cycle in the process graph')
      return
    }

    setSaving(true); setError(null)
    try {
      await createRoute({ processId: process._id, load: fromId, unload: toId, quantity })
      setFromId(''); setToId(''); setQty('1')
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const stationName = (id: string) => stations[id]?.name ?? id

  return (
    <Modal title={`Routes — ${process.name}`} onClose={onClose} width={520}>
      {/* Existing routes */}
      <div>
        <FieldLabel>EXISTING ROUTES ({processRoutes.length})</FieldLabel>
        {processRoutes.length === 0 ? (
          <div style={{ fontSize: 11, color: color.textDim, padding: '8px 0' }}>No routes yet.</div>
        ) : (
          <div style={{
            border: `1px solid ${color.border}`, borderRadius: size.radius, overflow: 'hidden',
          }}>
            {processRoutes.map((r) => (
              <div key={r._id} style={{
                display: 'flex', alignItems: 'center', padding: `${size.sp2} ${size.sp3}`,
                borderBottom: `1px solid ${color.border}`,
                gap: size.sp2,
              }}>
                <span style={{ flex: 1, fontSize: 12, color: color.textPrimary, fontFamily: font.mono }}>
                  {stationName(r.load)}
                  <span style={{ color: color.textDim, margin: '0 6px' }}>→</span>
                  {stationName(r.unload)}
                </span>
                <span style={{
                  fontSize: 10, fontFamily: font.mono, color: color.textSecondary,
                  background: color.bgElevated, border: `1px solid ${color.border}`,
                  borderRadius: size.radiusFull, padding: '1px 8px',
                  flexShrink: 0,
                }}>
                  ×{r.quantity}
                </span>
                <button
                  onClick={() => deleteRoute(r._id)}
                  style={{
                    background: 'none', border: 'none',
                    color: color.statusFault, cursor: 'pointer', fontSize: 14, padding: '0 4px',
                  }}
                >×</button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add new route */}
      <div>
        <FieldLabel>ADD ROUTE</FieldLabel>
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
          <input
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            title="Units required (edge weight)"
            style={{ ...inputStyle, width: 56, fontFamily: font.mono, textAlign: 'center' }}
          />
        </div>
        <div style={{ fontSize: 10, color: color.textDim, marginTop: 4 }}>
          Quantity = units of the upstream product required per assembly cycle.
        </div>
        <ErrorMsg msg={error} />
        <div style={{ marginTop: size.sp2, display: 'flex', justifyContent: 'flex-end' }}>
          <button onClick={handleAdd} disabled={saving} style={primaryBtn(saving)}>
            {saving ? 'Adding…' : 'Add Route'}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button onClick={onClose} style={secondaryBtn}>Done</button>
      </div>
    </Modal>
  )
}
