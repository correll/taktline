import React, { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useStationsStore, useProcessesStore } from '../store'
import { color, font, size, shadow } from '../theme/tokens'
import { useHelpStore } from './helpStore'
import { TOUR_STEPS, type TourCtx } from './tourSteps'

export function TourManager() {
  const tourActive = useHelpStore((s) => s.tourActive)
  const tourStep = useHelpStore((s) => s.tourStep)
  const nextStep = useHelpStore((s) => s.nextStep)
  const backStep = useHelpStore((s) => s.backStep)
  const stopTour = useHelpStore((s) => s.stopTour)

  const stations = useStationsStore((s) => s.stations)
  const processes = useProcessesStore((s) => s.processes)
  const routes = useProcessesStore((s) => s.routes)
  const templates = useProcessesStore((s) => s.lotTemplates)
  const { pathname } = useLocation()

  const step = TOUR_STEPS[tourStep]
  const total = TOUR_STEPS.length

  const ctx: TourCtx = {
    pathname,
    stations: Object.values(stations),
    routes,
    processes,
    templates,
  }
  const done = !!(tourActive && step?.isDone && step.isDone(ctx))

  // A step reached via the Back button whose action is already complete must
  // not bounce straight forward again — hold auto-advance until the status
  // actually changes (goes not-done → done) while the step is showing.
  const manualBackRef = useRef(false)
  const [suppressAuto, setSuppressAuto] = useState(false)
  useEffect(() => {
    if (manualBackRef.current) {
      setSuppressAuto(done)
      manualBackRef.current = false
    } else {
      setSuppressAuto(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tourStep])

  // Auto-advance a short beat after the user completes the step's action.
  useEffect(() => {
    if (!done) {
      if (suppressAuto) setSuppressAuto(false)   // status changed → re-arm
      return
    }
    if (suppressAuto) return
    const t = setTimeout(() => nextStep(), 650)
    return () => clearTimeout(t)
  }, [done, suppressAuto, tourStep, nextStep])

  // Keep the highlight ring glued to the current target element.
  const ringRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!tourActive) return
    let raf = 0
    const loop = () => {
      const ring = ringRef.current
      if (ring) {
        const el = step?.target
          ? (document.querySelector(`[data-tour="${step.target}"]`) as HTMLElement | null)
          : null
        if (el) {
          const r = el.getBoundingClientRect()
          ring.style.display = 'block'
          ring.style.top = `${r.top - 6}px`
          ring.style.left = `${r.left - 6}px`
          ring.style.width = `${r.width + 12}px`
          ring.style.height = `${r.height + 12}px`
        } else {
          ring.style.display = 'none'
        }
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [tourActive, tourStep])

  if (!tourActive || !step) return null
  const isLast = tourStep === total - 1

  return (
    <>
      <div ref={ringRef} className="tour-ring" style={{ display: 'none' }} />

      <div style={{
        position: 'fixed', right: size.sp6, bottom: size.sp6, width: 360, maxWidth: 'calc(100vw - 32px)',
        background: color.bgPanel, border: `1px solid ${color.borderActive}`,
        borderRadius: size.radiusLg, boxShadow: shadow.lg, zIndex: 9999,
        padding: size.sp5, fontFamily: font.sans,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: size.sp2 }}>
          <span style={{ fontSize: 11, letterSpacing: '0.1em', color: color.blueBright, fontFamily: font.mono }}>
            GUIDED TOUR · {tourStep + 1}/{total}
          </span>
          <button onClick={stopTour} title="End tour"
                  style={{ background: 'none', border: 'none', color: color.textDim, cursor: 'pointer', fontSize: 18, lineHeight: 1 }}>
            ×
          </button>
        </div>

        <h3 style={{ margin: 0, color: color.textPrimary, fontSize: 16 }}>{step.title}</h3>
        <p style={{ color: color.textSecondary, fontSize: 13, lineHeight: 1.55, marginTop: size.sp2, marginBottom: size.sp4 }}>
          {step.body}
        </p>

        {step.isDone && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: size.sp4 }}>
            <span className={`status-dot ${done ? 'running' : 'warning'}`} />
            <span style={{ fontSize: 11, color: done ? color.statusRunning : color.textDim, fontFamily: font.mono }}>
              {done ? (suppressAuto ? 'done' : 'done — advancing…') : 'waiting for you…'}
            </span>
          </div>
        )}

        <div style={{ display: 'flex', gap: size.sp2, justifyContent: 'space-between' }}>
          <button onClick={() => { manualBackRef.current = true; backStep() }} disabled={tourStep === 0}
                  style={{
                    background: 'transparent', border: `1px solid ${color.border}`, color: color.textSecondary,
                    borderRadius: size.radius, padding: `${size.sp2} ${size.sp3}`, fontSize: 13,
                    cursor: tourStep === 0 ? 'default' : 'pointer', opacity: tourStep === 0 ? 0.4 : 1,
                  }}>
            Back
          </button>
          <button onClick={() => (isLast ? stopTour() : nextStep())}
                  style={{
                    background: color.bluePrimary, border: 'none', color: color.white,
                    borderRadius: size.radius, padding: `${size.sp2} ${size.sp5}`, fontSize: 13, fontWeight: 600,
                    cursor: 'pointer',
                  }}>
            {isLast ? 'Finish' : !step.isDone ? 'Next' : done ? 'Next →' : 'Skip →'}
          </button>
        </div>
      </div>
    </>
  )
}
