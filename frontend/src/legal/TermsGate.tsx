import React, { useCallback, useState } from 'react'
import { color, font, size } from '../theme/tokens'
import { TERMS, TERMS_EFFECTIVE, TERMS_VERSION } from './terms'

/** The agreement, in a pane you must actually reach the end of.
 *
 *  The checkbox stays disabled until the text has been scrolled to the bottom,
 *  so "I have read it" is at least true of the scrollbar. That is worth more
 *  than a bare tick-box: it is the difference between a term someone had the
 *  opportunity to read and one buried behind a link nobody opened.
 *
 *  A pane shorter than its own content is treated as already read — otherwise
 *  a tall screen (or a zoomed-out one) would show the whole agreement at once
 *  and then refuse to let anyone continue, which is the sort of thing that
 *  makes people give up on signing up rather than read more carefully.
 */
export function TermsGate({ accepted, onAccept }: {
  accepted: boolean
  onAccept: (v: boolean) => void
}) {
  const [readToEnd, setReadToEnd] = useState(false)

  const check = useCallback((el: HTMLDivElement | null) => {
    if (!el) return
    const atEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - 24
    if (atEnd) setReadToEnd(true)
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
      <div style={{
        fontSize: 10.5, fontFamily: font.mono, letterSpacing: '0.08em',
        color: color.textDim, display: 'flex', justifyContent: 'space-between',
      }}>
        <span>END-USER AGREEMENT</span>
        <span>v{TERMS_VERSION}</span>
      </div>

      <div
        // Measured on mount too: a pane taller than its own content can
        // never be scrolled, and would otherwise lock the box forever.
        ref={check}
        onScroll={(e) => check(e.currentTarget)}
        style={{
          height: 190, overflowY: 'auto',
          background: color.bgInput, border: `1px solid ${color.border}`,
          borderRadius: size.radius, padding: `${size.sp3} ${size.sp4}`,
          fontSize: 12, lineHeight: 1.6, color: color.textSecondary,
        }}
      >
        <div style={{ fontSize: 11, color: color.textDim, marginBottom: size.sp3 }}>
          Effective {TERMS_EFFECTIVE}. Please read to the end — the box below unlocks when you do.
        </div>
        {TERMS.map((s) => (
          <div key={s.heading} style={{ marginBottom: size.sp3 }}>
            <div style={{ fontWeight: 600, color: color.textPrimary, marginBottom: 3 }}>
              {s.heading}
            </div>
            {s.paragraphs?.map((p, i) => (
              <p key={i} style={{ margin: '0 0 6px' }}>{p}</p>
            ))}
            {s.bullets && (
              <ul style={{ margin: '0 0 6px', paddingLeft: 18 }}>
                {s.bullets.map((b, i) => <li key={i} style={{ marginBottom: 3 }}>{b}</li>)}
              </ul>
            )}
          </div>
        ))}
        <div style={{ color: color.textDim, fontStyle: 'italic' }}>
          — end of agreement —
        </div>
      </div>

      <label style={{
        display: 'flex', alignItems: 'flex-start', gap: 8,
        cursor: readToEnd ? 'pointer' : 'not-allowed',
        opacity: readToEnd ? 1 : 0.55,
      }}>
        <input
          type="checkbox"
          checked={accepted}
          disabled={!readToEnd}
          onChange={(e) => onAccept(e.target.checked)}
          style={{ marginTop: 2, width: 15, height: 15, flexShrink: 0,
                   cursor: readToEnd ? 'pointer' : 'not-allowed' }}
        />
        <span style={{ fontSize: 12, color: color.textSecondary, lineHeight: 1.5 }}>
          I have read and accept the end-user agreement. I understand my line and every decision
          in it stay my responsibility, that the Service is provided without warranty, and that my
          data is stored on Taktline’s servers and may be used to improve the product and to give
          me data-driven advice.
          {!readToEnd && (
            <b style={{ color: color.textDim }}> — scroll to the end of the text to enable this.</b>
          )}
        </span>
      </label>
    </div>
  )
}
