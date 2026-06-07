import React, { useEffect, useState } from 'react'
import { useProcessesStore, useStationsStore } from '../../store'
import { color, font, size } from '../../theme/tokens'
import type { LotTemplate, FieldDefinition, FieldType } from '../../models'
import { Modal, FieldLabel, inputStyle, primaryBtn, secondaryBtn, dangerBtn, ErrorMsg, ListRow } from './shared'

const LOT_COLORS = ['#3B82F6','#10B981','#F59E0B','#8B5CF6','#EF4444','#06B6D4','#F97316','#EC4899']
const FIELD_TYPES: FieldType[] = ['text', 'number', 'date', 'select']

type FormState = {
  name:           string
  description:    string
  processId:      string
  startStationId: string
  color:          string | null
  fields:         FieldDefinition[]
}

const blank = (): FormState => ({
  name: '', description: '', processId: '', startStationId: '', color: null, fields: [],
})

function templateToForm(t: LotTemplate): FormState {
  return {
    name:           t.name,
    description:    t.description,
    processId:      t.processId ?? '',
    startStationId: t.startStationId ?? '',
    color:          t.color,
    fields:         t.fields.map((f) => ({ ...f })),
  }
}

const blankField = (): FieldDefinition => ({
  key: '', label: '', type: 'text', options: [], required: false,
})

interface Props {
  initialStationId?: string | null
}

export default function TemplatesTab({ initialStationId }: Props = {}) {
  const templates       = useProcessesStore((s) => s.lotTemplates)
  const processes       = useProcessesStore((s) => s.processes)
  const stations        = useStationsStore((s) => s.stations)
  const createTemplate  = useProcessesStore((s) => s.createTemplate)
  const updateTemplate  = useProcessesStore((s) => s.updateTemplate)
  const deleteTemplate  = useProcessesStore((s) => s.deleteTemplate)

  const [editing, setEditing]         = useState<LotTemplate | null>(null)
  const [creating, setCreating]       = useState(false)
  const [form, setForm]               = useState<FormState>(blank())
  const [saving, setSaving]           = useState(false)
  const [error, setError]             = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<LotTemplate | null>(null)

  // Deep-link from merge station error banner: open create modal pre-populated
  useEffect(() => {
    if (initialStationId) {
      setForm({ ...blank(), startStationId: initialStationId })
      setCreating(true)
      setError(null)
    }
  }, [initialStationId])

  const openCreate = () => { setForm(blank()); setCreating(true); setError(null) }
  const openEdit   = (t: LotTemplate) => { setForm(templateToForm(t)); setEditing(t); setError(null) }
  const closeModal = () => { setCreating(false); setEditing(null) }

  const setF = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  const handleSave = async () => {
    if (!form.name.trim()) { setError('Name is required'); return }
    // Validate fields
    for (const fd of form.fields) {
      if (!fd.key.trim()) { setError('All fields need a key'); return }
      if (!fd.label.trim()) { setError('All fields need a label'); return }
    }
    setSaving(true); setError(null)
    try {
      const body: Partial<LotTemplate> = {
        name:           form.name.trim(),
        description:    form.description.trim(),
        processId:      form.processId || null,
        startStationId: form.startStationId || null,
        color:          form.color,
        fields:         form.fields,
      }
      if (editing) {
        await updateTemplate(editing._id, body)
      } else {
        await createTemplate(body)
      }
      closeModal()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const addField    = () => setForm((f) => ({ ...f, fields: [...f.fields, blankField()] }))
  const removeField = (i: number) => setForm((f) => ({ ...f, fields: f.fields.filter((_, idx) => idx !== i) }))
  const setField    = (i: number, k: keyof FieldDefinition, v: unknown) =>
    setForm((f) => {
      const fields = f.fields.map((fd, idx) => idx === i ? { ...fd, [k]: v } : fd)
      return { ...f, fields }
    })

  const processList = Object.values(processes).sort((a, b) => a.name.localeCompare(b.name))
  const stationList = Object.values(stations).sort((a, b) => a.name.localeCompare(b.name))
  const list        = Object.values(templates).sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{
        padding: `${size.sp3} ${size.sp6}`,
        borderBottom: `1px solid ${color.border}`,
        display: 'flex', alignItems: 'center', flexShrink: 0,
      }}>
        <span style={{ flex: 1, fontSize: 11, color: color.textDim }}>
          {list.length} template{list.length !== 1 ? 's' : ''}
        </span>
        <button onClick={openCreate} style={primaryBtn()}>+ Add Template</button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {list.length === 0 ? (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: 200, color: color.textDim, fontSize: 12, fontFamily: font.mono, letterSpacing: '0.08em',
          }}>
            NO TEMPLATES — ADD ONE ABOVE
          </div>
        ) : (
          list.map((t) => (
            <ListRow
              key={t._id}
              label={t.name}
              sub={[
                processes[t.processId ?? '']?.name,
                stations[t.startStationId ?? '']?.name ? `starts at ${stations[t.startStationId ?? '']?.name}` : null,
                t.fields.length ? `${t.fields.length} field${t.fields.length !== 1 ? 's' : ''}` : null,
              ].filter(Boolean).join(' · ')}
              badge={t.color ? undefined : undefined}
              onEdit={() => openEdit(t)}
              onDelete={() => setConfirmDelete(t)}
            />
          ))
        )}
      </div>

      {/* Create/Edit modal */}
      {(creating || editing) && (
        <Modal title={editing ? `Edit — ${editing.name}` : 'New Template'} onClose={closeModal} width={520}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>NAME *</FieldLabel>
            <input value={form.name} onChange={(e) => setF('name', e.target.value)} style={inputStyle} autoFocus />
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <FieldLabel>DESCRIPTION</FieldLabel>
            <input value={form.description} onChange={(e) => setF('description', e.target.value)} style={inputStyle} />
          </label>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: size.sp3 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <FieldLabel>PROCESS</FieldLabel>
              <select value={form.processId} onChange={(e) => setF('processId', e.target.value)} style={inputStyle}>
                <option value="">— none —</option>
                {processList.map((p) => <option key={p._id} value={p._id}>{p.name}</option>)}
              </select>
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <FieldLabel>START LOCATION</FieldLabel>
              <select value={form.startStationId} onChange={(e) => setF('startStationId', e.target.value)} style={inputStyle}>
                <option value="">— none —</option>
                {stationList.map((s) => <option key={s._id} value={s._id}>{s.name}</option>)}
              </select>
            </label>
          </div>

          {/* Color */}
          <div>
            <FieldLabel>COLOR</FieldLabel>
            <div style={{ display: 'flex', gap: size.sp2, flexWrap: 'wrap' }}>
              {LOT_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => setF('color', form.color === c ? null : c)}
                  style={{
                    width: 22, height: 22, borderRadius: '50%', background: c,
                    border: form.color === c ? `2px solid ${color.white}` : '2px solid transparent',
                    cursor: 'pointer', padding: 0,
                  }}
                />
              ))}
              <button
                onClick={() => setF('color', null)}
                style={{
                  width: 22, height: 22, borderRadius: '50%',
                  background: color.bgCard,
                  border: !form.color ? `2px solid ${color.white}` : `1px solid ${color.border}`,
                  cursor: 'pointer', padding: 0, fontSize: 12, color: color.textDim,
                }}
              >✕</button>
            </div>
          </div>

          {/* Fields editor */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: size.sp2 }}>
              <FieldLabel>CUSTOM FIELDS ({form.fields.length})</FieldLabel>
              <button
                onClick={addField}
                style={{
                  marginLeft: 'auto', background: 'none',
                  border: `1px solid ${color.border}`, borderRadius: size.radius,
                  color: color.textSecondary, cursor: 'pointer', fontSize: 11, padding: '2px 10px',
                }}
              >
                + Add Field
              </button>
            </div>
            {form.fields.map((fd, i) => (
              <FieldRow key={i} fd={fd} index={i} onSet={setField} onRemove={removeField} />
            ))}
          </div>

          <ErrorMsg msg={error} />

          <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end' }}>
            <button onClick={closeModal} style={secondaryBtn}>Cancel</button>
            <button onClick={handleSave} disabled={saving} style={primaryBtn(saving)}>
              {saving ? 'Saving…' : (editing ? 'Save Changes' : 'Create Template')}
            </button>
          </div>
        </Modal>
      )}

      {/* Confirm delete */}
      {confirmDelete && (
        <Modal title="Delete Template?" onClose={() => setConfirmDelete(null)} width={360}>
          <p style={{ fontSize: 13, color: color.textSecondary, margin: 0 }}>
            Delete <strong style={{ color: color.textPrimary }}>{confirmDelete.name}</strong>?
            Existing lots using this template will still exist.
          </p>
          <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'flex-end' }}>
            <button onClick={() => setConfirmDelete(null)} style={secondaryBtn}>Cancel</button>
            <button onClick={async () => { await deleteTemplate(confirmDelete._id); setConfirmDelete(null) }} style={dangerBtn}>
              Delete
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ─── Single field row in the field editor ────────────────────────────────────

function FieldRow({
  fd, index, onSet, onRemove,
}: {
  fd:       FieldDefinition
  index:    number
  onSet:    (i: number, k: keyof FieldDefinition, v: unknown) => void
  onRemove: (i: number) => void
}) {
  return (
    <div style={{
      border: `1px solid ${color.border}`, borderRadius: size.radius,
      padding: size.sp3, marginBottom: size.sp2,
      display: 'flex', flexDirection: 'column', gap: size.sp2,
    }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: size.sp2, alignItems: 'center' }}>
        <input
          placeholder="key (no spaces)"
          value={fd.key}
          onChange={(e) => onSet(index, 'key', e.target.value.replace(/\s/g, '_'))}
          style={{ ...inputStyle, fontFamily: font.mono, fontSize: 11 }}
        />
        <input
          placeholder="Display Label"
          value={fd.label}
          onChange={(e) => onSet(index, 'label', e.target.value)}
          style={inputStyle}
        />
        <button
          onClick={() => onRemove(index)}
          style={{
            background: 'none', border: 'none', color: color.statusFault,
            cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: '0 4px',
          }}
        >×</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: size.sp2, alignItems: 'center' }}>
        <select
          value={fd.type}
          onChange={(e) => onSet(index, 'type', e.target.value as FieldType)}
          style={{ ...inputStyle, fontSize: 11 }}
        >
          {FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <label style={{ display: 'flex', alignItems: 'center', gap: size.sp2, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={fd.required}
            onChange={(e) => onSet(index, 'required', e.target.checked)}
            style={{ accentColor: color.bluePrimary }}
          />
          <span style={{ fontSize: 11, color: color.textSecondary }}>Required</span>
        </label>
      </div>

      {fd.type === 'select' && (
        <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <FieldLabel>OPTIONS (comma-separated)</FieldLabel>
          <input
            value={fd.options.join(', ')}
            onChange={(e) => onSet(index, 'options', e.target.value.split(',').map((o) => o.trim()).filter(Boolean))}
            style={{ ...inputStyle, fontSize: 11 }}
            placeholder="Option A, Option B, Option C"
          />
        </label>
      )}
    </div>
  )
}
