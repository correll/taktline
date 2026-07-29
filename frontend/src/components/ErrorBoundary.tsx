import React from 'react'
import { useLocation } from 'react-router-dom'
import { color, font, size } from '../theme/tokens'
import { isChunkLoadError } from '../lazyView'
import { client } from '../api/client'

/** The app had no error boundary, which in React 18 means any error thrown
 *  while rendering unmounts the whole tree and leaves an empty <div id="root">
 *  — a blank page in the body's background colour, with nothing in the UI to
 *  say what happened or how to recover.
 *
 *  A boundary turns that into a message and a button. It is deliberately
 *  placed *inside* the shell on the authenticated routes, so the topbar
 *  survives and the other views stay reachable: one broken view should not
 *  cost someone the whole board mid-shift.
 */

type Props = {
  children: React.ReactNode
  /** Changing this clears the error — bound to the route, so navigating away
   *  recovers instead of leaving the boundary latched on the failed view. */
  resetKey?: string
}
type State = {
  error: Error | null
  /** Whether the report actually reached Taktline. Tracked rather than
   *  assumed: telling someone their crash was sent when the POST failed —
   *  offline, rate-limited, server down — is a lie that costs us the report
   *  AND their trust that anything is being done about it. */
  reported: 'pending' | 'sent' | 'failed'
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null, reported: 'pending' }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error, reported: 'pending' }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[taktline] render error:', error, info.componentStack)
    // The console dies with the tab; the report must not. Two sinks, both
    // best-effort: localStorage (readable in a support session even offline)
    // and the server (readable by platform staff after the user reloaded and
    // moved on — which is exactly when "what actually happened?" gets asked).
    const report = {
      message: String(error?.message ?? error).slice(0, 1000),
      stack: String(error?.stack ?? '').slice(0, 6000),
      componentStack: String(info.componentStack ?? '').slice(0, 6000),
      url: window.location.href.slice(0, 500),
    }
    try {
      localStorage.setItem('taktline.lastError',
        JSON.stringify({ ...report, at: new Date().toISOString() }))
    } catch { /* storage full or blocked — the POST below still goes out */ }
    // A crashed view must never crash again in the reporter.
    try {
      client.post('/client-errors/', report)
        .then(() => this.setState({ reported: 'sent' }))
        .catch(() => this.setState({ reported: 'failed' }))
    } catch { this.setState({ reported: 'failed' }) }
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null, reported: 'pending' })
    }
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    // A chunk error that reaches here means the one automatic reload was
    // already spent, so ask rather than loop.
    const stale = isChunkLoadError(error)

    return (
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: size.sp6, background: color.bgDeep,
      }}>
        <div style={{
          maxWidth: 420, textAlign: 'center', display: 'flex',
          flexDirection: 'column', gap: size.sp4, alignItems: 'center',
        }}>
          <div style={{
            fontFamily: font.mono, fontSize: 11, letterSpacing: '0.12em',
            color: color.textDim,
          }}>
            {stale ? 'NEW VERSION AVAILABLE' : 'SOMETHING WENT WRONG'}
          </div>
          <div style={{ fontSize: 15, color: color.textPrimary, lineHeight: 1.6 }}>
            {stale
              ? 'Taktline was updated while this tab was open, so this page could not load. Reloading picks up the new version.'
              : 'This view ran into an error and stopped. Your data is safe — nothing was saved or changed by this.'}
          </div>
          {/* Only claimed once the POST has actually resolved. A stale build is
              excluded: that is the tab being old, not a fault worth reporting. */}
          {!stale && this.state.reported !== 'pending' && (
            <div style={{ fontSize: 12.5, color: color.textDim, lineHeight: 1.55 }}>
              {this.state.reported === 'sent'
                ? 'This error has been recorded and sent to Taktline to improve the software. You don’t need to report it.'
                : 'We couldn’t reach Taktline to report this automatically — the details are saved in this browser under “Details” below.'}
            </div>
          )}
          <button
            onClick={() => window.location.reload()}
            style={{
              background: color.bluePrimary, color: '#fff', border: 'none',
              borderRadius: size.radius, padding: `10px ${size.sp5}`,
              fontSize: 14, fontFamily: font.sans, cursor: 'pointer',
            }}
          >
            Reload
          </button>
          {(!stale || this.state.reported === 'failed') && (
            <details style={{ fontSize: 12, color: color.textDim, textAlign: 'left', width: '100%' }}>
              <summary style={{ cursor: 'pointer' }}>Details</summary>
              <pre style={{
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: size.sp2,
                fontFamily: font.mono, fontSize: 11, color: color.textSecondary,
              }}>{String(error?.message ?? error)}</pre>
            </details>
          )}
        </div>
      </div>
    )
  }
}

/** ErrorBoundary that resets itself when the route changes. */
export function RouteErrorBoundary({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  return <ErrorBoundary resetKey={location.pathname}>{children}</ErrorBoundary>
}

export default ErrorBoundary
