import React, { useEffect, useState } from 'react'
import { color, font, size, shadow } from '../theme/tokens'
import { useHelpStore } from './helpStore'
import { tipOfTheDay } from './leanTips'
import { disableTips, recordTipShown, shouldShowTip, todayKey } from './tipSchedule'

/** Daily lean-tip splash: one tip per calendar day, dismissible, with a
 *  persistent opt-out. Stays out of the way of the first-run welcome and the
 *  guided tour. */
export function TipOfTheDay() {
  const calloutDismissed = useHelpStore((s) => s.calloutDismissed)
  const tourActive = useHelpStore((s) => s.tourActive)
  const openManual = useHelpStore((s) => s.openManual)

  const [visible, setVisible] = useState(() => shouldShowTip(localStorage, todayKey()))

  // Welcome dialog and tour take precedence over the daily tip.
  const showing = visible && calloutDismissed && !tourActive

  // Mark it seen the moment it is actually on screen. Recording this in
  // `dismiss` instead meant a tip only counted as shown if the user clicked
  // something, so it reappeared on every page load until they did.
  useEffect(() => {
    if (showing) recordTipShown(localStorage, todayKey())
  }, [showing])

  if (!showing) return null

  const tip = tipOfTheDay()

  const dismiss = (forever = false) => {
    if (forever) disableTips(localStorage)
    setVisible(false)
  }

  return (
    <div style={{
      position: 'fixed', bottom: size.sp6, left: '50%', transform: 'translateX(-50%)',
      zIndex: 9000, width: 460, maxWidth: 'calc(100vw - 32px)',
      background: color.bgPanel, border: `1px solid ${color.border}`,
      borderTop: `3px solid ${color.bluePrimary}`,
      borderRadius: size.radiusMd, boxShadow: shadow.lg,
      padding: `${size.sp4} ${size.sp5}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: size.sp2, marginBottom: size.sp2 }}>
        <span style={{ fontSize: 14 }}>💡</span>
        <span style={{ fontSize: 10, fontFamily: font.mono, letterSpacing: '0.12em', color: color.textDim }}>
          LEAN TIP OF THE DAY
        </span>
        <span style={{
          fontSize: 9, fontFamily: font.mono, letterSpacing: '0.06em', marginLeft: 'auto',
          color: color.blueBright, background: `${color.bluePrimary}18`,
          border: `1px solid ${color.bluePrimary}40`,
          borderRadius: size.radiusFull, padding: '1px 8px',
        }}>
          {tip.category}
        </span>
      </div>

      <div style={{ fontSize: 13, color: color.textPrimary, lineHeight: 1.55 }}>
        {tip.text}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3, marginTop: size.sp3 }}>
        <button
          onClick={() => { dismiss(); openManual() }}
          style={{
            background: 'none', border: 'none', color: color.blueBright,
            fontSize: 11, cursor: 'pointer', padding: 0,
          }}
        >
          Learn more in the manual
        </button>
        <button
          onClick={() => dismiss(true)}
          style={{
            background: 'none', border: 'none', color: color.textDim,
            fontSize: 11, cursor: 'pointer', padding: 0, marginLeft: 'auto',
          }}
        >
          Don’t show tips
        </button>
        <button
          onClick={() => dismiss()}
          style={{
            background: color.bluePrimary, color: color.white, border: 'none',
            borderRadius: size.radius, padding: `4px 14px`, fontSize: 12,
            fontWeight: 600, cursor: 'pointer',
          }}
        >
          Got it
        </button>
      </div>
    </div>
  )
}
