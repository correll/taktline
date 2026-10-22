import { useState } from 'react'
import { analysisApi, type WhatIfResult } from '../../api/analysis.api'
import { color, font, size } from '../../theme/tokens'

/** What if? The line's recorded history replayed with one thing changed.
 *
 *  The answer a snapshot cannot give: not which station is slowest, but how
 *  much shorter the lead time gets if one of them becomes a machine. The
 *  model is built from this line's own sessions, stoppages and moves, and the
 *  first line of the answer says how well it reproduces the lead time the
 *  line actually had, so nobody has to take it on trust. */
export function WhatIf({ stations }: { stations: { _id: string; name: string }[] }) {
  const [speed, setSpeed] = useState(0.75)
  const [cv, setCv] = useState<string>('0.05')
  const [breakdowns, setBreakdowns] = useState(true)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<WhatIfResult | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const run = async () => {
    setBusy(true); setErr(null)
    try {
      setRes(await analysisApi.automation({ speedFactor: speed, cv: cv === '' ? null : Number(cv), breakdowns }))
    } catch (e) {
      setErr(String((e as { message?: string })?.message ?? e))
    } finally { setBusy(false) }
  }
  const h = (x: number | null | undefined) => x == null ? '—'
    : x >= 1 ? `${x.toFixed(2)} h` : `${(x * 60).toFixed(1)} min`
  const input = { background: color.bgCard, border: `1px solid ${color.border}`, borderRadius: size.radius,
                  color: color.textPrimary, padding: '4px 8px', fontSize: 12, width: 70 }
  return (
    <div style={{ display: 'grid', gap: size.sp3, fontSize: 12, color: color.textPrimary }}>
      <div style={{ color: color.textSecondary, lineHeight: 1.5 }}>
        Where would a machine shorten the lead time most? Describe it against the people it would
        replace, and Taktline replays the recorded period with the machine at each station in turn.
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: size.sp4, alignItems: 'center' }}>
        <label>Work time × <input type="number" step="0.05" min="0.1" max="3" value={speed}
          onChange={(e) => setSpeed(Number(e.target.value) || 1)} style={input} /></label>
        <label>Variability (CV) <input type="number" step="0.05" min="0" max="3" value={cv}
          placeholder="as now" onChange={(e) => setCv(e.target.value)} style={input} /></label>
        <label><input type="checkbox" checked={breakdowns} onChange={(e) => setBreakdowns(e.target.checked)} />
          {' '}breaks down like the station</label>
        <button onClick={run} disabled={busy} style={{
          padding: '5px 14px', background: color.statusRunning, color: '#fff', border: 'none',
          borderRadius: size.radius, fontFamily: font.mono, fontSize: 12, cursor: busy ? 'wait' : 'pointer',
        }}>{busy ? 'Simulating…' : 'Rank stations'}</button>
      </div>
      {err && <div style={{ color: color.statusFault }}>{err}</div>}
      {res && (
        <>
          <div style={{ color: color.textSecondary }}>
            Model check: the line took {h(res.calibration.observedLeadTimeHours)} from release to
            finish ({res.calibration.observedUnits} units); the model of it, {h(res.calibration.modelLeadTimeHours)}.
            Times are open hours.
          </div>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead><tr style={{ color: color.textDim, fontSize: 9, letterSpacing: '0.1em', textAlign: 'right' }}>
              <th style={{ textAlign: 'left', padding: 4 }}>MACHINE AT</th><th>LEAD TIME</th>
              <th>SHORTER BY</th><th>95% INTERVAL</th><th>SHARE</th></tr></thead>
            <tbody>
              {res.scenarios.map((r) => (
                <tr key={r.name} style={{ borderTop: `1px solid ${color.border}`, textAlign: 'right' }}>
                  <td style={{ textAlign: 'left', padding: 4 }}>{stations.find((s) => s._id === r.stationId)?.name ?? r.name}</td>
                  <td>{h(r.leadTimeHours)}</td>
                  <td style={{ fontWeight: 700 }}>{h(r.gainHours)}</td>
                  <td style={{ color: color.textSecondary }}>
                    {r.gainCi95Hours ? `${h(r.gainCi95Hours[0])} – ${h(r.gainCi95Hours[1])}` : '—'}</td>
                  <td>{r.gainShare != null ? `${(r.gainShare * 100).toFixed(0)}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
