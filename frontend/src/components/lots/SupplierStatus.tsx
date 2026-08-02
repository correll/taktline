import { useEffect, useState } from 'react'
import { color, font, size } from '../../theme/tokens'

/**
 * A supplier's progress, on your board.
 *
 * The other half of the tracking link: they publish, you paste it in, and the
 * black box where "waiting on castings" used to sit becomes "60%, at Grinding,
 * four minutes ago". It is also the reason a supplier invitation is worth
 * sending — without this, inviting a supplier is asking them to adopt your
 * software as a favour.
 *
 * **The fetch happens here, in the browser, never on our server.** The URL comes
 * from a user, and a server that follows user-supplied URLs is the whole SSRF
 * class; doing it in the browser avoids it rather than fencing it. Cookies are
 * never sent cross-origin, so this can only ever read the public view — the same
 * thing the supplier's customer sees, which is exactly the intent.
 */

interface Status {
  reference: string
  product: string
  quantity: number
  status: string
  percent: number
  stepIndex: number | null
  stepTotal: number | null
  steps: { name: string; current: boolean; done: boolean }[] | null
  updatedAt: string | null
}

const REFRESH_MS = 120_000

/** `/o/<id>/<token>` → `/track/<id>/<token>`. Mirrors `core/network.status_url`;
 *  the value was already validated server-side before it was stored. */
function statusUrl(trackingUrl: string): string | null {
  try {
    const u = new URL(trackingUrl)
    if (!/^https?:$/.test(u.protocol)) return null
    return `${u.origin}${u.pathname.replace('/o/', '/track/')}`
  } catch { return null }
}

export function SupplierStatus({ url }: { url: string }) {
  const [data, setData] = useState<Status | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const endpoint = statusUrl(url)
    if (!endpoint) { setFailed(true); return }
    let live = true
    const load = () => {
      // `credentials: 'omit'` is the default and is load-bearing: it is what
      // guarantees this reads the customer view and nothing privileged, even
      // when the supplier happens to be on the same host we are.
      fetch(endpoint, { headers: { Accept: 'application/json' } })
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((d) => { if (live) { setData(d); setFailed(false) } })
        .catch(() => { if (live) setFailed(true) })
    }
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => { live = false; clearInterval(t) }
  }, [url])

  if (failed && !data) {
    return (
      <div style={{ fontSize: 11.5, color: color.textDim, lineHeight: 1.5 }}>
        Could not read the supplier’s status. They may have turned tracking off,
        or the job may be finished and cleared.
      </div>
    )
  }
  if (!data) {
    return <div style={{ fontSize: 11.5, color: color.textDim }}>Checking…</div>
  }

  const done = data.status === 'completed'
  const here = data.steps?.find((s) => s.current)
  const tone = done ? color.statusRunning : color.bluePrimary

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp2, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 18, fontWeight: 600, color: tone }}>
          {done ? 'Ready' : `${data.percent}%`}
        </span>
        <span style={{ fontSize: 12, color: color.textSecondary }}>
          {data.product}
          {data.reference && (
            <span style={{ fontFamily: font.mono, color: color.textDim }}> · {data.reference}</span>
          )}
        </span>
      </div>

      <div style={{ height: 5, borderRadius: 3, background: color.border, overflow: 'hidden' }}>
        <div style={{ width: `${data.percent}%`, height: '100%', background: tone,
                      transition: 'width 500ms ease' }} />
      </div>

      <div style={{ fontSize: 11.5, color: color.textDim }}>
        {here ? `At ${here.name}` : data.stepTotal && data.stepIndex !== null
          ? `Step ${data.stepIndex + 1} of ${data.stepTotal}` : 'In production'}
        {data.updatedAt && ` · moved ${relative(data.updatedAt)}`}
      </div>
    </div>
  )
}

function relative(iso: string): string {
  const when = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  const mins = Math.max(0, Math.round((Date.now() - when.getTime()) / 60_000))
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

/**
 * Paste, clear, and a word about what it is.
 *
 * Collapsed to one line until there is something to show. Most lots are not
 * waiting on a supplier, and an empty input with two lines of explanation on
 * every lot modal is a tax paid by everyone to serve the few — the same reason
 * the customer-link block only appears once tracking is switched on.
 */
export function SupplierLinkField({ value, onChange, disabled, hint }: {
  value?: string | null
  onChange: (next: string | null) => void
  disabled?: boolean
  /** Shown beside the collapsed affordance — what linking one buys you here. */
  hint?: string
}) {
  const [draft, setDraft] = useState(value ?? '')
  const [open, setOpen] = useState(false)
  useEffect(() => { setDraft(value ?? '') }, [value])

  if (!value && !open) {
    if (disabled) return null
    return (
      <button
        onClick={() => setOpen(true)}
        style={{ ...btn, alignSelf: 'flex-start', color: color.textDim }}
      >
        + Link a supplier{hint ? ` — ${hint}` : ''}
      </button>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: size.sp2 }}>
      {value && <SupplierStatus url={value} />}
      <div style={{ display: 'flex', gap: size.sp2 }}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Paste your supplier’s tracking link"
          disabled={disabled}
          style={{
            flex: 1, minWidth: 0, background: color.bgCard,
            border: `1px solid ${color.border}`, borderRadius: size.radius,
            color: color.textPrimary, padding: '5px 8px', fontSize: 12,
            fontFamily: 'inherit',
          }}
        />
        <button
          onClick={() => onChange(draft.trim() || null)}
          disabled={disabled || draft.trim() === (value ?? '')}
          style={btn}
        >
          {value ? 'Update' : 'Link'}
        </button>
        {value && (
          <button onClick={() => { setDraft(''); onChange(null) }} disabled={disabled}
                  style={btn}>
            Clear
          </button>
        )}
      </div>
    </div>
  )
}

const btn = {
  background: 'none', border: `1px solid ${color.border}`, borderRadius: size.radius,
  color: color.textSecondary, fontSize: 11, padding: '3px 10px', cursor: 'pointer',
  fontFamily: 'inherit', flexShrink: 0,
} as const
