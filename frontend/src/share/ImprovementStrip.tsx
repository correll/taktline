import { useEffect, useState } from 'react'
import { shareApi, type ImprovementPreview } from '../api/share.api'
import { color, font, size } from '../theme/tokens'
import { ShareModal } from './ShareModal'

/**
 * "Your line got better this week." Shown at the foot of the line doctor's
 * report — and only when there is something true to say.
 *
 * When nothing moved, this renders nothing at all. A permanent "no improvement
 * yet" strip would be a standing reproach in a panel whose whole job is to be
 * useful, and it would train people to stop reading the bottom of the report.
 * The trigger for a share should be the achievement, not the button.
 *
 * Publishing is a second, explicit step: the numbers are computed server-side
 * and shown here first, so nobody posts a figure they have not seen.
 */
export function ImprovementStrip() {
  const [preview, setPreview] = useState<ImprovementPreview | null>(null)
  const [publishedId, setPublishedId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    shareApi.improvement('1w')
      .then((p) => { if (live) setPreview(p) })
      .catch(() => { /* offline, or no permission — say nothing */ })
    return () => { live = false }
  }, [])

  if (!preview?.available) return null

  const publish = async () => {
    setBusy(true)
    setFailed(null)
    try {
      const card = await shareApi.publishImprovement(preview.window ?? '1w')
      setPublishedId(card.id)
    } catch {
      setFailed('Could not publish just now — try again in a moment.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{
      marginTop: size.sp5, paddingTop: size.sp4, borderTop: `1px solid ${color.border}`,
    }}>
      <div style={{
        fontSize: 10, fontFamily: font.mono, letterSpacing: '0.12em', color: color.statusRunning,
      }}>
        THIS WEEK AGAINST LAST
      </div>

      <div style={{ marginTop: size.sp2, fontSize: 14, color: color.textPrimary, lineHeight: 1.4 }}>
        {preview.headline}
      </div>

      <div style={{
        marginTop: size.sp2, display: 'flex', alignItems: 'baseline', gap: size.sp2,
        fontSize: 13, color: color.textSecondary,
      }}>
        <span>{preview.metric}</span>
        <span style={{ color: color.textDim }}>{preview.before}</span>
        <span style={{ color: color.textDim }}>→</span>
        <span style={{ color: color.statusRunning, fontWeight: 600 }}>{preview.after}</span>
      </div>

      <button
        onClick={publish}
        disabled={busy}
        style={{
          marginTop: size.sp3, background: 'none', border: `1px solid ${color.border}`,
          borderRadius: size.radius, color: color.textSecondary, fontSize: 12,
          padding: '5px 12px', cursor: busy ? 'default' : 'pointer', fontFamily: 'inherit',
        }}
      >
        {busy ? 'Preparing…' : 'Share this'}
      </button>

      {failed && (
        <div style={{ marginTop: size.sp2, fontSize: 11, color: color.statusFault }}>{failed}</div>
      )}

      {publishedId && (
        <ShareModal
          target={{
            id: publishedId,
            kind: 'result',
            suggested:
              `${preview.headline}. ${preview.metric} went from ${preview.before} to ` +
              `${preview.after} — measured on the floor, not estimated.`,
            subject: `${preview.metric}: ${preview.before} → ${preview.after}`,
          }}
          onClose={() => setPublishedId(null)}
        />
      )}
    </div>
  )
}
