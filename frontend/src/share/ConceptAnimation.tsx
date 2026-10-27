import { useEffect, useState } from 'react'
import type { ConceptAnimation as Kind } from '../help/concepts'
import { color } from '../theme/tokens'

/**
 * The eight flow-science results, moving.
 *
 * Deliberately SVG and CSS rather than Pixi: these render on a shared link
 * opened by strangers on unknown machines, and a WebGL context is not
 * guaranteed — privacy extensions block it, GPU blocklists disable it, and the
 * crawler that first reported the problem here had none. A concept animation
 * that shows an apology instead of the concept is worse than a static diagram.
 *
 * Every scene steps through *discrete* states on a clock rather than tweening,
 * because each of these results is an argument about two situations being
 * different, and a smooth interpolation between them shows neither. The clock
 * stops for `prefers-reduced-motion`, holding the state that makes the point.
 */

const CORAL = '#F0997B'
/** The unfilled part of a bar. `bgCard` was the obvious choice and is white in
 *  the day theme — on a white panel every track disappeared and the charts read
 *  as floating fills. `border` is a mid neutral in both themes. */
const TRACK = color.border
const GOOD = '#5FA97F'
const WARN = '#EF9F27'
const BAD = '#E24B4A'

function useStep(count: number, ms: number, still: number): number {
  const [step, setStep] = useState(still)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (mq.matches) { setStep(still); return }
    const t = setInterval(() => setStep((s) => (s + 1) % count), ms)
    return () => clearInterval(t)
  }, [count, ms, still])
  return step
}

const label = { fill: color.textDim, fontSize: 11, fontFamily: 'inherit' } as const
const readout = { fill: color.textPrimary, fontSize: 17, fontWeight: 600 } as const

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <svg viewBox="0 0 480 210" style={{ width: '100%', height: 'auto', display: 'block' }}
         role="img">
      {children}
    </svg>
  )
}

/** A lot on the floor. */
function Lot({ x, y, on, fill = CORAL }: { x: number; y: number; on: boolean; fill?: string }) {
  return (
    <rect x={x} y={y} width={16} height={16} rx={3}
          fill={on ? fill : 'transparent'}
          stroke={on ? fill : color.border} strokeWidth={1}
          style={{ transition: 'fill 400ms ease, stroke 400ms ease' }} />
  )
}

// ── Little's law ─────────────────────────────────────────────────────────────

function WipScene() {
  const step = useStep(2, 2600, 1)
  const shown = step === 0 ? 12 : 6
  return (
    <Frame>
      <text x={0} y={14} style={label}>PRODUCTS ON THE FLOOR</text>
      {Array.from({ length: 12 }, (_, i) => (
        <Lot key={i} x={(i % 6) * 24} y={26 + Math.floor(i / 6) * 24} on={i < shown} />
      ))}
      <text x={0} y={112} style={readout}>{shown} products</text>

      <text x={0} y={148} style={label}>LEAD TIME</text>
      <rect x={0} y={158} width={460} height={20} rx={4} fill={TRACK} />
      <rect x={0} y={158} width={step === 0 ? 460 : 230} height={20} rx={4} fill={CORAL}
            style={{ transition: 'width 700ms cubic-bezier(.4,0,.2,1)' }} />
      <text x={0} y={200} style={readout}>{step === 0 ? '3 days' : '1.5 days'}</text>
      <text x={190} y={200} style={{ ...label, fill: GOOD }}>
        {step === 0 ? '' : 'nobody worked any faster'}
      </text>
    </Frame>
  )
}

// ── Kingman ──────────────────────────────────────────────────────────────────

const RHOS = [0.5, 0.7, 0.8, 0.9, 0.95]

function QueueScene() {
  const step = useStep(RHOS.length, 1500, 3)
  const rho = RHOS[step]
  const wait = rho / (1 - rho)
  const queued = Math.min(20, Math.round(wait))
  const hot = rho >= 0.9
  return (
    <Frame>
      <text x={0} y={14} style={label}>UTILISATION</text>
      <rect x={0} y={24} width={300} height={14} rx={7} fill={TRACK} />
      <rect x={0} y={24} width={300 * rho} height={14} rx={7}
            fill={hot ? BAD : rho >= 0.8 ? WARN : GOOD}
            style={{ transition: 'width 500ms ease, fill 500ms ease' }} />
      <text x={312} y={36} style={readout}>{Math.round(rho * 100)}%</text>

      <text x={0} y={72} style={label}>QUEUE IN FRONT OF THE STATION</text>
      {Array.from({ length: 20 }, (_, i) => (
        <Lot key={i} x={(i % 10) * 22} y={82 + Math.floor(i / 10) * 22} on={i < queued}
             fill={hot ? BAD : CORAL} />
      ))}

      <line x1={230} y1={104} x2={252} y2={104} stroke={color.textDim} strokeWidth={1.5}
            markerEnd="url(#qtip)" />
      <defs>
        <marker id="qtip" markerWidth={6} markerHeight={6} refX={5} refY={3} orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill={color.textDim} />
        </marker>
      </defs>
      <rect x={258} y={80} width={62} height={48} rx={5} fill={color.bgCard}
            stroke={color.border} />
      <text x={270} y={109} style={{ ...label, fill: color.textSecondary }}>work</text>

      <text x={0} y={170} style={readout}>
        waits {Math.round(wait)}× its own work time
      </text>
      <text x={0} y={196} style={{ ...label, fill: hot ? BAD : color.textDim }}>
        {hot ? 'the last 5% of load cost more than the first 80%'
             : 'load and queue are not proportional'}
      </text>
    </Frame>
  )
}

// ── Balance efficiency ───────────────────────────────────────────────────────

const WORK = [25, 40, 22, 31, 28]

function BalanceScene() {
  const step = useStep(2, 2400, 1)
  const slowest = Math.max(...WORK)
  const px = (m: number) => m * 3.2
  return (
    <Frame>
      <text x={0} y={14} style={label}>WORK CONTENT PER PRODUCT</text>
      <defs>
        <pattern id="idle" width={6} height={6} patternTransform="rotate(45)"
                 patternUnits="userSpaceOnUse">
          <line x1={0} y1={0} x2={0} y2={6} stroke={WARN} strokeWidth={2} opacity={0.5} />
        </pattern>
      </defs>
      {WORK.map((m, i) => {
        const y = 28 + i * 27
        const gap = slowest - m
        return (
          <g key={i}>
            <text x={0} y={y + 14} style={label}>S{i + 1}</text>
            <rect x={26} y={y} width={px(m)} height={18} rx={3}
                  fill={m === slowest ? CORAL : color.textDim} opacity={m === slowest ? 1 : 0.55} />
            {step === 1 && gap > 0 && (
              <rect x={26 + px(m)} y={y} width={px(gap)} height={18} rx={3} fill="url(#idle)"
                    stroke={WARN} strokeWidth={0.75} strokeOpacity={0.5} />
            )}
            <text x={26 + px(slowest) + 12} y={y + 14} style={label}>{m}m</text>
          </g>
        )
      })}
      <text x={0} y={188} style={step === 1 ? { ...readout, fill: WARN } : readout}>
        {step === 1
          // Computed rather than written down: the caption and the bars have to
          // agree, and the first hand-typed figure did not.
          ? `${WORK.reduce((a, m) => a + (slowest - m), 0)} minutes of built-in ` +
            'waiting, every product'
          : 'Every station is paced by the slowest one'}
      </text>
    </Frame>
  )
}

// ── Flow efficiency ──────────────────────────────────────────────────────────

function FlowScene() {
  const step = useStep(2, 2800, 1)
  // 4.1 h in the building against 15 min of work — 6%, drawn to scale.
  const work = 28
  return (
    <Frame>
      <text x={0} y={14} style={label}>TODAY · ONE PRODUCT, RELEASE TO FINISH</text>
      <rect x={0} y={26} width={460} height={28} rx={5} fill={TRACK} />
      <rect x={0} y={26} width={work} height={28} rx={5} fill={CORAL} />
      <text x={work + 12} y={45} style={{ ...label, fill: color.textSecondary }}>
        the other 94% is waiting, queueing and moving
      </text>
      <text x={0} y={76} style={label}>↑ 15 min of work, inside 4.1 hours</text>

      <text x={0} y={122} style={label}>NOW DOUBLE THE SPEED OF EVERY MACHINE</text>
      <rect x={0} y={134} width={460} height={28} rx={5} fill={TRACK} />
      <rect x={0} y={134} width={step === 1 ? work / 2 : work} height={28} rx={5} fill={GOOD}
            style={{ transition: 'width 700ms ease' }} />
      <rect x={0} y={134} width={step === 1 ? 446 : 460} height={28} rx={5} fill="none"
            stroke={GOOD} strokeWidth={1.2} strokeOpacity={0.5}
            style={{ transition: 'width 700ms ease' }} />
      <text x={0} y={196} style={step === 1 ? { ...readout, fill: GOOD } : readout}>
        {step === 1 ? 'The customer waits 3% less' : 'Every machine, twice as fast'}
      </text>
    </Frame>
  )
}

// ── Common cause / special cause ─────────────────────────────────────────────

const RUN = [62, 58, 65, 60, 63, 59, 64, 61, 57, 63, 30, 62, 60, 64]

function ControlScene() {
  const step = useStep(2, 2600, 1)
  const x = (i: number) => 20 + i * 32
  const y = (v: number) => 150 - (v - 20) * 1.6
  return (
    <Frame>
      <text x={0} y={14} style={label}>UTILISATION, ONE POINT PER DAY</text>
      <line x1={14} y1={y(70)} x2={466} y2={y(70)} stroke={color.border} strokeDasharray="4 4" />
      <line x1={14} y1={y(50)} x2={466} y2={y(50)} stroke={color.border} strokeDasharray="4 4" />
      <text x={468} y={y(70) + 4} style={{ ...label, textAnchor: 'end' as const }}></text>
      <text x={14} y={y(70) - 6} style={label}>upper limit</text>
      <text x={14} y={y(50) + 14} style={label}>lower limit</text>
      <polyline
        points={RUN.map((v, i) => `${x(i)},${y(v)}`).join(' ')}
        fill="none" stroke={color.textDim} strokeWidth={1.5} opacity={0.7}
      />
      {RUN.map((v, i) => {
        const special = v < 50 || v > 70
        return (
          <circle key={i} cx={x(i)} cy={y(v)} r={special ? 6 : 4}
                  fill={special ? BAD : color.textSecondary}
                  opacity={step === 1 || !special ? 1 : 0.35}
                  style={{ transition: 'opacity 400ms ease' }} />
        )
      })}
      <text x={0} y={186} style={step === 1 ? { ...readout, fill: BAD } : readout}>
        {step === 1
          ? 'One point is an event to find'
          : 'This spread is the system — adjusting for it makes it worse'}
      </text>
    </Frame>
  )
}

// ── Matched sets ─────────────────────────────────────────────────────────────

const FEEDS = [
  { name: 'Frames', pct: 100 },
  { name: 'Motors', pct: 100 },
  { name: 'Wheels', pct: 40 },
]

function MatchedScene() {
  const step = useStep(2, 2600, 0)
  return (
    <Frame>
      <text x={0} y={14} style={label}>PRECURSORS FINISHED</text>
      {FEEDS.map((f, i) => {
        const pct = step === 1 ? 100 : f.pct
        return (
          <g key={f.name}>
            <text x={0} y={44 + i * 34} style={label}>{f.name}</text>
            <rect x={78} y={30 + i * 34} width={280} height={18} rx={4} fill={TRACK} />
            <rect x={78} y={30 + i * 34} width={280 * (pct / 100)} height={18} rx={4}
                  fill={pct === 100 ? GOOD : WARN}
                  style={{ transition: 'width 700ms ease, fill 700ms ease' }} />
            <text x={370} y={44 + i * 34} style={label}>{pct}%</text>
          </g>
        )
      })}
      <text x={0} y={166} style={label}>ASSEMBLIES YOU CAN ACTUALLY BUILD</text>
      <text x={0} y={196} style={{ ...readout, fill: step === 1 ? GOOD : BAD }}>
        {step === 1 ? '10 — the set completed' : '0 — at 80% of all parts'}
      </text>
    </Frame>
  )
}

// ── Monuments ────────────────────────────────────────────────────────────────

function MonumentScene() {
  const step = useStep(2, 2800, 1)
  const cellX = [8, 78, 148]
  return (
    <Frame>
      <text x={0} y={14} style={label}>RIGHT-SIZED MACHINES, PLACED IN THE FLOW</text>
      {cellX.map((x, i) => (
        <g key={i}>
          <rect x={x} y={26} width={50} height={40} rx={5} fill={color.bgCard}
                stroke={GOOD} strokeWidth={1.2} />
          {i < 2 && <line x1={x + 50} y1={46} x2={x + 70} y2={46} stroke={color.textDim}
                          strokeWidth={1.5} markerEnd="url(#tip)" />}
        </g>
      ))}
      <defs>
        <marker id="tip" markerWidth={6} markerHeight={6} refX={5} refY={3} orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill={color.textDim} />
        </marker>
      </defs>
      <text x={212} y={51} style={{ ...label, fill: GOOD }}>one product at a time</text>

      <text x={0} y={96} style={label}>ONE BIG MACHINE EVERYTHING ROUTES TO</text>
      {[0, 1, 2].map((i) => (
        <rect key={i} x={8 + i * 34} y={110} width={26} height={26} rx={4} fill={color.bgCard}
              stroke={color.border} />
      ))}
      {[0, 1, 2].map((i) => (
        <line key={i} x1={21 + i * 34} y1={136} x2={150} y2={158} stroke={WARN}
              strokeWidth={1.2} opacity={0.7} />
      ))}
      <rect x={150} y={110} width={110} height={72} rx={6} fill={color.bgCard}
            stroke={WARN} strokeWidth={1.5} />
      <text x={162} y={152} style={{ ...label, fill: WARN }}>FURNACE</text>
      {Array.from({ length: step === 1 ? 8 : 3 }, (_, i) => (
        <Lot key={i} x={274 + (i % 4) * 20} y={122 + Math.floor(i / 4) * 20} on fill={WARN} />
      ))}
      <text x={274} y={178} style={{ ...label, fill: WARN }}>batch, waiting for a full load</text>
    </Frame>
  )
}

// ── Theory of constraints ────────────────────────────────────────────────────

const RATES = [12, 11, 6, 13]

function ConstraintScene() {
  const step = useStep(2, 2400, 1)
  return (
    <Frame>
      <text x={0} y={14} style={label}>PIECES PER HOUR, STATION BY STATION</text>
      {RATES.map((r, i) => {
        const x = 10 + i * 118
        const slow = r === Math.min(...RATES)
        return (
          <g key={i}>
            <rect x={x} y={54} width={78} height={r * 4.6} rx={5}
                  fill={slow ? BAD : color.textDim} opacity={slow ? 1 : 0.5}
                  transform={`translate(0 ${60 - r * 4.6})`} />
            <text x={x + 4} y={130} style={label}>S{i + 1} · {r}/h</text>
            {i < 3 && (
              <line x1={x + 84} y1={92} x2={x + 104} y2={92} stroke={color.textDim}
                    strokeWidth={1.5} markerEnd="url(#tip2)" />
            )}
          </g>
        )
      })}
      <defs>
        <marker id="tip2" markerWidth={6} markerHeight={6} refX={5} refY={3} orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill={color.textDim} />
        </marker>
      </defs>
      {/* Work piling up in front of the constraint — the visible symptom, and
          the reason the queue sits between S2 and S3 rather than anywhere else. */}
      {step === 1 && Array.from({ length: 6 }, (_, i) => (
        <Lot key={i} x={222 + (i % 3) * 19} y={144 + Math.floor(i / 3) * 19} on fill={BAD} />
      ))}
      <text x={0} y={198} style={step === 1 ? { ...readout, fill: BAD } : readout}>
        {step === 1 ? 'The whole line runs at 6/h' : 'Speeding up S4 changes nothing'}
      </text>
    </Frame>
  )
}

const SCENES: Record<Kind, () => JSX.Element> = {
  wip: WipScene,
  queue: QueueScene,
  balance: BalanceScene,
  flow: FlowScene,
  control: ControlScene,
  matched: MatchedScene,
  monument: MonumentScene,
  constraint: ConstraintScene,
}

export function ConceptAnimation({ kind }: { kind: Kind }) {
  const Scene = SCENES[kind]
  if (!Scene) return null
  return <Scene />
}
