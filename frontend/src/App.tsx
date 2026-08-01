import { LineDoctor } from './help/LineDoctor'
import { UndoBar } from './components/UndoBar'
import React, { useEffect, useRef, useState } from 'react'
import { Routes, Route, Navigate, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { connectWS, disconnectWS } from './api/ws'
import { useStationsStore, useProcessesStore, useCardsStore, useMachinesStore, useMapSettingsStore } from './store'
import { useAuthStore } from './store/auth.store'
import { useGlobalSettingsStore } from './store/globalSettings.store'
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
import { RouteErrorBoundary } from './components/ErrorBoundary'
import { lazyView } from './lazyView'
import { startMotionObserver } from './motion/motion.store'
import { platformApi } from './api/platform.api'

const MapView        = lazyView(() => import('./views/map/MapView'))
const LotsView       = lazyView(() => import('./views/lots/LotsView'))
const StatisticsView = lazyView(() => import('./views/statistics/StatisticsView'))
const OperatorView   = lazyView(() => import('./views/operator/OperatorView'))
const SettingsView   = lazyView(() => import('./views/settings/SettingsView'))
const PlatformView   = lazyView(() => import('./views/platform/PlatformView'))
const ClientErrorsView = lazyView(() => import('./views/platform/ClientErrorsView'))

const LoginView          = lazyView(() => import('./views/auth/LoginView'))
const SignupView         = lazyView(() => import('./views/auth/SignupView'))
const VerifyEmailView    = lazyView(() => import('./views/auth/VerifyEmailView'))
const ForgotPasswordView = lazyView(() => import('./views/auth/ForgotPasswordView'))
const ResetPasswordView  = lazyView(() => import('./views/auth/ResetPasswordView'))
const AcceptInviteView   = lazyView(() => import('./views/auth/AcceptInviteView'))
const CreateCompanyView  = lazyView(() => import('./views/company/CreateCompanyView'))
const LandingView        = lazyView(() => import('./views/landing/LandingView'))
const TermsView  = lazyView(() => import('./views/landing/TermsView'))
const ManualView         = lazyView(() => import('./views/landing/ManualView'))

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
      <RouteErrorBoundary>
        <React.Suspense fallback={<LoadingPane />}>
          <Routes>
            <Route path="/"                element={<RootGate />} />
            <Route path="/manual"          element={<ManualView />} />
              <Route path="/terms"    element={<TermsView />} />
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
      </RouteErrorBoundary>
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
  const fetchGlobalSettings = useGlobalSettingsStore((s) => s.fetch)
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
    fetchGlobalSettings()
    connectWS()
    // Watches the card store and names each change — moved, appeared, merged —
    // so the board and the map can show the transition rather than just the
    // new state. Nothing is invented: an unknown origin stays unknown.
    const stopMotion = startMotionObserver()
    return () => { stopMotion(); disconnectWS() }
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
      <LineDoctor />
      <UndoBar />
      <OrientationNavigator />
      {/* Inside the shell on purpose: the topbar stays, so a view that fails
          leaves the rest of the app reachable instead of blanking the screen. */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <RouteErrorBoundary>
          <React.Suspense fallback={<LoadingPane />}>
            <Routes>
              <Route path="/"           element={<PortraitAwareRedirect />} />
              <Route path="/map"        element={<MapView />} />
              <Route path="/lots"       element={<LotsView />} />
              <Route path="/operator"   element={<OperatorView />} />
              <Route path="/statistics" element={<StatisticsView />} />
              <Route path="/settings"   element={<RequireAdmin><SettingsView /></RequireAdmin>} />
              <Route path="/platform"   element={<RequirePlatformStaff><PlatformView /></RequirePlatformStaff>} />
              <Route path="/platform/client-errors" element={<RequirePlatformStaff><ClientErrorsView /></RequirePlatformStaff>} />
            </Routes>
          </React.Suspense>
        </RouteErrorBoundary>
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

/** True on phones and tablets held in portrait — the widths where the desktop
 *  topbar cannot fit. A media query rather than a user-agent test, so it also
 *  covers a narrow desktop window and updates live on rotation. */
const PHONE_CHROME_QUERY = '(max-width: 980px)'

function usePhoneChrome() {
  const [phone, setPhone] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(PHONE_CHROME_QUERY).matches)
  useEffect(() => {
    const mq = window.matchMedia(PHONE_CHROME_QUERY)
    const sync = (e: MediaQueryListEvent) => setPhone(e.matches)
    setPhone(mq.matches)
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])
  return phone
}

/** Phone chrome: a title bar with one menu button.
 *
 *  The desktop bar is a single non-wrapping row — logo, five nav links, the
 *  company switcher, the connection pill, help, the signed-in email and Sign
 *  out — whose min-content width is ~1160px. Nothing in it can shrink: every
 *  item is `white-space: nowrap` and flex items default to `min-width: auto`.
 *  On a 393px phone it therefore propped the *document* open to three screens,
 *  and every view — the operator dashboard included — scrolled sideways into
 *  empty space. The overflow was never in the views; it was always up here.
 *
 *  Hiding the overflow would have left the controls unreachable, so instead
 *  everything that does not fit moves into a sheet, which is what a native app
 *  does with the same problem. */
function PhoneTopbar({ connection }: { connection: 'live' | 'reconnecting' | 'off' }) {
  const { isSuperAdmin } = useRole()
  const user     = useAuthStore((s) => s.user)
  const logout   = useAuthStore((s) => s.logout)
  const location = useLocation()
  const [open, setOpen] = useState(false)

  // A menu that outlives the tap that used it reads as a stuck overlay.
  useEffect(() => { setOpen(false) }, [location.pathname])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const links: Array<[string, string]> = [
    ['/map', 'Floor plan'], ['/lots', 'Lots'], ['/operator', 'Operator'], ['/statistics', 'Statistics'],
    ...(isSuperAdmin          ? [['/settings', 'Settings'] as [string, string]] : []),
    ...(user?.platformRole    ? [['/platform', 'Platform'] as [string, string]] : []),
  ]

  const rowStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
    display: 'flex', alignItems: 'center', minHeight: 48,   // 48 ≥ the 44pt HIG target
    padding: `0 ${size.sp5}`, textDecoration: 'none', fontSize: 15,
    color: isActive ? color.textPrimary : color.textSecondary,
    background: isActive ? color.bgElevated : 'transparent',
    fontWeight: isActive ? 600 : 400,
    borderLeft: `3px solid ${isActive ? color.bluePrimary : 'transparent'}`,
  })

  return (
    <>
      <header className="tk-topbar" style={{
        height: size.topbarHeight, background: color.bgPanel,
        borderBottom: `1px solid ${color.border}`, display: 'flex', alignItems: 'center',
        padding: `0 ${size.sp4}`, gap: size.sp3, flexShrink: 0, zIndex: 100, boxShadow: shadow.sm,
      }}>
        <NavLink to="/" title="Taktline home" style={{ display: 'flex', textDecoration: 'none' }}>
          <TaktlineLogo height={20} color={color.textPrimary} />
        </NavLink>

        {/* The dot survives the collapse but the word does not: an operator
            needs to know at a glance whether the board is live, and the dot
            already carries that. The words return with the room for them. */}
        <span
          className={`status-dot ${
            connection === 'live' ? 'running' : connection === 'reconnecting' ? 'warning' : 'offline'
          }`}
          style={{ marginLeft: 'auto' }}
          title={connection === 'live' ? 'Event stream connected'
               : connection === 'reconnecting' ? 'Server unreachable — retrying automatically'
               : 'Event stream off'}
        />

        <button
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 44, height: 44, marginRight: -6,          // 44pt target, optically flush
            background: 'transparent', border: 'none', color: color.textSecondary, cursor: 'pointer',
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round">
            {open
              ? <><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>
              : <><path d="M3 6h18" /><path d="M3 12h18" /><path d="M3 18h18" /></>}
          </svg>
        </button>
      </header>

      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{
            position: 'fixed', inset: 0, zIndex: 8000, background: 'rgba(0,0,0,0.35)',
          }} />
          <div className="tk-phone-sheet" style={{
            position: 'fixed', zIndex: 8001, left: 0, right: 0,
            top: `calc(${size.topbarHeight} + env(safe-area-inset-top, 0px))`,
            maxHeight: `calc(var(--tk-vvh, 100dvh) - ${size.topbarHeight} - 24px)`,
            overflowY: 'auto', background: color.bgPanel,
            borderBottom: `1px solid ${color.border}`, boxShadow: shadow.lg,
            paddingBottom: `max(env(safe-area-inset-bottom, 0px), ${size.sp2})`,
          }}>
            {links.map(([to, label]) => (
              <NavLink key={to} to={to} style={rowStyle}>{label}</NavLink>
            ))}

            <div style={{ height: 1, background: color.border, margin: `${size.sp2} 0` }} />

            <div style={{ padding: `${size.sp2} ${size.sp5}`, display: 'flex',
                          flexDirection: 'column', gap: size.sp3 }}>
              <ImpersonationChip />
              <SandboxChip />
              <CompanySwitcher />
              {/* ThemeToggle is not here: it already floats bottom-left app-wide. */}
              <div style={{ display: 'flex', alignItems: 'center', gap: size.sp3 }}>
                <HelpMenu />
              </div>
              <span style={{ fontSize: 12, color: color.textDim, overflow: 'hidden',
                             textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user?.email}
              </span>
              <button
                onClick={() => logout()}
                style={{
                  background: 'transparent', color: color.textSecondary,
                  border: `1px solid ${color.border}`, borderRadius: size.radius,
                  padding: `10px ${size.sp3}`, fontSize: 14, cursor: 'pointer',
                  fontFamily: font.sans, width: '100%',
                }}
              >
                Sign out
              </button>
            </div>
          </div>
        </>
      )}
    </>
  )
}

function Topbar({ connection }: { connection: 'live' | 'reconnecting' | 'off' }) {
  const { isSuperAdmin } = useRole()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const phone = usePhoneChrome()

  if (phone) return <PhoneTopbar connection={connection} />

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
        <NavLink to="/map"        data-tour="nav-map" style={navStyle}>Floor plan</NavLink>
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
          <span className="tk-topbar-conn-label" style={{
            fontSize: 11, fontFamily: font.mono,
            color: connection === 'reconnecting' ? color.warnText : color.textDim,
          }}>
            {connection === 'live' ? 'LIVE' : connection === 'reconnecting' ? 'RECONNECTING' : 'OFFLINE'}
          </span>
        </div>
        <HelpMenu />
        <div style={{ width: 1, height: 20, background: color.border }} />
        <span className="tk-topbar-email" style={{ fontSize: 12, color: color.textSecondary, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
