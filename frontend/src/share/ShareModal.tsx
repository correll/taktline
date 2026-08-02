import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { color, font, shadow, size } from '../theme/tokens'
import { cardUrl, copyText, linkedInUrl, mailtoUrl, shareUrl } from './shareLinks'

/**
 * The one share surface in the app.
 *
 * It shows the card that will actually appear — fetched from the same URL the
 * crawler will fetch, not a CSS mock-up of it — because the single worst thing
 * a share button can do is post something the sharer did not expect. The
 * suggested text is editable for the same reason.
 *
 * There are exactly three places this opens from (the daily tip, a flow-science
 * concept in the manual, and a measured improvement). That restraint is the
 * feature: a share button on everything is noise, and noise is what teaches
 * people to stop seeing them.
 */

export interface ShareTarget {
  /** Path segment of `/i/<id>` — the permanent public URL. */
  id: string
  /** Modal heading: what kind of thing this is. */
  kind: string
  /** Pre-filled post text, without the URL (appended on copy). */
  suggested: string
  /** Email subject. */
  subject: string
}

export function ShareModal({ target, onClose }: { target: ShareTarget; onClose: () => void }) {
  const [text, setText] = useState(target.suggested)
  const [note, setNote] = useState<string | null>(null)
  const [imageFailed, setImageFailed] = useState(false)
  const url = shareUrl(target.id)
  const full = `${text}\n\n${url}`

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const flash = (m: string) => { setNote(m); window.setTimeout(() => setNote(null), 2200) }

  const copy = async (what: string, label: string) => {
    flash(await copyText(what) ? label : 'Could not reach the clipboard — select the text above')
  }

  const toLinkedIn = async () => {
    // Copy first: the composer opens with the link only, and the text has to be
    // pasted. Doing it in the other order loses the copy to the popup blocker
    // dance on some browsers.
    const ok = await copyText(full)
    window.open(linkedInUrl(url), '_blank', 'noopener,noreferrer')
    flash(ok ? 'Text copied — paste it into the post' : 'Opened LinkedIn — copy your text above')
  }

  const btn = (primary = false) => ({
    display: 'inline-flex', alignItems: 'center', gap: size.sp2, cursor: 'pointer',
    border: `1px solid ${primary ? color.bluePrimary : color.border}`,
    background: primary ? color.bluePrimary : 'transparent',
    color: primary ? color.white : color.textSecondary,
    borderRadius: size.radius, padding: '8px 14px', fontSize: 13,
    fontWeight: primary ? 600 : 400,
  } as const)

  // Rendered into <body>. The daily tip is centred with `translateX(-50%)`,
  // and a transformed ancestor becomes the containing block for `position:
  // fixed` — so an inline modal was laid out against the tip card and its
  // buttons fell below the fold. A portal makes the placement independent of
  // wherever it is opened from, which every future caller inherits.
  return createPortal(
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 9500, background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: size.sp4,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`Share this ${target.kind}`}
        style={{
          width: 620, maxWidth: '100%', maxHeight: '90vh', overflowY: 'auto',
          background: color.bgPanel, border: `1px solid ${color.border}`,
          borderRadius: size.radiusLg, boxShadow: shadow.lg, padding: size.sp5,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: size.sp4 }}>
          <span style={{
            fontSize: 10, fontFamily: font.mono, letterSpacing: '0.12em',
            textTransform: 'uppercase', color: color.textDim,
          }}>
            Share this {target.kind}
          </span>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              marginLeft: 'auto', background: 'none', border: 'none',
              color: color.textDim, fontSize: 20, lineHeight: 1, cursor: 'pointer', padding: 0,
            }}
          >
            ×
          </button>
        </div>

        {imageFailed ? (
          <div style={{
            border: `1px dashed ${color.border}`, borderRadius: size.radius,
            padding: size.sp5, fontSize: 12, color: color.textDim, textAlign: 'center',
          }}>
            The preview image could not be loaded, but the link still works.
          </div>
        ) : (
          <img
            src={cardUrl(target.id)}
            alt=""
            onError={() => setImageFailed(true)}
            style={{
              width: '100%', display: 'block', borderRadius: size.radius,
              border: `1px solid ${color.border}`,
            }}
          />
        )}

        <label style={{
          display: 'block', marginTop: size.sp4, marginBottom: size.sp2,
          fontSize: 11, color: color.textDim,
        }}>
          Suggested text — edit it to sound like you
        </label>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          style={{
            width: '100%', boxSizing: 'border-box', resize: 'vertical',
            background: color.bgCard, border: `1px solid ${color.border}`,
            borderRadius: size.radius, color: color.textPrimary,
            padding: size.sp3, fontSize: 13, lineHeight: 1.55, fontFamily: 'inherit',
          }}
        />

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: size.sp2, marginTop: size.sp4 }}>
          <button onClick={toLinkedIn} style={btn(true)}>Share on LinkedIn</button>
          <a href={mailtoUrl(target.subject, full)} style={{ ...btn(), textDecoration: 'none' }}>
            Email
          </a>
          <button onClick={() => copy(url, 'Link copied')} style={btn()}>Copy link</button>
          <button onClick={() => copy(full, 'Text and link copied')} style={btn()}>Copy text</button>
        </div>

        <div style={{ minHeight: 18, marginTop: size.sp3, fontSize: 11, color: color.blueBright }}>
          {note}
        </div>
      </div>
    </div>,
    document.body,
  )
}
