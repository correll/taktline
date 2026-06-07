import React, { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { color, font, size, shadow } from '../theme/tokens'

// ─── Types ────────────────────────────────────────────────────────────────────

type ToastLevel = 'info' | 'success' | 'warning' | 'error'

interface Toast {
  id:      number
  level:   ToastLevel
  message: string
}

interface ToastCtx {
  toast: (message: string, level?: ToastLevel) => void
}

// ─── Context ──────────────────────────────────────────────────────────────────

const Ctx = createContext<ToastCtx>({ toast: () => {} })

let _id = 0
const DURATION_MS = 3500

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const toast = useCallback((message: string, level: ToastLevel = 'info') => {
    const id = ++_id
    setToasts((t) => [...t, { id, level, message }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), DURATION_MS)
  }, [])

  return (
    <Ctx.Provider value={{ toast }}>
      {children}
      <ToastStack toasts={toasts} />
    </Ctx.Provider>
  )
}

export function useToast() {
  return useContext(Ctx)
}

// ─── Rendering ────────────────────────────────────────────────────────────────

const LEVEL_COLOR: Record<ToastLevel, string> = {
  info:    color.blueBright,
  success: color.statusRunning,
  warning: color.statusWarning,
  error:   color.statusFault,
}

function ToastStack({ toasts }: { toasts: Toast[] }) {
  if (toasts.length === 0) return null

  return (
    <div style={{
      position:      'fixed',
      bottom:        24,
      right:         24,
      zIndex:        2000,
      display:       'flex',
      flexDirection: 'column',
      gap:           8,
      pointerEvents: 'none',
    }}>
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} />
      ))}
    </div>
  )
}

function ToastItem({ toast: t }: { toast: Toast }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const raf = requestAnimationFrame(() => setVisible(true))
    return () => cancelAnimationFrame(raf)
  }, [])

  const accent = LEVEL_COLOR[t.level]

  return (
    <div style={{
      background:   color.bgPanel,
      border:       `1px solid ${color.border}`,
      borderLeft:   `3px solid ${accent}`,
      borderRadius: size.radiusMd,
      padding:      `${size.sp3} ${size.sp4}`,
      boxShadow:    shadow.md,
      maxWidth:     320,
      fontSize:     12,
      color:        color.textPrimary,
      fontFamily:   font.sans,
      opacity:      visible ? 1 : 0,
      transform:    visible ? 'translateY(0)' : 'translateY(12px)',
      transition:   'opacity 0.2s ease, transform 0.2s ease',
      pointerEvents:'none',
    }}>
      {t.message}
    </div>
  )
}
