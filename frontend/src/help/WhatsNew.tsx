import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { LATEST, RELEASES, SEEN_KEY, unseen, type Release } from './changelog'
import { useHelpStore } from './helpStore'
import { color, font, shadow, size } from '../theme/tokens'

/**
 * "What's new", shown once per release.
 *
 * It fires on the *changelog* changing, not on a deploy: see `changelog.ts` for
 * why. It also never fires on a first visit — a new account meets the product,
 * not a list of things that changed before they arrived — and it stays reachable
 * from the help menu afterwards, so dismissing it does not lose it.
 *
 * The seen marker is written when it is *shown*, not when it is dismissed. The
 * same bug already cost this codebase a bug report once (the daily tip
 * reappeared on every page load until the user clicked something), and the
 * failure mode here is worse: a modal over the board every time somebody
 * refreshes.
 */
export function WhatsNew() {
  const [releases, setReleases] = useState<Release[]>([])
  // Same precedence as the daily tip: the first-run welcome and the guided tour
  // both come first. Stacking a changelog on top of "Welcome to Taktline" is
  // two dialogs arguing over somebody's first thirty seconds.
  const calloutDismissed = useHelpStore((s) => s.calloutDismissed)
  const tourActive = useHelpStore((s) => s.tourActive)

  useEffect(() => {
    let stored: string | null = null
    try { stored = localStorage.getItem(SEEN_KEY) } catch { /* private mode */ }
    const pending = unseen(stored)
    try { localStorage.setItem(SEEN_KEY, LATEST) } catch { /* ignore */ }
    if (pending.length) setReleases(pending)
  }, [])

  if (!releases.length || !calloutDismissed || tourActive) return null
  return <ReleaseDialog releases={releases} onClose={() => setReleases([])} />
}

/** The same content, opened deliberately from the help menu. */
export function WhatsNewDialog({ onClose }: { onClose: () => void }) {
  return <ReleaseDialog releases={RELEASES} onClose={onClose} />
}

function ReleaseDialog({ releases, onClose }: { releases: Release[]; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 9400, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: size.sp4,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="What's new in Taktline"
        style={{
          width: 560, maxWidth: '100%', maxHeight: '82vh', overflowY: 'auto',
          background: color.bgPanel, border: `1px solid ${color.border}`,
          borderRadius: size.radiusLg, boxShadow: shadow.lg, padding: size.sp5,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: size.sp4 }}>
          <span style={{
            fontSize: 10, fontFamily: font.mono, letterSpacing: '0.12em',
            textTransform: 'uppercase', color: color.textDim,
          }}>
            What&rsquo;s new
          </span>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              marginLeft: 'auto', background: 'none', border: 'none', color: color.textDim,
              fontSize: 20, lineHeight: 1, cursor: 'pointer', padding: 0,
            }}
          >
            ×
          </button>
        </div>

        {releases.map((r) => (
          <section key={r.id} style={{ marginBottom: size.sp6 }}>
            <h2 style={{
              margin: 0, fontSize: 17, fontWeight: 600, lineHeight: 1.3,
              color: color.textPrimary,
            }}>
              {r.headline}
            </h2>
            <div style={{ marginTop: 2, fontSize: 11.5, color: color.textDim }}>{r.date}</div>

            {r.added && <Group label="New" tone={color.blueBright} items={r.added} />}
            {r.fixed && <Group label="Fixed" tone={color.statusRunning} items={r.fixed} />}
          </section>
        ))}

        <button
          onClick={onClose}
          style={{
            background: color.bluePrimary, color: color.white, border: 'none',
            borderRadius: size.radius, padding: '8px 18px', fontSize: 13,
            fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
          }}
        >
          Got it
        </button>
      </div>
    </div>,
    document.body,
  )
}

function Group({ label, tone, items }: { label: string; tone: string; items: string[] }) {
  return (
    <div style={{ marginTop: size.sp4 }}>
      <div style={{
        fontSize: 10, fontFamily: font.mono, letterSpacing: '0.1em',
        textTransform: 'uppercase', color: tone, marginBottom: size.sp2,
      }}>
        {label}
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: 'none',
                   display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
        {items.map((text) => (
          <li key={text} style={{
            display: 'flex', gap: size.sp2, fontSize: 13.5, lineHeight: 1.6,
            color: color.textSecondary,
          }}>
            <span aria-hidden="true" style={{ color: tone }}>·</span>
            <span>{text}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
