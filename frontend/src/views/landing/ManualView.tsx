import React from 'react'
import { Link } from 'react-router-dom'
import { TaktlineLogo } from '../../components/TaktlineLogo'
import { ManualContent } from '../../help/UserManual'
import { color, font, size } from '../../theme/tokens'

// Public mirror of the in-app user manual — identical content, no sign-in.

export default function ManualView() {
  return (
    <div style={{ flex: 1, overflowY: 'auto', background: color.bgDeep }}>
      <header style={{
        position: 'sticky', top: 0, zIndex: 50,
        background: color.bgPanel, borderBottom: `1px solid ${color.border}`,
        padding: `0 ${size.sp6}`, height: 56, display: 'flex', alignItems: 'center',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', width: '100%', maxWidth: 900, margin: '0 auto', gap: size.sp4 }}>
          <Link to="/" style={{ display: 'flex', color: color.textPrimary }} aria-label="Taktline home">
            <TaktlineLogo height={24} color={color.textPrimary} />
          </Link>
          <span style={{ fontSize: 13, color: color.textDim }}>User manual</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: size.sp3 }}>
            <Link to="/login" style={{ color: color.textPrimary, textDecoration: 'none', fontSize: 14,
                                       border: `1px solid ${color.border}`, borderRadius: size.radiusMd, padding: '8px 16px' }}>
              Sign in
            </Link>
            <Link to="/signup" style={{ background: color.bluePrimary, color: '#fff', textDecoration: 'none',
                                        fontSize: 14, fontWeight: 600, borderRadius: size.radiusMd, padding: '8px 18px' }}>
              Start free
            </Link>
          </div>
        </div>
      </header>

      <main style={{ maxWidth: 820, margin: '0 auto', padding: `${size.sp6} ${size.sp6} ${size.sp12}`, fontFamily: font.sans }}>
        <ManualContent />
        <div style={{
          marginTop: size.sp10, padding: size.sp6, textAlign: 'center',
          background: color.bgCard, border: `1px solid ${color.borderActive}55`, borderRadius: size.radiusLg,
        }}>
          <div style={{ fontSize: 16, fontWeight: 500, color: color.textPrimary }}>
            Ready to see it on your own floor plan?
          </div>
          <div style={{ marginTop: size.sp4 }}>
            <Link to="/signup" style={{ display: 'inline-block', background: color.bluePrimary, color: '#fff',
                                        textDecoration: 'none', fontSize: 15, fontWeight: 600,
                                        borderRadius: size.radiusMd, padding: '11px 26px' }}>
              Start free
            </Link>
          </div>
          <div style={{ marginTop: size.sp2, fontSize: 12.5, color: color.textDim }}>Two weeks free, no card needed</div>
        </div>
      </main>
    </div>
  )
}
