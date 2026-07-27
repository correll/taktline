import React from 'react'
import { color, font, size, shadow } from '../../theme/tokens'
import { TaktlineLogo } from '../../components/TaktlineLogo'

export function AuthCard({ title, subtitle, children }: {
  title: string; subtitle?: React.ReactNode; children?: React.ReactNode
}) {
  return (
    <div style={{
      minHeight: '100%', width: '100%', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: color.bgDeep, padding: size.sp6, boxSizing: 'border-box',
    }}>
      <div style={{
        width: 400, maxWidth: '100%', background: color.bgPanel,
        border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
        boxShadow: shadow.lg, padding: size.sp8, boxSizing: 'border-box',
      }}>
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: size.sp6 }}>
          <TaktlineLogo height={28} color={color.textPrimary} />
        </div>
        <h1 style={{ fontSize: 19, color: color.textPrimary, margin: 0, fontFamily: font.sans }}>{title}</h1>
        {subtitle && (
          <p style={{ color: color.textSecondary, fontSize: 13, marginTop: size.sp2, marginBottom: 0, lineHeight: 1.5 }}>
            {subtitle}
          </p>
        )}
        <div style={{ marginTop: size.sp6 }}>{children}</div>
      </div>
    </div>
  )
}

type FieldProps = React.InputHTMLAttributes<HTMLInputElement> & { label: string }
export function Field({ label, ...props }: FieldProps) {
  return (
    <label style={{ display: 'block', marginBottom: size.sp4 }}>
      <span style={{ display: 'block', fontSize: 12, color: color.textSecondary, marginBottom: size.sp1 }}>{label}</span>
      <input
        {...props}
        style={{
          width: '100%', boxSizing: 'border-box', padding: `${size.sp2} ${size.sp3}`,
          background: color.bgCard, border: `1px solid ${color.border}`, borderRadius: size.radius,
          color: color.textPrimary, fontSize: 14, fontFamily: font.sans, outline: 'none',
        }}
      />
    </label>
  )
}

export function PrimaryButton({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      style={{
        width: '100%', padding: size.sp3,
        background: props.disabled ? color.bgElevated : color.bluePrimary,
        color: color.white, border: 'none', borderRadius: size.radius,
        fontSize: 14, fontWeight: 600, cursor: props.disabled ? 'default' : 'pointer',
        fontFamily: font.sans, opacity: props.disabled ? 0.6 : 1,
      }}
    >
      {children}
    </button>
  )
}

export function FormError({ children }: { children?: React.ReactNode }) {
  if (!children) return null
  return <div style={{ color: color.statusFault, fontSize: 13, marginBottom: size.sp4 }}>{children}</div>
}

export function FormInfo({ children }: { children?: React.ReactNode }) {
  if (!children) return null
  return <div style={{ color: color.statusRunning, fontSize: 13, marginBottom: size.sp4, wordBreak: 'break-all' }}>{children}</div>
}

export function AuthFooter({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ marginTop: size.sp5, fontSize: 13, color: color.textSecondary, textAlign: 'center' }}>
      {children}
    </div>
  )
}

export const linkStyle: React.CSSProperties = { color: color.blueBright, textDecoration: 'none', fontWeight: 500 }
