import React, { useState } from 'react'
import { client } from '../api/client'
import { useAuthStore } from '../store/auth.store'
import { color, font, shadow, size } from '../theme/tokens'

/** "Contact support" from the help menu: a subject, a message, send.
 *
 * The server attaches who is asking (session-verified email + company), so
 * the form asks for nothing the app already knows — the shortest path from
 * "something is wrong" to a sentence in the maintainer's inbox.
 */
export function SupportDialog({ onClose }: { onClose: () => void }) {
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = async () => {
    setBusy(true); setError(null)
    try {
      await client.post('/contact/support', {
        subject: subject.trim(), message: message.trim(),
        companyId: activeCompanyId ?? undefined,
      })
      setSent(true)
    } catch (e: any) {
      setError(e?.response?.status === 429
        ? 'A few messages are already on their way — give it an hour.'
        : 'That did not send. Please try again in a moment.')
    } finally {
      setBusy(false)
    }
  }

  const field: React.CSSProperties = {
    width: '100%', padding: '8px 10px', fontSize: 13,
    background: color.bgInput, color: color.textPrimary,
    border: `1px solid ${color.border}`, borderRadius: size.radius,
    fontFamily: font.sans,
  }

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, zIndex: 9500, background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: 440, maxWidth: 'calc(100vw - 32px)', background: color.bgPanel,
        border: `1px solid ${color.border}`, borderRadius: size.radiusMd,
        boxShadow: shadow.lg, padding: size.sp5,
      }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: color.textPrimary,
                      marginBottom: size.sp2 }}>
          Contact support
        </div>

        {sent ? (
          <>
            <p style={{ fontSize: 13, color: color.textSecondary, lineHeight: 1.6 }}>
              Sent. The reply goes to your account&rsquo;s email address.
            </p>
            <button onClick={onClose} style={{
              marginTop: size.sp3, padding: '7px 14px', fontSize: 12.5,
              background: color.bluePrimary, color: '#fff', border: 'none',
              borderRadius: size.radius, cursor: 'pointer',
            }}>
              Close
            </button>
          </>
        ) : (
          <>
            <p style={{ fontSize: 12.5, color: color.textDim, margin: `0 0 ${size.sp3}`,
                        lineHeight: 1.5 }}>
              Goes straight to the maintainer, with your account and company
              attached so you don&rsquo;t have to explain who you are.
            </p>
            <input
              value={subject} onChange={(e) => setSubject(e.target.value)}
              placeholder="What is it about?" autoFocus maxLength={160} style={field}
            />
            <textarea
              value={message} onChange={(e) => setMessage(e.target.value)}
              placeholder="What happened, what did you expect?"
              rows={6} maxLength={8000}
              style={{ ...field, marginTop: size.sp2, resize: 'vertical' }}
            />
            {error && (
              <div style={{ marginTop: size.sp2, fontSize: 12.5, color: color.statusFault }}>
                {error}
              </div>
            )}
            <div style={{ display: 'flex', gap: size.sp2, marginTop: size.sp3 }}>
              <button
                onClick={send}
                disabled={busy || !subject.trim() || message.trim().length < 5}
                style={{
                  padding: '7px 16px', fontSize: 12.5, border: 'none',
                  borderRadius: size.radius, cursor: busy ? 'default' : 'pointer',
                  background: color.bluePrimary, color: '#fff',
                  opacity: busy || !subject.trim() || message.trim().length < 5 ? 0.5 : 1,
                }}>
                {busy ? 'Sending…' : 'Send'}
              </button>
              <button onClick={onClose} style={{
                background: 'none', border: 'none', color: color.textDim,
                fontSize: 12.5, cursor: 'pointer',
              }}>
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
