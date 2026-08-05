import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { client } from '../../api/client'
import { TaktlineLogo } from '../../components/TaktlineLogo'
import { color, font, size } from '../../theme/tokens'

/**
 * Where a shop's own customer lands: one order, and how far along it is.
 *
 * The only page in this app written for somebody who is not our customer. That
 * shapes everything about it — no login, no navigation into the product, no
 * jargon, and one answer to one question. The Taktline mark is a footnote, not
 * a banner: the visitor came to find out about their order, and a page that
 * makes them read our pitch first is a page the shop stops sending.
 *
 * It refreshes while open, because the tab someone leaves on a second monitor
 * showing "at Paint" for a job that shipped an hour ago is worse than no page.
 */

interface Step { name: string; units: number; done: boolean; current: boolean }

/** Present only for a signed-in member of the company that owns the job — an
 *  operator who scanned the QR on the card. A customer never sees this, and the
 *  token alone never grants it: the server re-checks the session and membership
 *  from scratch. */
interface WorkHandle { cardId: string; stationId: string; units: number }

interface Tracked {
  work: WorkHandle | null
  reference: string
  product: string
  quantity: number
  quantityDone: number
  status: string
  percent: number
  showSteps: boolean
  stepIndex: number | null
  stepTotal: number | null
  steps: Step[] | null
  updatedAt: string | null
}

const REFRESH_MS = 60_000

export default function TrackView() {
  const { order = '', token = '' } = useParams()
  const [data, setData] = useState<Tracked | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    let live = true
    const load = () => {
      client.get<Tracked>(`/track/${order}/${token}`)
        .then((d) => { if (live) { setData(d as unknown as Tracked); setMissing(false) } })
        .catch(() => { if (live && !data) setMissing(true) })
    }
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => { live = false; clearInterval(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order, token])

  return (
    <div style={{
      minHeight: '100vh', background: color.bgDeep, fontFamily: font.sans,
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: `${size.sp8} ${size.sp5}`,
    }}>
      <div style={{ width: 560, maxWidth: '100%' }}>
        {missing && !data && <NotFound />}
        {data && <Card data={data} />}
        {data?.work && <StartWork work={data.work} />}
        {!missing && !data && (
          <p style={{ color: color.textDim, fontSize: 14 }}>Loading…</p>
        )}

        <footer style={{
          marginTop: size.sp8, paddingTop: size.sp4,
          borderTop: `1px solid ${color.border}`,
          display: 'flex', alignItems: 'center', gap: size.sp2,
          fontSize: 12.5, color: color.textDim,
        }}>
          <TaktlineLogo mark height={14} color={color.textDim} />
          <span>
            Live from the shop floor, by{' '}
            <Link to="/" style={{ color: color.blueBright, textDecoration: 'none' }}>
              Taktline
            </Link>
          </span>
        </footer>
      </div>
    </div>
  )
}

/** The other half of the QR on a lot card.
 *
 *  The same sticker serves two people: a customer, who gets the status page, and
 *  the operator standing at the bench, who gets a way straight into the work.
 *  One label, two audiences, and neither is shown the other's affordance. */
function StartWork({ work }: { work: WorkHandle }) {
  return (
    <div style={{
      marginTop: size.sp5, padding: size.sp4,
      border: `1px dashed ${color.bluePrimary}66`, borderRadius: size.radiusMd,
      display: 'flex', alignItems: 'center', gap: size.sp4, flexWrap: 'wrap',
    }}>
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ fontSize: 13, color: color.textPrimary }}>
          You are signed in to Taktline.
        </div>
        <div style={{ fontSize: 12, color: color.textDim, marginTop: 2 }}>
          {work.units} unit{work.units === 1 ? '' : 's'} here — open it at the bench.
        </div>
      </div>
      <Link
        to={`/operator?station=${work.stationId}&card=${work.cardId}`}
        style={{
          background: color.bluePrimary, color: '#fff', textDecoration: 'none',
          borderRadius: size.radius, padding: '9px 18px', fontSize: 13.5, fontWeight: 600,
        }}
      >
        Start work
      </Link>
    </div>
  )
}

function NotFound() {
  return (
    <>
      <h1 style={h1}>This tracking link is not active</h1>
      <p style={body}>
        It may have expired, or the company may have turned tracking off. Ask them
        for a current link.
      </p>
    </>
  )
}

function Card({ data }: { data: Tracked }) {
  const done = data.status === 'completed'
  const cancelled = data.status === 'cancelled'
  const tone = cancelled ? color.statusFault
             : done ? color.statusRunning : color.bluePrimary

  return (
    <>
      <div style={{
        fontSize: 11, fontFamily: font.mono, letterSpacing: '0.12em',
        textTransform: 'uppercase', color: color.textDim,
      }}>
        Order {data.reference}
      </div>
      <h1 style={h1}>{data.product}</h1>

      <div style={{
        marginTop: size.sp5, padding: size.sp5, background: color.bgCard,
        border: `1px solid ${color.border}`, borderRadius: size.radiusLg,
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp3 }}>
          <span style={{ fontSize: 40, fontWeight: 600, color: tone }}>
            {cancelled ? '—' : `${data.percent}%`}
          </span>
          {/* "50%" beside "0 of 24 finished" reads as a contradiction — the
              percentage is position on the line, the count is units shipped.
              Until something is finished, say what is actually true. */}
          <span style={{ fontSize: 14, color: color.textSecondary }}>
            {cancelled ? 'cancelled'
              : done ? `all ${data.quantity} complete`
              : data.quantityDone === 0 ? `${data.quantity} in production`
              : `${data.quantityDone} of ${data.quantity} finished`}
          </span>
        </div>

        {!cancelled && (
          <div style={{
            marginTop: size.sp4, height: 8, borderRadius: 4,
            background: color.border, overflow: 'hidden',
          }}>
            <div style={{
              width: `${data.percent}%`, height: '100%', background: tone,
              transition: 'width 600ms ease',
            }} />
          </div>
        )}

        {/* Only when the shop has chosen to describe its process. Plenty are
            happy to say "60% done" and not to tell a customer they subcontract
            the plating. */}
        {data.steps && (
          <ol style={{
            margin: `${size.sp5} 0 0`, padding: 0, listStyle: 'none',
            display: 'flex', flexDirection: 'column', gap: size.sp2,
          }}>
            {data.steps.map((s) => (
              <li key={s.name} style={{
                display: 'flex', alignItems: 'center', gap: size.sp3,
                fontSize: 14,
                color: s.current ? color.textPrimary
                     : s.done ? color.textSecondary : color.textDim,
              }}>
                <span aria-hidden="true" style={{
                  width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                  background: s.done || s.current ? tone : 'transparent',
                  border: `1px solid ${s.done || s.current ? tone : color.border}`,
                }} />
                <span style={{ fontWeight: s.current ? 600 : 400 }}>{s.name}</span>
                {s.current && (
                  <span style={{ fontSize: 12, color: color.textDim }}>
                    · here now
                  </span>
                )}
              </li>
            ))}
          </ol>
        )}

        {!data.steps && data.stepTotal && data.stepIndex !== null && (
          <div style={{ marginTop: size.sp4, fontSize: 13.5, color: color.textSecondary }}>
            Step {data.stepIndex + 1} of {data.stepTotal}
          </div>
        )}
      </div>

      {data.updatedAt && (
        <p style={{ ...body, fontSize: 12.5, color: color.textDim }}>
          Last movement {new Date(
            data.updatedAt.endsWith('Z') || data.updatedAt.includes('+')
              ? data.updatedAt : `${data.updatedAt}Z`).toLocaleString()}
          {' · '}this page updates on its own
        </p>
      )}
    </>
  )
}

const h1 = {
  fontSize: 30, fontWeight: 600, color: color.textPrimary,
  margin: `${size.sp2} 0 0`, lineHeight: 1.25,
} as const

const body = {
  fontSize: 14.5, lineHeight: 1.65, color: color.textSecondary,
  margin: `${size.sp4} 0 0`,
} as const
