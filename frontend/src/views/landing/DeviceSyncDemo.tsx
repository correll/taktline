import { useEffect, useState } from 'react'
import { color, font, shadow, size } from '../../theme/tokens'

/**
 * One swipe on a phone, every screen in the shop.
 *
 * The page already claimed "works on phones and tablets" in a feature card,
 * which is the kind of sentence every SaaS site has and nobody believes. What
 * a shop floor actually wants to know is whether the thing in their hand is a
 * real terminal or a cut-down viewer — so this shows the answer instead of
 * asserting it: a worker advances a lot with their thumb, and the floor plan
 * and the board move on every other device before they have put the phone
 * down.
 *
 * Drawn in plain SVG and CSS rather than with the map's Pixi primitives.
 * WebGL is not guaranteed — privacy extensions block it, GPU blocklists and
 * remote desktops disable it, and it is exactly the locked-down office PC a
 * prospect browses from — and a hero that apologises instead of rendering is
 * worse than a simpler hero. See `components/demo/webgl.ts` for the same
 * lesson learned the expensive way.
 *
 * The sequence is honest about the product: the phone commits the move, the
 * server broadcasts it, and the other screens follow. That is the real order
 * of events on the websocket, not a decorative shimmer.
 */

type Phase = 'idle' | 'swipe' | 'sync' | 'settled'

const TIMINGS: Record<Phase, number> = {
  idle: 900,
  swipe: 1100,
  sync: 700,
  settled: 2100,
}
const ORDER: Phase[] = ['idle', 'swipe', 'sync', 'settled']

export default function DeviceSyncDemo() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [still, setStill] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const apply = () => setStill(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    if (still) return
    const t = setTimeout(
      () => setPhase(ORDER[(ORDER.indexOf(phase) + 1) % ORDER.length]),
      TIMINGS[phase],
    )
    return () => clearTimeout(t)
  }, [phase, still])

  // With motion disabled the scene rests in its finished state: the lot has
  // moved and every screen agrees, which is the point being made. Nothing is
  // lost but the travel.
  const p: Phase = still ? 'settled' : phase
  const moved = p === 'sync' || p === 'settled'

  return (
    <div>
      <div
        aria-hidden="true"
        style={{
          display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
          gap: 'clamp(16px, 4vw, 44px)', flexWrap: 'wrap',
        }}
      >
        <Device label="iPhone · operator" caption="the worker's own phone">
          <Phone phase={p} />
        </Device>

        <Sync active={p === 'sync'} />

        <Device label="Android tablet · floor plan" caption="at the cell">
          <Tablet moved={moved} />
        </Device>

        {/* A second connector, firing at the SAME time as the first rather
            than after it. With one the row reads as a chain — phone, then
            tablet, then office — and that is not what happens: the server
            broadcasts, and every screen is downstream of the phone equally. */}
        <Sync active={p === 'sync'} />

        <Device label="Any browser · lots board" caption="the office">
          <Board moved={moved} />
        </Device>
      </div>

      {/* The same statement in text, for a screen reader and for a crawler
          that will never run any of the above. */}
      <p style={{
        margin: `${size.sp6} auto 0`, maxWidth: 620, textAlign: 'center',
        fontSize: 15, lineHeight: 1.7, color: color.textSecondary,
      }}>
        An operator swipes a lot forward on an iPhone. The floor plan on the
        tablet at the next cell and the board in the office both move —
        instantly, over the same live connection, with no refresh and nothing to
        install.
      </p>
    </div>
  )
}

// ─── Chrome ───────────────────────────────────────────────────────────────────

function Device({ label, caption, children }: {
  label: string; caption: string; children: React.ReactNode
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
      {children}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 12, fontFamily: font.mono, color: color.textSecondary }}>
          {label}
        </div>
        <div style={{ fontSize: 11, color: color.textDim, marginTop: 2 }}>{caption}</div>
      </div>
    </div>
  )
}

/** The broadcast itself: a pulse that leaves the phone and reaches the rest. */
function Sync({ active }: { active: boolean }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 5, height: 150,
      alignSelf: 'center', padding: '0 2px',
    }}>
      {[0, 1, 2].map((i) => (
        <span key={i} style={{
          width: 6, height: 6, borderRadius: '50%',
          background: active ? color.bluePrimary : color.border,
          transform: active ? 'scale(1.6)' : 'scale(1)',
          opacity: active ? 1 : 0.55,
          transition: `all 170ms ease ${i * 70}ms`,
          boxShadow: active ? `0 0 10px ${color.blueGlow}` : 'none',
        }} />
      ))}
    </div>
  )
}

// ─── The phone: the operator view, mid-swipe ─────────────────────────────────

function Phone({ phase }: { phase: Phase }) {
  const swiping = phase === 'swipe'
  const gone = phase === 'sync' || phase === 'settled'

  return (
    <div style={{
      width: 132, height: 258, borderRadius: 22, padding: 7,
      background: color.bgPanel, border: `1px solid ${color.borderStrong}`,
      boxShadow: shadow.lg, position: 'relative',
    }}>
      <div style={{
        position: 'absolute', top: 11, left: '50%', transform: 'translateX(-50%)',
        width: 40, height: 4, borderRadius: 3, background: color.border,
      }} />
      <div style={{
        height: '100%', borderRadius: 16, background: color.bgDeep,
        overflow: 'hidden', display: 'flex', flexDirection: 'column',
      }}>
        <div style={{
          padding: '18px 9px 7px', borderBottom: `1px solid ${color.border}`,
          fontSize: 10, color: color.textSecondary, fontFamily: font.mono,
        }}>
          Reassembly
        </div>

        <div style={{ padding: 7, display: 'flex', flexDirection: 'column', gap: 5, flex: 1 }}>
          <LotChip
            code="LFP-0042"
            units="8 modules"
            tint={color.lotBlue}
            style={{
              transform: gone ? 'translateX(150%)' : swiping ? 'translateX(58%)' : 'translateX(0)',
              opacity: gone ? 0 : 1,
              transition: gone ? 'all 260ms ease-in' : 'transform 620ms cubic-bezier(.2,.7,.3,1)',
            }}
          />
          <LotChip code="LFP-0043" units="8 modules" tint={color.lotGreen}
                   style={{ transform: gone ? 'translateY(-38px)' : 'none',
                            transition: 'transform 320ms ease 120ms' }} />
          <LotChip code="NMC-0088" units="6 modules" tint={color.lotPurple}
                   style={{ transform: gone ? 'translateY(-38px)' : 'none',
                            transition: 'transform 320ms ease 160ms' }} />
        </div>

        <div style={{
          padding: '6px 8px 9px', fontSize: 9, color: color.textDim,
          textAlign: 'center', letterSpacing: '0.04em',
        }}>
          {gone ? 'sent to Pack Test' : 'swipe to advance →'}
        </div>
      </div>

      {/* The thumb. Present only while the gesture is happening. */}
      <div style={{
        position: 'absolute', left: 26, top: 74,
        width: 30, height: 30, borderRadius: '50%',
        background: color.textPrimary, opacity: swiping ? 0.16 : 0,
        transform: swiping ? 'translateX(56px) scale(1)' : 'translateX(0) scale(0.7)',
        transition: 'all 620ms cubic-bezier(.2,.7,.3,1)', pointerEvents: 'none',
      }} />
    </div>
  )
}

function LotChip({ code, units, tint, style }: {
  code: string; units: string; tint: string; style?: React.CSSProperties
}) {
  return (
    <div style={{
      background: color.bgCard, border: `1px solid ${color.border}`,
      borderLeft: `3px solid ${tint}`, borderRadius: size.radius,
      padding: '6px 7px', ...style,
    }}>
      <div style={{ fontSize: 9, fontFamily: font.mono, color: color.textPrimary }}>{code}</div>
      <div style={{ fontSize: 8, color: color.textDim, marginTop: 1 }}>{units}</div>
    </div>
  )
}

// ─── The tablet: the floor plan, with the lot travelling an edge ─────────────

function Tablet({ moved }: { moved: boolean }) {
  const NODES = [
    { x: 26, y: 62, label: 'Teardown' },
    { x: 96, y: 34, label: 'Module' },
    { x: 96, y: 90, label: 'Busbar' },
    { x: 168, y: 62, label: 'Reassembly' },
    { x: 236, y: 62, label: 'Pack Test' },
  ]
  return (
    <div style={{
      width: 274, height: 172, borderRadius: 10, padding: 6,
      background: color.bgPanel, border: `1px solid ${color.borderStrong}`,
      boxShadow: shadow.lg,
    }}>
      <svg viewBox="0 0 262 124" width="100%" height="100%"
           style={{ background: color.bgDeep, borderRadius: 6, display: 'block' }}>
        {[[0, 1], [0, 2], [1, 3], [2, 3], [3, 4]].map(([a, b], i) => (
          <line key={i}
                x1={NODES[a].x} y1={NODES[a].y - 6} x2={NODES[b].x} y2={NODES[b].y - 6}
                stroke={color.border} strokeWidth={1.5} />
        ))}
        {/* The leg the lot is travelling, drawn in the lot's own colour —
            never brand coral, which everywhere else means "the app is doing
            something" rather than "your material is moving". */}
        <line x1={NODES[3].x} y1={NODES[3].y - 6} x2={NODES[4].x} y2={NODES[4].y - 6}
              stroke={color.lotBlue} strokeWidth={2}
              strokeDasharray="4 4"
              style={{ opacity: moved ? 1 : 0.25, transition: 'opacity 300ms ease' }} />
        <circle r={5} cy={NODES[3].y - 6} fill={color.lotBlue}
                cx={moved ? NODES[4].x : NODES[3].x}
                style={{
                  transition: 'cx 700ms cubic-bezier(.3,.7,.3,1)',
                  filter: `drop-shadow(0 0 5px ${color.lotBlue})`,
                }} />
        {NODES.map((n, i) => (
          <g key={i}>
            <rect x={n.x - 20} y={n.y - 20} width={40} height={28} rx={4}
                  fill={color.bgCard} stroke={i === 4 && moved ? color.lotBlue : color.border}
                  strokeWidth={i === 4 && moved ? 1.6 : 1}
                  style={{ transition: 'all 300ms ease' }} />
            <text x={n.x} y={n.y - 3} textAnchor="middle"
                  fontSize={7} fill={color.textSecondary} fontFamily="monospace">
              {n.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  )
}

// ─── The board: the lot jumping a column ─────────────────────────────────────

function Board({ moved }: { moved: boolean }) {
  const COLUMNS = ['Teardown', 'Reassembly', 'Pack Test']
  return (
    <div style={{
      width: 218, height: 172, borderRadius: 8, padding: 6,
      background: color.bgPanel, border: `1px solid ${color.borderStrong}`,
      boxShadow: shadow.lg,
    }}>
      <div style={{
        height: '100%', background: color.bgDeep, borderRadius: 5,
        padding: 5, display: 'flex', gap: 4,
      }}>
        {COLUMNS.map((name, i) => (
          <div key={name} style={{
            flex: 1, display: 'flex', flexDirection: 'column', gap: 3,
            background: color.bgPanel, borderRadius: 4, padding: 4,
          }}>
            <div style={{
              fontSize: 7, fontFamily: font.mono, color: color.textDim,
              borderBottom: `1px solid ${color.border}`, paddingBottom: 3,
              whiteSpace: 'nowrap', overflow: 'hidden',
            }}>
              {name}
            </div>
            {i === 1 && !moved && <MiniCard tint={color.lotBlue} label="LFP-0042" />}
            {i === 2 && moved && <MiniCard tint={color.lotBlue} label="LFP-0042" />}
            {i === 1 && <MiniCard tint={color.lotGreen} label="LFP-0043" />}
            {i === 0 && <MiniCard tint={color.lotAmber} label="NMC-0091" />}
          </div>
        ))}
      </div>
    </div>
  )
}

function MiniCard({ tint, label }: { tint: string; label: string }) {
  return (
    <div style={{
      background: color.bgCard, borderLeft: `2px solid ${tint}`,
      borderRadius: 2, padding: '3px 4px', fontSize: 6.5,
      fontFamily: font.mono, color: color.textSecondary,
    }}>
      {label}
    </div>
  )
}
