import React, { useEffect } from 'react'
import { useAuthStore } from '../store/auth.store'
import { color, font } from '../theme/tokens'

/** Resolves the current session on mount and reacts to lost sessions (401). */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const status = useAuthStore((s) => s.status)
  const bootstrap = useAuthStore((s) => s.bootstrap)
  const markAnon = useAuthStore((s) => s.markAnon)

  useEffect(() => { bootstrap() }, [bootstrap])

  useEffect(() => {
    const onUnauthorized = () => {
      if (useAuthStore.getState().status === 'authed') markAnon()
    }
    window.addEventListener('taktline:unauthorized', onUnauthorized)
    return () => window.removeEventListener('taktline:unauthorized', onUnauthorized)
  }, [markAnon])

  if (status === 'loading') {
    return (
      <div style={{
        height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: color.bgDeep, color: color.textDim, fontFamily: font.mono,
        fontSize: 12, letterSpacing: '0.1em',
      }}>
        TAKTLINE · AUTHENTICATING…
      </div>
    )
  }
  return <>{children}</>
}
