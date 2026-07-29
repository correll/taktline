import React, { useState } from 'react'
import { color, font, size, shadow } from '../theme/tokens'
import { useRole } from '../auth/useRole'
import { useHelpStore, DISMISS_KEY } from './helpStore'
import { TaktlineLogo } from '../components/TaktlineLogo'

/** First-run welcome, offering the tour or the manual. Also re-openable from
 *  Help → Getting started. */
export function GettingStarted() {
  const dismissed = useHelpStore((s) => s.calloutDismissed)
  const dismiss = useHelpStore((s) => s.dismissCallout)
  const startTour = useHelpStore((s) => s.startTour)
  const openManual = useHelpStore((s) => s.openManual)
  const { isSuperAdmin } = useRole()
  // Reflect any stored preference, so re-opening shows the box already ticked.
  const [remember, setRemember] = useState(() => localStorage.getItem(DISMISS_KEY) === '1')

  if (dismissed) return null

  return (
    <div style={{ position: 'fixed', inset: 0, background: color.backdrop, zIndex: 10001,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: size.sp6 }}>
      <div style={{ width: 460, maxWidth: '100%', background: color.bgPanel, border: `1px solid ${color.borderActive}`,
                    borderRadius: size.radiusLg, boxShadow: shadow.lg, padding: size.sp8, textAlign: 'center',
                    fontFamily: font.sans }}>
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: size.sp3, color: color.textPrimary }}>
          <TaktlineLogo mark height={40} />
        </div>
        <h2 style={{ color: color.textPrimary, fontSize: 20, margin: 0 }}>Welcome to Taktline</h2>
        <p style={{ color: color.textSecondary, fontSize: 14, lineHeight: 1.6, marginTop: size.sp3 }}>
          Taktline models your production as a living graph — stations, routes, and lot cards that flow
          through them. {isSuperAdmin
            ? 'New here? Take a five-minute guided tour and build your first line end to end, or browse the manual.'
            : 'Browse the manual to learn how the board and operator views work.'}
        </p>

        <div style={{ display: 'flex', gap: size.sp3, justifyContent: 'center', marginTop: size.sp6, flexWrap: 'wrap' }}>
          {isSuperAdmin && (
            <button onClick={() => { dismiss(remember); startTour() }}
                    style={{ background: color.bluePrimary, color: color.white, border: 'none', borderRadius: size.radius,
                             padding: `${size.sp3} ${size.sp6}`, fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>
              🧭 Take the tour
            </button>
          )}
          <button onClick={() => { openManual(); dismiss(remember) }}
                  style={{ background: color.bgCard, color: color.textPrimary, border: `1px solid ${color.border}`,
                           borderRadius: size.radius, padding: `${size.sp3} ${size.sp6}`, fontSize: 14, cursor: 'pointer' }}>
            📖 Open the manual
          </button>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: size.sp2,
                        marginTop: size.sp6, fontSize: 13, color: color.textSecondary, cursor: 'pointer' }}>
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)}
                 style={{ accentColor: color.bluePrimary, width: 15, height: 15, cursor: 'pointer' }} />
          Don’t show this again
        </label>

        <button onClick={() => dismiss(remember)}
                style={{ marginTop: size.sp3, background: 'none', border: 'none', color: color.textDim,
                         fontSize: 13, cursor: 'pointer' }}>
          Maybe later
        </button>
      </div>
    </div>
  )
}
