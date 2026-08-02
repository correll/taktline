import { useState } from 'react'
import { conceptForAnchor } from '../help/concepts'
import { color, size } from '../theme/tokens'
import { ShareModal } from './ShareModal'

/**
 * The share affordance on a manual section, driven by the anchor rather than
 * placed by hand at each heading: adding a concept to `concepts.ts` gives it a
 * button, and there is no way to forget one or to leave a dead one behind after
 * a section is renamed.
 *
 * It renders nothing at all for a heading that is not a shareable concept,
 * which is most of them — a share button on every heading is exactly the noise
 * this feature is trying to avoid.
 */
export function ShareConceptButton({ anchor }: { anchor?: string }) {
  const [open, setOpen] = useState(false)
  const concept = anchor ? conceptForAnchor(anchor) : undefined
  if (!concept) return null

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title={`Share "${concept.title}"`}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          background: 'none', border: `1px solid ${color.border}`,
          borderRadius: size.radiusFull, color: color.textDim,
          fontSize: 10.5, cursor: 'pointer', padding: '2px 10px',
          flexShrink: 0, fontFamily: 'inherit',
        }}
      >
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
          <path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" />
        </svg>
        Share
      </button>

      {open && (
        <ShareModal
          target={{
            id: concept.id,
            kind: 'idea',
            suggested: `${concept.claim}\n\n${concept.body}`,
            subject: concept.title,
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}
