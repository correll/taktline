import React from 'react'
import { Sun, Moon } from 'lucide-react'
import { useThemeStore } from '../store/theme.store'
import { color } from '../theme/tokens'

// Day/night switch, pinned to the bottom-left of every screen (rendered once
// in App). Icon + tooltip carry the meaning — never color alone (BRANDING.md).
export function ThemeToggle() {
  const mode   = useThemeStore((s) => s.mode)
  const toggle = useThemeStore((s) => s.toggle)
  const label  = mode === 'night' ? 'Switch to day mode' : 'Switch to night mode'
  const Icon   = mode === 'night' ? Sun : Moon

  return (
    <button
className="tk-theme-toggle"       onClick={toggle}
      title={label}
      aria-label={label}
      style={{
        position:       'fixed',
        bottom:         16,
        left:           16,
        zIndex:         300,
        width:          34,
        height:         34,
        borderRadius:   '50%',
        background:     color.glass,
        border:         `1px solid ${color.glassBorder}`,
        color:          color.glassText,
        cursor:         'pointer',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        padding:        0,
      }}
    >
      <Icon size={16} strokeWidth={1.8} />
    </button>
  )
}
