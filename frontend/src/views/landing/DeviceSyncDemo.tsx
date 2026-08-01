import { useEffect, useState } from 'react'
import { color, font, shadow, size } from '../../theme/tokens'

/**
 * One job finished on a phone, every screen in the shop.
 *
 * The page already claimed "works on phones and tablets" in a feature card,
 * which is the kind of sentence every SaaS site has and nobody believes. What
 * a shop floor actually wants to know is whether the thing in their hand is a
 * real terminal or a cut-down viewer — so this shows the answer instead of
 * asserting it.
 *
 * It shows the ACTUAL operator flow: tap a lot, press start, work while the
 * timer runs, press stop, and the lot moves on. An earlier version had the
 * worker flick the card away with a swipe — a gesture this product does not
 * have, and one that skipped the entire point of the operator view, which is
 * that the timer is where cycle time comes from. A demo that teaches the wrong
 * gesture costs more than no demo, because trying it is the first thing a new
 * user does.
 *
 * Drawn in plain SVG and CSS rather than with the map's Pixi primitives.
 * WebGL is not guaranteed — privacy extensions block it, GPU blocklists and
 * remote desktops disable it, and it is exactly the locked-down office PC a
 * prospect browses from. See `components/demo/webgl.ts`.
 */

type Phase = 'idle' | 'picked' | 'starting' | 'running' | 'stopped' | 'sync' | 'settled'

const TIMINGS: Record<Phase, number> = {
  idle: 1100,
  picked: 800,
  starting: 600,
  running: 3000,     // the work itself — the only part that should feel long
  stopped: 700,
  sync: 700,
  settled: 1900,
}
const ORDER: Phase[] = ['idle', 'picked', 'starting', 'running', 'stopped', 'sync', 'settled']

export default function DeviceSyncDemo() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [elapsed, setElapsed] = useState(0)
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

  // The clock ticks only while the work is running, which is what the real
  // timer does — and what cycle time is computed from.
  useEffect(() => {
    if (phase === 'running') {
      const i = setInterval(() => setElapsed((s) => s + 1), 1000)
      return () => clearInterval(i)
    }
    if (phase === 'idle') setElapsed(0)
  }, [phase])

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
        <Device label="iPhone · operator" caption="the operator's handset">
          <Phone phase={p} elapsed={still ? 3 : elapsed} />
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
        An operator picks a lot on an iPhone, presses start, does the work, and
        presses stop — that timer is where cycle time comes from. When the lot
        moves on, the floor plan on the tablet at the next cell and the board in
        the office follow over the same live connection, with no refresh and
        nothing to install.
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

// ─── The phone: the operator view, running a job ─────────────────────────────

const LOTS = [
  { code: 'LFP-0042', units: '4 modules', tint: '#3B82F6' },
  { code: 'LFP-0043', units: '4 modules', tint: '#10B981' },
  { code: 'NMC-0088', units: '8 modules', tint: '#8B5CF6' },
]

function Phone({ phase, elapsed }: { phase: Phase; elapsed: number }) {
  const chosen = phase !== 'idle'
  const running = phase === 'running' || phase === 'stopped'
  const gone = phase === 'sync' || phase === 'settled'

  // Which control the thumb is over. Three taps — the lot, start, stop — which
  // is the whole interaction.
  const tap =
    phase === 'picked' ? 'lot'
      : phase === 'starting' || phase === 'stopped' ? 'button'
        : null

  const label = gone ? 'Sent to Pack Test'
    : running ? 'Stop'
      : chosen ? 'Start'
        : 'Tap a lot to begin'

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
          padding: '18px 9px 6px', borderBottom: `1px solid ${color.border}`,
          fontSize: 10, color: color.textSecondary, fontFamily: font.mono,
        }}>
          Reassembly
        </div>

        <div style={{ padding: 6, display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
          {LOTS.map((lot, i) => {
            const selected = i === 0 && chosen && !gone
            const hidden = i === 0 && gone
            return (
              <div key={lot.code} style={{
                background: selected ? color.bgElevated : color.bgCard,
                border: `1px solid ${selected ? color.borderActive : color.border}`,
                borderLeft: `3px solid ${lot.tint}`, borderRadius: size.radius,
                padding: '5px 6px',
                opacity: hidden ? 0 : 1,
                transform: hidden ? 'translateY(-6px)' : 'none',
                transition: 'all 260ms ease',
              }}>
                <div style={{ fontSize: 9, fontFamily: font.mono, color: color.textPrimary }}>
                  {lot.code}
                </div>
                <div style={{ fontSize: 8, color: color.textDim, marginTop: 1 }}>{lot.units}</div>
              </div>
            )
          })}
        </div>

        {/* The timer. Visible only once a lot is being worked, because that is
            when it exists — and it is the number the statistics are built on. */}
        <div style={{
          textAlign: 'center', fontSize: 15, fontFamily: font.mono, height: 19,
          color: running ? color.statusRunning : color.textDim,
          letterSpacing: '0.04em',
          opacity: chosen && !gone ? 1 : 0, transition: 'opacity 200ms ease',
        }}>
          0:{String(elapsed).padStart(2, '0')}
        </div>

        <div style={{ padding: '4px 8px 9px' }}>
          <div style={{
            borderRadius: size.radius, textAlign: 'center', padding: '6px 0',
            fontSize: 9, fontWeight: 600, letterSpacing: '0.05em',
            background: gone ? 'transparent'
              : running ? color.statusFault
                : chosen ? color.statusRunning
                  : 'transparent',
            color: gone || !chosen ? color.textDim : color.white,
            transform: tap === 'button' ? 'scale(0.94)' : 'scale(1)',
            transition: 'all 180ms ease',
          }}>
            {label}
          </div>
        </div>
      </div>

      {/* The thumb, over whatever is being tapped. */}
      <div style={{
        position: 'absolute',
        left: tap === 'lot' ? 44 : 52,
        top: tap === 'lot' ? 66 : 212,
        width: 28, height: 28, borderRadius: '50%',
        background: color.textPrimary,
        opacity: tap ? 0.2 : 0,
        transform: tap ? 'scale(1)' : 'scale(0.7)',
        transition: 'all 240ms ease', pointerEvents: 'none',
      }} />
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
