import React, { useEffect, useRef, useState } from 'react'
import { color, font, size } from '../../theme/tokens'
import { client } from '../../api/client'

/** "Get in touch" — built by JavaScript, on purpose.
 *
 *  Nothing here exists until a visitor asks for it: the page ships a single
 *  button, and the fields are created only after it is pressed. A scraper
 *  reading the HTML finds no form, no field names and no action to post to,
 *  which stops the commonest bots — the ones that never run scripts — without
 *  costing a human anything.
 *
 *  Behind that: a honeypot field people never see, and the time the form spent
 *  on screen (a person cannot read and fill this in under three seconds; a
 *  script does it in milliseconds). Both are client-asserted and therefore
 *  advisory — the server rate-limits by IP as well, which is the only part
 *  that survives someone who has read this file. Deliberately not a CAPTCHA:
 *  it taxes every honest visitor and hands their behaviour to a third party,
 *  which is a bad trade at this volume.
 */
export function ContactForm() {
  const [open, setOpen] = useState(false)
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const openedAt = useRef<number>(0)
  const firstField = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    openedAt.current = Date.now()
    firstField.current?.focus()
  }, [open])

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    setBusy(true)
    setError(null)
    try {
      await client.post('/contact/', {
        name: String(f.get('name') ?? ''),
        email: String(f.get('email') ?? ''),
        company: String(f.get('company') ?? ''),
        message: String(f.get('message') ?? ''),
        company_website: String(f.get('company_website') ?? ''),
        elapsedMs: Date.now() - openedAt.current,
      })
      setSent(true)
    } catch (err) {
      setError('That did not go through. Email nikolaus.correll@gmail.com directly and it will reach us.')
    } finally { setBusy(false) }
  }

  const field: React.CSSProperties = {
    background: color.bgInput, border: `1px solid ${color.border}`,
    borderRadius: size.radius, color: color.textPrimary,
    padding: '9px 11px', fontSize: 13.5, fontFamily: font.sans, width: '100%',
    boxSizing: 'border-box',
  }
  const label: React.CSSProperties = {
    fontSize: 10.5, fontFamily: font.mono, letterSpacing: '0.08em',
    color: color.textDim, marginBottom: 4, display: 'block',
  }

  return (
    <section id="contact" style={{
      borderTop: `1px solid ${color.border}`, padding: `${size.sp8} ${size.sp6}`,
      background: color.bgDeep,
    }}>
      <div style={{ maxWidth: 640, margin: '0 auto', textAlign: 'center' }}>
        <h2 style={{ fontSize: 26, color: color.textPrimary, margin: 0 }}>
          Talk to us about your line
        </h2>
        <p style={{ fontSize: 15, color: color.textSecondary, lineHeight: 1.65,
                    margin: `${size.sp3} 0 ${size.sp5}` }}>
          Questions about whether Taktline fits your floor, what it would take to map
          your process, or anything else — a real person reads these.
        </p>

        {sent ? (
          <div style={{
            background: color.bgCard, border: `1px solid ${color.statusRunning}55`,
            borderRadius: size.radiusMd, padding: size.sp5,
            fontSize: 14, color: color.textPrimary, lineHeight: 1.6,
          }}>
            Thank you — that arrived. We usually reply within a working day.
          </div>
        ) : !open ? (
          <button
            onClick={() => setOpen(true)}
            style={{
              background: color.bluePrimary, border: 'none', borderRadius: size.radiusMd,
              color: '#fff', fontSize: 15, fontWeight: 600, padding: '12px 26px',
              cursor: 'pointer', fontFamily: font.sans,
            }}
          >
            Write to us
          </button>
        ) : (
          <form onSubmit={submit} style={{
            textAlign: 'left', display: 'flex', flexDirection: 'column', gap: size.sp3,
            background: color.bgCard, border: `1px solid ${color.border}`,
            borderRadius: size.radiusMd, padding: size.sp5,
          }}>
            <div style={{ display: 'flex', gap: size.sp3, flexWrap: 'wrap' }}>
              <label style={{ flex: '1 1 200px' }}>
                <span style={label}>YOUR NAME</span>
                <input ref={firstField} name="name" required maxLength={120} style={field} />
              </label>
              <label style={{ flex: '1 1 200px' }}>
                <span style={label}>EMAIL</span>
                <input name="email" type="email" required style={field} />
              </label>
            </div>
            <label>
              <span style={label}>COMPANY (OPTIONAL)</span>
              <input name="company" maxLength={160} style={field} />
            </label>
            <label>
              <span style={label}>MESSAGE</span>
              <textarea name="message" required minLength={10} maxLength={4000} rows={5}
                        style={{ ...field, resize: 'vertical' }} />
            </label>

            {/* The honeypot. Hidden from people every way that matters — off
                screen, not tabbable, told to assistive tech to ignore it — and
                left plainly attractive to anything that fills forms by name. */}
            <div aria-hidden="true" style={{
              position: 'absolute', left: '-9999px', width: 1, height: 1, overflow: 'hidden',
            }}>
              <label>
                Company website
                <input name="company_website" tabIndex={-1} autoComplete="off" />
              </label>
            </div>

            {error && (
              <div style={{ fontSize: 12.5, color: color.statusFault, lineHeight: 1.5 }}>
                {error}
              </div>
            )}
            <div style={{ display: 'flex', gap: size.sp3, alignItems: 'center' }}>
              <button type="submit" disabled={busy} style={{
                background: busy ? `${color.bluePrimary}60` : color.bluePrimary,
                border: 'none', borderRadius: size.radiusMd, color: '#fff',
                fontSize: 14.5, fontWeight: 600, padding: '10px 22px',
                cursor: busy ? 'not-allowed' : 'pointer', fontFamily: font.sans,
              }}>
                {busy ? 'Sending…' : 'Send'}
              </button>
              <span style={{ fontSize: 11.5, color: color.textDim, lineHeight: 1.5 }}>
                We use your address to reply, and for nothing else.
              </span>
            </div>
          </form>
        )}
      </div>
    </section>
  )
}
