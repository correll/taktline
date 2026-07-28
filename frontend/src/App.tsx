import React, { useEffect, useRef, useState } from 'react'
import { Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom'
import { connectWS, disconnectWS } from './api/ws'
import { useStationsStore, useProcessesStore, useCardsStore, useMachinesStore, useMapSettingsStore } from './store'
import { useAuthStore } from './store/auth.store'
import { useRole } from './auth/useRole'
import { RequireAuth, RequireAdmin } from './auth/RequireAuth'
import { CompanySwitcher } from './components/CompanySwitcher'
import { HelpMenu } from './help/HelpMenu'
import { TourManager } from './help/TourManager'
import { UserManual } from './help/UserManual'
import { GettingStarted } from './help/GettingStarted'
import { TipOfTheDay } from './help/TipOfTheDay'
import { TaktlineLogo } from './components/TaktlineLogo'
import { ThemeToggle } from './components/ThemeToggle'
import { color, font, size, shadow } from './theme/tokens'
import { ToastProvider } from './components/Toast'
import { platformApi } from './api/platform.api'

const MapView        = React.lazy(() => import('./views/map/MapView'))
const LotsView       = React.lazy(() => import('./views/lots/LotsView'))
const StatisticsView = React.lazy(() => import('./views/statistics/StatisticsView'))
const OperatorView   = React.lazy(() => import('./views/operator/OperatorView'))
const SettingsView   = React.lazy(() => import('./views/settings/SettingsView'))
const PlatformView   = React.lazy(() => import('./views/platform/PlatformView'))

const LoginView          = React.lazy(() => import('./views/auth/LoginView'))
const SignupView         = React.lazy(() => import('./views/auth/SignupView'))
const VerifyEmailView    = React.lazy(() => import('./views/auth/VerifyEmailView'))
const ForgotPasswordView = React.lazy(() => import('./views/auth/ForgotPasswordView'))
const ResetPasswordView  = React.lazy(() => import('./views/auth/ResetPasswordView'))
const AcceptInviteView   = React.lazy(() => import('./views/auth/AcceptInviteView'))
const CreateCompanyView  = React.lazy(() => import('./views/company/CreateCompanyView'))
const LandingView        = React.lazy(() => import('./views/landing/LandingView'))
const ManualView         = React.lazy(() => import('./views/landing/ManualView'))

/** Publish the *visual* viewport height as --tk-vvh.
 *
 *  iOS does not resize the layout viewport when the keyboard opens, so vh and
 *  dvh both keep reporting the full screen and a dialog sized in them hides its
 *  own submit button behind the keyboard. visualViewport is the only thing that
 *  reports the truth. On desktop it equals the window height, so the variable
 *  changes nothing there. */
function useVisualViewportHeight() {
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const sync = () => document.documentElement.style.setProperty('--tk-vvh', `${vv.height}px`)
    sync()
    vv.addEventListener('resize', sync)
    vv.addEventListener('scroll', sync)
    return () => { vv.removeEventListener('resize', sync); vv.removeEventListener('scroll', sync) }
  }, [])
}

export default function App() {
  useVisualViewportHeight()
  return (
    <ToastProvider>
      <React.Suspense fallback={<LoadingPane />}>
        <Routes>
          <Route path="/"                element={<RootGate />} />
          <Route path="/manual"          element={<ManualView />} />
          <Route path="/login"           element={<LoginView />} />
          <Route path="/signup"          element={<SignupView />} />
          <Route path="/verify-email"    element={<VerifyEmailView />} />
          <Route path="/forgot-password" element={<ForgotPasswordView />} />
          <Route path="/reset-password"  element={<ResetPasswordView />} />
          <Route path="/accept-invite"   element={<AcceptInviteView />} />
          <Route path="/create-company"  element={<RequireAuth allowNoCompany><CreateCompanyView /></RequireAuth>} />
          <Route path="/*"               element={<RequireAuth><Shell /></RequireAuth>} />
        </Routes>
      </React.Suspense>
      <ThemeToggle />
    </ToastProvider>
  )
}

function Shell() {
  const fetchStations  = useStationsStore((s) => s.fetchAll)
  const fetchFavorites = useStationsStore((s) => s.fetchFavorites)
  const fetchProcesses = useProcessesStore((s) => s.fetchAll)
  const fetchCards     = useCardsStore((s) => s.fetchAll)
  const fetchMapConfig = useMapSettingsStore((s) => s.fetch)
  const connection     = useMachinesStore((s) => s.connection)
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)

  // (Re)load all company-scoped data and (re)connect the event stream whenever
  // the active company changes.
  useEffect(() => {
    if (!activeCompanyId) return
    fetchStations()
    fetchFavorites()
    fetchProcesses()
    fetchCards()
    fetchMapConfig()
    connectWS()
    return () => disconnectWS()
  }, [activeCompanyId])

  // Server-side pulls/merges/orders auto-provision lot templates; whenever a
  // card references one this client hasn't seen, refetch — so lots never show
  // as "Unknown" and merge-station classification stays correct.
  const cards = useCardsStore((s) => s.cards)
  const ensureTemplates = useProcessesStore((s) => s.ensureTemplates)
  useEffect(() => {
    ensureTemplates(Object.values(cards).map((c) => c.lotTemplateId))
  }, [cards, ensureTemplates])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Topbar connection={connection} />
      <OutageBanner />
      <OrientationNavigator />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <React.Suspense fallback={<LoadingPane />}>
          <Routes>
            <Route path="/"           element={<PortraitAwareRedirect />} />
            <Route path="/map"        element={<MapView />} />
            <Route path="/lots"       element={<LotsView />} />
            <Route path="/operator"   element={<OperatorView />} />
            <Route path="/statistics" element={<StatisticsView />} />
            <Route path="/settings"   element={<RequireAdmin><SettingsView /></RequireAdmin>} />
            <Route path="/platform"   element={<RequirePlatformStaff><PlatformView /></RequirePlatformStaff>} />
          </Routes>
        </React.Suspense>
      </div>

      {/* Help & onboarding overlays */}
      <GettingStarted />
      <TipOfTheDay />
      <UserManual />
      <TourManager />
    </div>
  )
}

/** "/" is the public landing page for visitors; signed-in users go straight
 *  into the app (portrait devices land on the operator view). */
function RootGate() {
  const status = useAuthStore((s) => s.status)
  const isSandbox = useAuthStore((s) => s.user?.isSandbox === true)
  if (status === 'loading') return <LoadingPane />
  // Sandbox visitors are still prospects: "/" is the marketing site for them,
  // and their line is one click away. Real accounts go straight to work.
  if (status === 'authed' && !isSandbox) {
    return <Navigate to={isPortrait() ? '/operator' : '/map'} replace />
  }
  return <LandingView />
}

/** Customer-service dashboard gate: UX only, the server 404s non-staff. */
function RequirePlatformStaff({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (!user?.platformRole) return <Navigate to="/map" replace />
  return <>{children}</>
}

function Topbar({ connection }: { connection: 'live' | 'reconnecting' | 'off' }) {
  const { isSuperAdmin } = useRole()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)

  const navStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
    padding:        `${size.sp1} ${size.sp3}`,
    borderRadius:   size.radius,
    color:          isActive ? color.textPrimary : color.textSecondary,
    background:     isActive ? color.bgElevated : 'transparent',
    fontWeight:     isActive ? 600 : 400,
    fontSize:       13,
    textDecoration: 'none',
    letterSpacing:  '0.04em',
    transition:     'all 0.15s ease',
    border:         isActive ? `1px solid ${color.border}` : '1px solid transparent',
  })

  return (
    <header className="tk-topbar" style={{
      height: size.topbarHeight, background: color.bgPanel,
      borderBottom: `1px solid ${color.border}`, display: 'flex', alignItems: 'center',
      padding: `0 ${size.sp6}`, gap: size.sp4, flexShrink: 0, zIndex: 100, boxShadow: shadow.sm,
    }}>
      <NavLink to="/" title="Taktline home" style={{ display: 'flex', textDecoration: 'none' }}>
        <TaktlineLogo height={22} color={color.textPrimary} />
      </NavLink>

      <div style={{ width: 1, height: 20, background: color.border, margin: `0 ${size.sp2}` }} />
      <nav style={{ display: 'flex', gap: size.sp1 }}>
        <NavLink to="/map"        data-tour="nav-map" style={navStyle}>Map</NavLink>
        <NavLink to="/lots"       data-tour="nav-lots" style={navStyle}>Lots</NavLink>
        <NavLink to="/operator"   data-tour="nav-operator" style={navStyle}>Operator</NavLink>
        <NavLink to="/statistics" style={navStyle}>Statistics</NavLink>
        {isSuperAdmin && <NavLink to="/settings" data-tour="nav-settings" style={navStyle}>Settings</NavLink>}
        {user?.platformRole && <NavLink to="/platform" style={navStyle}>Platform</NavLink>}
      </nav>

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: size.sp4 }}>
        <ImpersonationChip />
        <SandboxChip />
        <CompanySwitcher />
        <div
          style={{ display: 'flex', alignItems: 'center', gap: size.sp2 }}
          title={connection === 'live' ? 'Event stream connected'
               : connection === 'reconnecting' ? 'Server unreachable — retrying automatically'
               : 'Event stream off'}
        >
          <span className={`status-dot ${
            connection === 'live' ? 'running' : connection === 'reconnecting' ? 'warning' : 'offline'
          }`} />
          <span style={{
            fontSize: 11, fontFamily: font.mono,
            color: connection === 'reconnecting' ? color.warnText : color.textDim,
          }}>
            {connection === 'live' ? 'LIVE' : connection === 'reconnecting' ? 'RECONNECTING' : 'OFFLINE'}
          </span>
        </div>
        <HelpMenu />
        <div style={{ width: 1, height: 20, background: color.border }} />
        <span style={{ fontSize: 12, color: color.textSecondary, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {user?.email}
        </span>
        <button
          onClick={() => logout()}
          style={{
            background: 'transparent', color: color.textSecondary, border: `1px solid ${color.border}`,
            borderRadius: size.radius, padding: `${size.sp1} ${size.sp3}`, fontSize: 12, cursor: 'pointer',
            fontFamily: font.sans,
          }}
        >
          Sign out
        </button>
      </div>
    </header>
  )
}

/** Amber strip while the server is unreachable: says the data on screen is a
 *  local snapshot and how old it is. Andon amber = attention, with icon + words
 *  (never color alone). Disappears on its own once the stream reconnects. */
function OutageBanner() {
  const connection = useMachinesStore((s) => s.connection)
  const staleSince = useMachinesStore((s) => s.staleSince)
  if (connection !== 'reconnecting' && !staleSince) return null

  const when = staleSince
    ? new Date(staleSince).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: size.sp2,
      padding: '5px 12px', background: 'rgba(239, 159, 39, 0.12)',
      borderBottom: '1px solid #EF9F2755', fontSize: 12.5, color: color.warnText,
      flexShrink: 0,
    }}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
           strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
        <path d="M12 9v4" /><path d="M12 17h.01" />
      </svg>
      {when
        ? `Server unreachable — showing data saved at ${when}. Reconnecting automatically; changes can't be saved right now.`
        : 'Connection to the server lost — reconnecting automatically.'}
    </div>
  )
}

/** Sandbox visitors see a standing invitation to convert — their line only
 *  lives as long as the throwaway account does. */
function SandboxChip() {
  const user = useAuthStore((s) => s.user)
  if (!user?.isSandbox) return null
  return (
    <NavLink to="/signup" style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: color.blueSubtle, border: `1px solid ${color.borderActive}66`,
      borderRadius: size.radiusFull, padding: '3px 12px',
      fontSize: 11.5, color: color.blueBright, whiteSpace: 'nowrap', textDecoration: 'none',
    }}>
      Sandbox · create a free account to keep your line
    </NavLink>
  )
}

/** Always-visible marker while customer service is inside a customer's company:
 *  names the company, shows time left on the grant, and ends it in one click. */
function ImpersonationChip() {
  const navigate = useNavigate()
  const companies = useAuthStore((s) => s.companies)
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)
  const setActiveCompany = useAuthStore((s) => s.setActiveCompany)
  const refresh = useAuthStore((s) => s.refresh)
  const [busy, setBusy] = useState(false)

  const active = companies.find((c) => c.id === activeCompanyId)
  if (!active?.impersonated) return null

  const minutesLeft = active.impersonationExpiresAt
    ? Math.max(0, Math.round((new Date(active.impersonationExpiresAt).getTime() - Date.now()) / 60_000))
    : null

  const end = async () => {
    setBusy(true)
    try {
      await platformApi.endImpersonation(active.id)
      await refresh()
      const own = useAuthStore.getState().companies.find((c) => !c.impersonated)
      if (own) setActiveCompany(own.id)
      navigate('/platform')
    } finally { setBusy(false) }
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: size.sp2,
      background: color.blueSubtle, border: `1px solid ${color.borderActive}66`,
      borderRadius: size.radiusFull, padding: `2px 4px 2px 10px`,
      fontSize: 11.5, color: color.blueBright, whiteSpace: 'nowrap',
    }}>
      <span>Supporting {active.name}{minutesLeft != null ? ` · ${minutesLeft} min left` : ''}</span>
      <button
        onClick={end} disabled={busy}
        style={{ background: color.bluePrimary, color: '#fff', border: 'none',
                 borderRadius: size.radiusFull, padding: '2px 10px', fontSize: 11,
                 fontWeight: 600, cursor: 'pointer' }}>
        End
      </button>
    </div>
  )
}

function isPortrait() {
  return window.innerHeight > window.innerWidth
}

function PortraitAwareRedirect() {
  return <Navigate to={isPortrait() ? '/operator' : '/map'} replace />
}

function OrientationNavigator() {
  const navigate    = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate

  useEffect(() => {
    const check = () => {
      const path = window.location.pathname
      if (isPortrait() && path === '/map')       navigateRef.current('/operator', { replace: true })
      if (!isPortrait() && path === '/operator') navigateRef.current('/map',      { replace: true })
    }
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  return null
}

function LoadingPane() {
  return (
    <div style={{
      flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: color.textDim, fontFamily: font.mono, fontSize: 12, letterSpacing: '0.1em',
      background: color.bgDeep, height: '100%',
    }}>
      LOADING…
    </div>
  )
}
