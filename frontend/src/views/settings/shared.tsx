import React from 'react'
import { color, font, size, shadow } from '../../theme/tokens'

// ─── Reusable modal shell ─────────────────────────────────────────────────────

export function Modal({
  title,
  onClose,
  children,
  width = 440,
}: {
  title:    string
  onClose:  () => void
  children: React.ReactNode
  width?:   number
}) {
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
      <div style={{
        background:    color.bgPanel,
        border:        `1px solid ${color.border}`,
        borderRadius:  size.radiusMd,
        padding:       size.sp6,
        width,
        maxHeight:     '85vh',
        overflowY:     'auto',
        boxShadow:     shadow.lg,
        display:       'flex',
        flexDirection: 'column',
        gap:           size.sp4,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: color.textPrimary }}>{title}</span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: color.textDim, cursor: 'pointer', fontSize: 18, lineHeight: 1 }}
          >×</button>
        </div>
        {children}
      </div>
    </div>
  )
}

// ─── Field label ──────────────────────────────────────────────────────────────

export function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span style={{
      fontSize:      10,
      color:         color.textSecondary,
      fontFamily:    font.mono,
      letterSpacing: '0.08em',
      display:       'block',
      marginBottom:  4,
    }}>
      {children}
    </span>
  )
}

// ─── Shared input/select styles ───────────────────────────────────────────────

export const inputStyle: React.CSSProperties = {
  background:   color.bgCard,
  border:       `1px solid ${color.border}`,
  borderRadius: size.radius,
  color:        color.textPrimary,
  padding:      '6px 10px',
  fontSize:     13,
  outline:      'none',
  width:        '100%',
  boxSizing:    'border-box',
}

export const secondaryBtn: React.CSSProperties = {
  padding:      '6px 16px',
  background:   'transparent',
  border:       `1px solid ${color.border}`,
  borderRadius: size.radius,
  color:        color.textSecondary,
  cursor:       'pointer',
  fontSize:     12,
}

export const primaryBtn = (disabled = false): React.CSSProperties => ({
  padding:      '6px 16px',
  background:   disabled ? `${color.bluePrimary}30` : color.bluePrimary,
  border:       'none',
  borderRadius: size.radius,
  color:        disabled ? color.textDim : color.white,
  cursor:       disabled ? 'not-allowed' : 'pointer',
  fontSize:     12,
  fontWeight:   600,
})

export const dangerBtn: React.CSSProperties = {
  padding:      '6px 16px',
  background:   'transparent',
  border:       `1px solid ${color.statusFault}60`,
  borderRadius: size.radius,
  color:        color.statusFault,
  cursor:       'pointer',
  fontSize:     12,
}

// ─── Error banner ─────────────────────────────────────────────────────────────

export function ErrorMsg({ msg }: { msg: string | null }) {
  if (!msg) return null
  return (
    <div style={{ fontSize: 11, color: color.statusFault, padding: '4px 0' }}>{msg}</div>
  )
}

// ─── Section row in a settings list ─────────────────────────────────────────

export function ListRow({
  label,
  sub,
  badge,
  onEdit,
  onDelete,
}: {
  label:    string
  sub?:     string
  badge?:   string
  onEdit?:  () => void
  onDelete?: () => void
}) {
  return (
    <div style={{
      display:      'flex',
      alignItems:   'center',
      padding:      `${size.sp3} ${size.sp4}`,
      borderBottom: `1px solid ${color.border}`,
      gap:          size.sp3,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: color.textPrimary, fontWeight: 500 }}>{label}</div>
        {sub && <div style={{ fontSize: 11, color: color.textDim, marginTop: 2 }}>{sub}</div>}
      </div>
      {badge && (
        <span style={{
          fontSize:     10,
          fontFamily:   font.mono,
          color:        color.textSecondary,
          background:   color.bgElevated,
          border:       `1px solid ${color.border}`,
          borderRadius: size.radiusFull,
          padding:      '1px 8px',
        }}>
          {badge}
        </span>
      )}
      {onEdit && (
        <button
          onClick={onEdit}
          style={{
            background:   'none',
            border:       `1px solid ${color.border}`,
            borderRadius: size.radius,
            color:        color.textSecondary,
            cursor:       'pointer',
            fontSize:     11,
            padding:      '3px 10px',
          }}
        >
          Edit
        </button>
      )}
      {onDelete && (
        <button
          onClick={onDelete}
          style={{
            background:   'none',
            border:       `1px solid ${color.statusFault}50`,
            borderRadius: size.radius,
            color:        color.statusFault,
            cursor:       'pointer',
            fontSize:     11,
            padding:      '3px 10px',
          }}
        >
          Delete
        </button>
      )}
    </div>
  )
}
