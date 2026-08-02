import React, { useEffect, useRef, useState } from 'react'
import { HelpCircle } from 'lucide-react'
import { color, font, size, shadow } from '../theme/tokens'
import { useRole } from '../auth/useRole'
import { useHelpStore } from './helpStore'
import { WhatsNewDialog } from './WhatsNew'

export function HelpMenu() {
  const [open, setOpen] = useState(false)
  const [whatsNew, setWhatsNew] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { isSuperAdmin } = useRole()
  const openManual = useHelpStore((s) => s.openManual)
  const startTour = useHelpStore((s) => s.startTour)
  const showCallout = useHelpStore((s) => s.showCallout)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const item: React.CSSProperties = {
    display: 'block', width: '100%', textAlign: 'left', background: 'transparent', border: 'none',
    color: color.textSecondary, padding: `${size.sp2} ${size.sp3}`, fontSize: 13, cursor: 'pointer',
    fontFamily: font.sans, borderRadius: size.radius,
  }

  const choose = (fn: () => void) => () => { fn(); setOpen(false) }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      {whatsNew && <WhatsNewDialog onClose={() => setWhatsNew(false)} />}
      <button onClick={() => setOpen((v) => !v)} title="Help"
              style={{ display: 'flex', alignItems: 'center', background: 'transparent',
                       border: `1px solid ${color.border}`, borderRadius: size.radius,
                       color: color.textSecondary, padding: size.sp1, cursor: 'pointer' }}>
        <HelpCircle size={16} />
      </button>
      {open && (
        <div style={{ position: 'absolute', right: 0, top: 'calc(100% + 6px)', width: 190,
                      background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: size.radiusMd,
                      boxShadow: shadow.md, padding: size.sp1, zIndex: 200 }}>
          {isSuperAdmin && <button style={item} onClick={choose(startTour)}>🧭 Take the tour</button>}
          <button style={item} onClick={choose(openManual)}>📖 User manual</button>
          <button style={item} onClick={choose(showCallout)}>👋 Getting started</button>
          <button style={item} onClick={choose(() => setWhatsNew(true))}>✨ What&rsquo;s new</button>
        </div>
      )}
    </div>
  )
}
