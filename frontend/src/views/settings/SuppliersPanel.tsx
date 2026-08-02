import { useEffect, useState } from 'react'
import { networkApi, type SupplierInvite } from '../../api/network.api'
import { color, font, size } from '../../theme/tokens'

/**
 * Invite your suppliers to publish status.
 *
 * This is the growth loop, and it is worth being honest about why it can work
 * where "invite your friends" cannot: the person being invited is being asked
 * for something their customer already wants from them anyway — an answer to
 * "where is my order?" — and the answer is a link, not a meeting. The invitation
 * costs the supplier nothing to evaluate and saves them the phone call.
 *
 * What we deliberately do NOT do: offer the inviter a discount, a credit, or a
 * referral fee. Paying for introductions turns a supplier's inbox into spam
 * addressed by a customer they cannot ignore, and the thing being asked for
 * stops being "here is a better way to answer me" and becomes "do me a favour
 * so I get a month free". The visibility is the reward.
 */
export default function SuppliersPanel() {
  const [invites, setInvites] = useState<SupplierInvite[]>([])
  const [email, setEmail] = useState('')
  const [supplies, setSupplies] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = () => { networkApi.list().then(setInvites).catch(() => {}) }
  useEffect(load, [])

  const send = async () => {
    setBusy(true); setError(null)
    try {
      await networkApi.invite({ email: email.trim(), supplies: supplies.trim() })
      setEmail(''); setSupplies(''); load()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Could not send that invitation.')
    } finally { setBusy(false) }
  }

  return (
    <section>
      <p style={{ margin: `0 0 ${size.sp4}`, fontSize: 12.5,
                  color: color.textSecondary, lineHeight: 1.6, maxWidth: 620 }}>
        Ask a supplier for a tracking link and their progress appears on the lot
        or station that is waiting for it — no phone call, no “any update?” email.
        They see nothing of your floor; you see nothing of theirs beyond the job
        they are making for you.
      </p>

      <div style={{ display: 'flex', gap: size.sp2, flexWrap: 'wrap', alignItems: 'center',
                    marginBottom: size.sp4 }}>
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="supplier@example.com"
          type="email"
          style={{ ...input, minWidth: 240 }}
        />
        <input
          value={supplies}
          onChange={(e) => setSupplies(e.target.value)}
          placeholder="what they supply (castings…)"
          style={{ ...input, minWidth: 200 }}
        />
        <button
          onClick={send}
          disabled={busy || !email.includes('@')}
          style={{
            background: color.bluePrimary, color: color.white, border: 'none',
            borderRadius: size.radius, padding: '6px 14px', fontSize: 12.5,
            fontWeight: 600, cursor: busy || !email.includes('@') ? 'default' : 'pointer',
            opacity: busy || !email.includes('@') ? 0.5 : 1, fontFamily: 'inherit',
          }}
        >
          {busy ? 'Sending…' : 'Invite'}
        </button>
      </div>

      {error && (
        <div style={{ fontSize: 12, color: color.statusFault, marginBottom: size.sp3 }}>{error}</div>
      )}

      {invites.length === 0 ? (
        <div style={{ fontSize: 12, color: color.textDim }}>Nobody invited yet.</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <tbody>
            {invites.map((i) => (
              <tr key={i.id} style={{ borderTop: `1px solid ${color.border}` }}>
                <td style={{ padding: `${size.sp2} 0`, color: color.textPrimary }}>{i.email}</td>
                <td style={{ padding: `${size.sp2} 0`, color: color.textDim }}>{i.supplies}</td>
                <td style={{ padding: `${size.sp2} 0`, fontFamily: font.mono, fontSize: 11,
                             color: i.accepted ? color.statusRunning : color.textDim }}>
                  {i.accepted ? 'on Taktline' : 'invited'}
                </td>
                <td style={{ padding: `${size.sp2} 0`, textAlign: 'right' }}>
                  <button
                    onClick={() => networkApi.forget(i.id).then(load).catch(() => {})}
                    style={{ background: 'none', border: 'none', color: color.textDim,
                             fontSize: 11, cursor: 'pointer', fontFamily: 'inherit' }}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

const input = {
  background: color.bgCard, border: `1px solid ${color.border}`,
  borderRadius: size.radius, color: color.textPrimary, padding: '6px 9px',
  fontSize: 12.5, fontFamily: 'inherit',
} as const
