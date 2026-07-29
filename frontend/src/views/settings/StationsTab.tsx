import React, { useState } from 'react'
import { useStationsStore, useProcessesStore, useMapSettingsStore } from '../../store'
import { color, font, size } from '../../theme/tokens'
import type { Station, AdapterType } from '../../models'
import { Modal, FieldLabel, inputStyle, primaryBtn, secondaryBtn, dangerBtn, ErrorMsg, ListRow } from './shared'
import { STATION_ICONS } from '../../components/map/StationNode'

const ADAPTER_TYPES: { value: AdapterType; label: string }[] = [
  { value: null,          label: 'None (manual only)' },
  { value: 'mock',        label: 'Mock (demo)'         },
  { value: 'plc_modbus',  label: 'PLC – Modbus TCP'    },
  { value: 'plc_opc_ua',  label: 'PLC – OPC-UA'        },
  { value: 'uav',         label: 'UAV / Drone'         },
]

const LOT_COLORS = ['#F0997B','#639922','#EF9F27','#8B5CF6','#E24B4A','#06B6D4','#F97316','#EC4899']

type FormState = {
  name:         string
  description:  string
  adapterType:  AdapterType
  adapterConfig:string
  color:        string | null
  icon:         string | null
  x: string; y: string; w: string; h: string
}

const blank = (): FormState => ({
  name: '', description: '', adapterType: null, adapterConfig: '{}', color: null, icon: null,
  x: '100', y: '100', w: '60', h: '60',
})

function stationToForm(s: Station): FormState {
  return {
    name:         s.name,
    description:  s.description,
    adapterType:  s.adapterType,
    adapterConfig:JSON.stringify(s.adapterConfig ?? {}, null, 2),
    color:        s.color,
    icon:         s.icon,
    x: String(s.position.x),
    y: String(s.position.y),
    w: String(s.position.width),
    h: String(s.position.height),
  }
}

export default function StationsTab() {
  const stations      = useStationsStore((s) => s.stations)
  const createStation = useStationsStore((s) => s.create)
  const updateStation = useStationsStore((s) => s.update)
  const removeStation = useStationsStore((s) => s.remove)
  const routes         = useProcessesStore((s) => s.routes)
  const refreshProcess = useProcessesStore((s) => s.fetchAll)
  const mapSettings    = useMapSettingsStore((s) => s.settings)

  const [editing, setEditing]   = useState<Station | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm]         = useState<FormState>(blank())
  const [saving, setSaving]     = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<Station | null>(null)

  // Place each new station 3 units (e.g. 3 ft) to the right of the most recent
  // one, so they line up along the flow instead of stacking on top of each other.
  const nextPosition = () => {
    const list = Object.values(stations)
    if (list.length === 0) return { x: 100, y: 100 }
    const ppu  = mapSettings?.pixelsPerUnit ?? 100
    const prev = list.reduce((a, b) => (a.createdAt >= b.createdAt ? a : b))
    return { x: Math.round(prev.position.x + 3 * ppu), y: Math.round(prev.position.y) }
  }
  const openCreate = () => {
    const p = nextPosition()
    setForm({ ...blank(), x: String(p.x), y: String(p.y) })
    setCreating(true); setError(null)
  }
  const openEdit   = (s: Station) => { setForm(stationToForm(s)); setEditing(s); setError(null) }
  const closeModal = () => { setCreating(false); setEditing(null) }

  const set = (k: keyof FormState, v: string | null) =>
    setForm((f) => ({ ...f, [k]: v }))

  const handleSave = async () => {
    if (!form.name.trim()) { setError('Name is required'); return }
    let cfg: Record<string,unknown> = {}
    try { cfg = JSON.parse(form.adapterConfig) } catch { setError('Adapter config must be valid JSON'); return }
    setSaving(true); setError(null)
    try {
      const body = {
        name:         form.name.trim(),
        description:  form.description.trim(),
        adapterType:  form.adapterType,
        adapterConfig:cfg,
        color:        form.color,
        icon:         form.icon,
        position: {
          x: parseFloat(form.x) || 0,
          y: parseFloat(form.y) || 0,
          width:  parseFloat(form.w) || 60,
          height: parseFloat(form.h) || 60,
        },
      }
      if (editing) {
        await updateStation(editing._id, body)
      } else {
        await createStation(body as Omit<Station, '_id' | 'createdAt' | 'updatedAt'>)
      }
      closeModal()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (s: Station) => {
    await removeStation(s._id)
    // The DB cascades away routes touching this station; refresh so they don't
    // linger in the board/map (and templates whose origin was reset).
    await refreshProcess()
    setConfirmDelete(null)
  }

  const list = Object.values(stations).sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Toolbar */}
      <div style={{
        padding:      `${size.sp3} ${size.sp6}`,
        borderBottom: `1px solid ${color.border}`,
        display:      'flex',
        alignItems:   'center',
        flexShrink:   0,
      }}>
        <span style={{ flex: 1, fontSize: 11, color: color.textDim }}>
          {list.length} station{list.length !== 1 ? 's' : ''}
        </span>
        <button data-tour="add-station" onClick={openCreate} style={primaryBtn()}>+ Add Station</button>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {list.length === 0 ? (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: 200, color: color.textDim, fontSize: 12, fontFamily: font.mono, letterSpacing: '0.08em',
          }}>
            NO STATIONS — ADD ONE ABOVE
          </div>
        ) : (
          list.map((s) => (
            <ListRow
              key={s._id}
              label={s.name}
              sub={[s.adapterType ?? 'no adapter', s.description].filter(Boolean).join(' · ')}
              badge={s.adapterType ?? undefined}
              onEdit={() => openEdit(s)}
              onDelete={() => setConfirmDelete(s)}
            />
          ))
        )}
      </div>

      {/* Create / Edit modal */}
      {(creating || editing) && (
        <Modal
          title={editing ? `Edit — ${editing.name}` : 'New Station'}
          onClose={closeModal}
          width={480}
        >
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>NAME *</FieldLabel>
            <input value={form.name} onChange={(e) => set('name', e.target.value)} style={inputStyle} autoFocus />
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>DESCRIPTION</FieldLabel>
            <input value={form.description} onChange={(e) => set('description', e.target.value)} style={inputStyle} />
          </label>

          {/* Position */}
          <div>
            <FieldLabel>POSITION (x, y) / SIZE (w, h)</FieldLabel>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: size.sp2 }}>
              {(['x','y','w','h'] as const).map((k) => (
                <input
                  key={k}
                  type="number"
                  placeholder={k.toUpperCase()}
                  value={form[k]}
                  onChange={(e) => set(k, e.target.value)}
                  style={{ ...inputStyle, fontFamily: font.mono }}
                />
              ))}
            </div>
          </div>

          {/* Color picker */}
          <div>
            <FieldLabel>COLOR</FieldLabel>
            <div style={{ display: 'flex', gap: size.sp2, flexWrap: 'wrap' }}>
              {LOT_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => set('color', form.color === c ? null : c)}
                  style={{
                    width: 22, height: 22, borderRadius: '50%',
                    background: c,
                    border: form.color === c ? `2px solid ${color.white}` : '2px solid transparent',
                    cursor: 'pointer',
                    padding: 0,
                  }}
                />
              ))}
              <button
                onClick={() => set('color', null)}
                style={{
                  width: 22, height: 22, borderRadius: '50%',
                  background: color.bgCard,
                  border: !form.color ? `2px solid ${color.white}` : `1px solid ${color.border}`,
                  cursor: 'pointer', padding: 0,
                  fontSize: 12, color: color.textDim,
                }}
              >✕</button>
            </div>
          </div>

          {/* Icon picker */}
          <div>
            <FieldLabel>ICON</FieldLabel>
            <div style={{
              display:             'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(56px, 1fr))',
              gap:                 size.sp2,
              maxHeight:           180,
              overflowY:           'auto',
            }}>
              {STATION_ICONS.map(({ id, label, Icon }) => {
                const active = form.icon === id
                return (
                  <button
                    key={id}
                    title={label}
                    onClick={() => set('icon', active ? null : id)}
                    style={{
                      display:        'flex',
                      flexDirection:  'column',
                      alignItems:     'center',
                      justifyContent: 'center',
                      gap:            3,
                      padding:        '6px 4px',
                      borderRadius:   size.radius,
                      background:     active ? `${form.color ?? '#F0997B'}22` : color.bgCard,
                      border:         active
                        ? `1.5px solid ${form.color ?? '#F0997B'}`
                        : `1px solid ${color.border}`,
                      cursor:         'pointer',
                    }}
                  >
                    <Icon
                      size={18}
                      color={active ? (form.color ?? '#F0997B') : color.textSecondary}
                      strokeWidth={1.5}
                    />
                    <span style={{
                      fontSize:   8,
                      color:      active ? (form.color ?? '#F0997B') : color.textDim,
                      textAlign:  'center',
                      lineHeight: 1.2,
                      whiteSpace: 'nowrap',
                      overflow:   'hidden',
                      textOverflow: 'ellipsis',
                      maxWidth:   52,
                    }}>
                      {label}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Adapter */}
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>ADAPTER TYPE</FieldLabel>
            <select
              value={form.adapterType ?? ''}
              onChange={(e) => set('adapterType', (e.target.value || null) as AdapterType)}
              style={inputStyle}
            >
              {ADAPTER_TYPES.map((a) => (
                <option key={String(a.value)} value={a.value ?? ''}>{a.label}</option>
              ))}
            </select>
          </label>

          <ErrorMsg msg={error} />

          <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end' }}>
            <button onClick={closeModal}  style={secondaryBtn}>Cancel</button>
            <button onClick={handleSave} disabled={saving} style={primaryBtn(saving)}>
              {saving ? 'Saving…' : (editing ? 'Save Changes' : 'Create Station')}
            </button>
          </div>
        </Modal>
      )}

      {/* Confirm delete */}
      {confirmDelete && (() => {
        const nameOf = (id: string) => stations[id]?.name ?? '—'
        const affected = Object.entries(routes)
          .filter(([, r]) => r.load === confirmDelete._id || r.unload === confirmDelete._id)
        return (
        <Modal title="Delete Station?" onClose={() => setConfirmDelete(null)} width={380}>
          <p style={{ fontSize: 13, color: color.textSecondary, margin: 0 }}>
            Delete <strong style={{ color: color.textPrimary }}>{confirmDelete.name}</strong>?
            This cannot be undone. Lots at this station will lose their bin entry.
          </p>
          {affected.length > 0 && (
            <div style={{ marginTop: size.sp3, padding: `${size.sp2} ${size.sp3}`,
                          background: '#EF9F2714', border: `1px solid #EF9F2740`, borderRadius: size.radius }}>
              <div style={{ fontSize: 12.5, color: '#EF9F27', fontWeight: 600, marginBottom: 4 }}>
                {affected.length} connected route{affected.length === 1 ? '' : 's'} will also be deleted:
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: color.textSecondary, lineHeight: 1.55 }}>
                {affected.slice(0, 6).map(([id, r]) => (
                  <li key={id}>{nameOf(r.load)} → {nameOf(r.unload)}</li>
                ))}
                {affected.length > 6 && <li>…and {affected.length - 6} more</li>}
              </ul>
            </div>
          )}
          <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end', marginTop: size.sp4 }}>
            <button onClick={() => setConfirmDelete(null)} style={secondaryBtn}>Cancel</button>
            <button onClick={() => handleDelete(confirmDelete)} style={dangerBtn}>Delete</button>
          </div>
        </Modal>
        )
      })()}
    </div>
  )
}
