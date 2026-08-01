import React, { useCallback, useEffect, useState } from 'react'
import { analysisApi, type Finding, type LineReport } from '../api/analysis.api'
import { useHelpStore } from './helpStore'
import { useStationsStore } from '../store/stations.store'
import { color, font, shadow, size } from '../theme/tokens'

/**
 * The bulb.
 *
 * Off — a faint outline — until the line has been running long enough to say
 * something about pace. Then it lights, because a light coming on is a thing
 * people notice without being told what it means, and it is honest: it is on
 * when there is something to read, not when there is a problem.
 *
 * Clicking it always works, even dark. That is deliberate: on day one there is
 * no timing data at all, and that is precisely when a new user most needs to be
 * told that their line cannot complete an order, or that a split delivers six
 * pieces into a bench that takes one. Those findings come from the shape of the
 * graph and need no measurements whatsoever.
 *
 * Everything is computed on our own server by `core/analysis.py` — a rule
 * engine, not a model. Nothing about a customer's line leaves the building,
 * which is the reason it can be pointed at real production data at all.
 */

const REFRESH_MS = 60_000

export function LineDoctor() {
  const [report, setReport] = useState<LineReport | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const tourActive = useHelpStore((s) => s.tourActive)

  const load = useCallback(async () => {
    setBusy(true)
    try { setReport(await analysisApi.report()) } catch { /* offline: keep the last one */ }
    finally { setBusy(false) }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  if (!report) return null

  const lit = report.readiness === 'ready'
  const alarming = report.counts.critical > 0
  const badge = report.counts.critical || report.counts.warning

  return (
    <>
      <button
        onClick={() => { setOpen((v) => !v); if (!open) load() }}
        data-tour="line-doctor"
        aria-label="Line doctor"
        title={lit ? 'Line doctor — enough data to read your line'
                   : 'Line doctor — not enough data yet, but the shape can still be checked'}
        style={{
          position: 'fixed',
          // Below the view's own top-right controls (the board's merge
          // button, the floor plan's legend) rather than on top of them.
          top: `calc(${size.topbarHeight} + 84px + env(safe-area-inset-top, 0px))`,
          right: 18, zIndex: 7500,
          width: 72, height: 72, borderRadius: '50%',
          display: tourActive ? 'none' : 'flex',
          alignItems: 'center', justifyContent: 'center',
          border: `1px solid ${lit ? `${color.statusWarning}66` : color.border}`,
          background: lit ? `${color.statusWarning}14` : 'transparent',
          backdropFilter: 'blur(2px)',
          color: lit ? color.statusWarning : color.textDim,
          opacity: lit ? 1 : 0.45,
          cursor: 'pointer',
          boxShadow: lit ? `0 0 26px ${color.statusWarning}44` : 'none',
          animation: lit ? 'tk-bulb-glow 3.4s ease-in-out infinite' : 'none',
          transition: 'opacity 300ms ease, box-shadow 400ms ease, background 400ms ease',
        }}
      >
        <Bulb lit={lit} />
        {badge > 0 && (
          <span style={{
            position: 'absolute', top: 4, right: 4, minWidth: 18, height: 18,
            borderRadius: 9, padding: '0 5px',
            background: alarming ? color.statusFault : color.statusWarning,
            color: color.white, fontSize: 10, fontWeight: 700, fontFamily: font.mono,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {badge}
          </span>
        )}
      </button>

      {open && <ReportPanel report={report} busy={busy} onClose={() => setOpen(false)} />}

      <style>{`
        @keyframes tk-bulb-glow {
          0%, 100% { box-shadow: 0 0 18px ${color.statusWarning}33; }
          50%      { box-shadow: 0 0 34px ${color.statusWarning}66; }
        }
        @media (prefers-reduced-motion: reduce) {
          @keyframes tk-bulb-glow { 0%, 100% { box-shadow: 0 0 22px ${color.statusWarning}44; } }
        }
      `}</style>
    </>
  )
}

function Bulb({ lit }: { lit: boolean }) {
  return (
    <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {lit && <circle cx="12" cy="9" r="5.4" fill="currentColor" opacity="0.22" />}
      <path d="M9 18h6M10 21h4" />
      <path d="M12 3a6 6 0 0 0-3.6 10.8c.5.4.8.9.9 1.5l.1.7h5.2l.1-.7c.1-.6.4-1.1.9-1.5A6 6 0 0 0 12 3Z" />
    </svg>
  )
}

// ─── The report ──────────────────────────────────────────────────────────────

const TONE: Record<string, { fg: string; label: string }> = {
  critical: { fg: color.statusFault, label: 'Stops the line' },
  warning: { fg: color.statusWarning, label: 'Costs you every cycle' },
  insight: { fg: color.textSecondary, label: 'Worth knowing' },
}

function ReportPanel({ report, busy, onClose }: {
  report: LineReport; busy: boolean; onClose: () => void
}) {
  const openManual = useHelpStore((s) => s.openManual)
  const stations = useStationsStore((s) => s.stations)
  const nameOf = (id: string) => stations[id]?.name ?? '—'

  const cov = report.coverage
  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 7600 }} />
      <div
        role="dialog"
        aria-label="Line doctor report"
        style={{
          position: 'fixed', zIndex: 7601,
          top: `calc(${size.topbarHeight} + 164px + env(safe-area-inset-top, 0px))`,
          right: 18, width: 460, maxWidth: 'calc(100vw - 36px)',
          maxHeight: 'calc(100vh - 220px)', overflowY: 'auto',
          background: color.bgPanel, border: `1px solid ${color.border}`,
          borderRadius: size.radiusLg, boxShadow: shadow.lg,
          padding: `${size.sp5} ${size.sp5} ${size.sp4}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: size.sp2 }}>
          <span style={{
            fontSize: 10, fontFamily: font.mono, letterSpacing: '0.12em', color: color.textDim,
          }}>
            LINE DOCTOR
          </span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: color.textDim }}>
            {busy ? 'reading…' : 'on your own server'}
          </span>
        </div>

        <h2 style={{
          margin: `${size.sp2} 0 0`, fontSize: 18, lineHeight: 1.3, fontWeight: 500,
          color: color.textPrimary,
        }}>
          {report.headline}
        </h2>

        {report.narrative.map((p, i) => (
          <p key={i} style={{
            margin: `${size.sp3} 0 0`, fontSize: 13, lineHeight: 1.65, color: color.textSecondary,
          }}>
            {p}
          </p>
        ))}

        {report.readiness !== 'ready' && (
          <div style={{
            marginTop: size.sp4, padding: `${size.sp2} ${size.sp3}`,
            background: color.bgElevated, borderRadius: size.radius,
            fontSize: 11, color: color.textDim, fontFamily: font.mono,
          }}>
            {cov.sessions}/{cov.sessionsNeeded} work sessions ·{' '}
            {cov.stationsWithTiming}/{cov.stationsNeeded} stations timed
          </div>
        )}

        {report.findings.length > 0 && (
          <div style={{ marginTop: size.sp5, display: 'flex', flexDirection: 'column', gap: size.sp3 }}>
            {report.findings.map((f, i) => (
              <FindingCard key={`${f.rule}-${i}`} f={f} nameOf={nameOf} onManual={openManual} />
            ))}
          </div>
        )}
      </div>
    </>
  )
}

function FindingCard({ f, nameOf, onManual }: {
  f: Finding; nameOf: (id: string) => string; onManual: (section?: string) => void
}) {
  const tone = TONE[f.severity] ?? TONE.insight
  return (
    <div style={{
      borderLeft: `3px solid ${tone.fg}`, background: color.bgCard,
      borderRadius: size.radius, padding: `${size.sp3} ${size.sp3}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: size.sp2, flexWrap: 'wrap' }}>
        <span style={{
          fontSize: 9, fontFamily: font.mono, letterSpacing: '0.08em', color: tone.fg,
          textTransform: 'uppercase',
        }}>
          {tone.label}
        </span>
        {f.waste && (
          <span style={{
            fontSize: 9, fontFamily: font.mono, color: color.textDim,
            border: `1px solid ${color.border}`, borderRadius: size.radiusFull, padding: '0 6px',
          }}>
            {f.waste}
          </span>
        )}
      </div>

      <div style={{ marginTop: 4, fontSize: 13, fontWeight: 500, color: color.textPrimary }}>
        {f.title}
      </div>
      <p style={{ margin: `4px 0 0`, fontSize: 12.5, lineHeight: 1.6, color: color.textSecondary }}>
        {f.detail}
      </p>

      <div style={{ display: 'flex', gap: size.sp3, marginTop: size.sp2, flexWrap: 'wrap' }}>
        {f.stations.slice(0, 4).map((id) => (
          <span key={id} style={{ fontSize: 10, fontFamily: font.mono, color: color.textDim }}>
            {nameOf(id)}
          </span>
        ))}
        {f.manual && (
          <button
            onClick={() => onManual(f.manual!)}
            style={{
              marginLeft: 'auto', background: 'none', border: 'none', padding: 0,
              color: color.blueBright, fontSize: 11, cursor: 'pointer',
            }}
          >
            Read more
          </button>
        )}
      </div>
    </div>
  )
}
