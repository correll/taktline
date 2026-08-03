import React from 'react'
import { Link } from 'react-router-dom'
import { TaktlineLogo } from '../../components/TaktlineLogo'
import { PRIVACY, PRIVACY_EFFECTIVE, PRIVACY_VERSION } from '../../legal/privacy'
import { color, font, size } from '../../theme/tokens'

/** The privacy policy on its own page — linkable, readable and printable
 *  without an account, which is also what App Store review requires of it. */
export default function PrivacyView() {
  return (
    <div style={{ minHeight: '100vh', background: color.bgDeep }}>
      <div style={{ borderBottom: `1px solid ${color.border}`, padding: size.sp4 }}>
        <div style={{ maxWidth: 780, margin: '0 auto', display: 'flex', alignItems: 'center', gap: size.sp4 }}>
          <Link to="/" style={{ display: 'flex', color: color.textPrimary }} aria-label="Taktline home">
            <TaktlineLogo height={22} color={color.textPrimary} />
          </Link>
          <span style={{ fontSize: 12, fontFamily: font.mono, color: color.textDim,
                         letterSpacing: '0.08em' }}>
            PRIVACY POLICY · v{PRIVACY_VERSION}
          </span>
        </div>
      </div>
      <div style={{ maxWidth: 780, margin: '0 auto', padding: `${size.sp8} ${size.sp6}` }}>
        <h1 style={{ fontSize: 28, color: color.textPrimary, margin: 0 }}>Privacy policy</h1>
        <p style={{ fontSize: 13, color: color.textDim, marginTop: size.sp2 }}>
          Effective {PRIVACY_EFFECTIVE}
        </p>
        {PRIVACY.map((s) => (
          <section key={s.heading} style={{ marginTop: size.sp6 }}>
            <h2 style={{ fontSize: 16, color: color.textPrimary, marginBottom: size.sp2 }}>
              {s.heading}
            </h2>
            {s.paragraphs?.map((p, i) => (
              <p key={i} style={{ fontSize: 14, lineHeight: 1.7, color: color.textSecondary,
                                  margin: '0 0 10px' }}>{p}</p>
            ))}
            {s.bullets && (
              <ul style={{ paddingLeft: 20, margin: '0 0 10px' }}>
                {s.bullets.map((b, i) => (
                  <li key={i} style={{ fontSize: 14, lineHeight: 1.7, color: color.textSecondary,
                                       marginBottom: 6 }}>{b}</li>
                ))}
              </ul>
            )}
          </section>
        ))}
        <div style={{ marginTop: size.sp8, fontSize: 13 }}>
          <Link to="/terms" style={{ color: color.blueBright, textDecoration: 'none' }}>
            The end-user agreement →
          </Link>
        </div>
      </div>
    </div>
  )
}
