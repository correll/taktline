import React, { useEffect } from 'react'
import { Routes, Route, Navigate, NavLink } from 'react-router-dom'
import { connectWS, disconnectWS } from './api/ws'
import { useStationsStore, useProcessesStore, useCardsStore, useMachinesStore } from './store'
import { color, font, size, shadow } from './theme/tokens'

const MapView      = React.lazy(() => import('./views/map/MapView'))
const LotsView     = React.lazy(() => import('./views/lots/LotsView'))
const SettingsView = React.lazy(() => import('./views/settings/SettingsView'))

export default function App() {
  const fetchStations  = useStationsStore((s) => s.fetchAll)
  const fetchProcesses = useProcessesStore((s) => s.fetchAll)
  const fetchCards     = useCardsStore((s) => s.fetchAll)
  const wsConnected    = useMachinesStore((s) => s.connected)

  useEffect(() => {
    fetchStations()
    fetchProcesses()
    fetchCards()
    connectWS()
    return disconnectWS
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Topbar wsConnected={wsConnected} />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <React.Suspense fallback={<LoadingPane />}>
          <Routes>
            <Route path="/"         element={<Navigate to="/map" replace />} />
            <Route path="/map"      element={<MapView />} />
            <Route path="/lots"     element={<LotsView />} />
            <Route path="/settings" element={<SettingsView />} />
          </Routes>
        </React.Suspense>
      </div>
    </div>
  )
}

function Topbar({ wsConnected }: { wsConnected: boolean }) {
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
    <header style={{
      height:       size.topbarHeight,
      background:   color.bgPanel,
      borderBottom: `1px solid ${color.border}`,
      display:      'flex',
      alignItems:   'center',
      padding:      `0 ${size.sp6}`,
      gap:          size.sp4,
      flexShrink:   0,
      zIndex:       100,
      boxShadow:    shadow.sm,
    }}>
      {/* Brand */}
      <img src="/logoV.png" alt="Veridion" style={{ height: 26 }} />
      <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
        <span style={{
          fontFamily:    font.sans,
          fontWeight:    700,
          fontSize:      14,
          letterSpacing: '0.16em',
          color:         color.textPrimary,
        }}>
          VERIDION
        </span>
        <span style={{
          fontFamily:    font.sans,
          fontSize:      8,
          letterSpacing: '0.22em',
          color:         color.textSecondary,
        }}>
          SYSTEMS
        </span>
      </div>

      {/* Nav */}
      <div style={{ width: 1, height: 20, background: color.border, margin: `0 ${size.sp2}` }} />
      <nav style={{ display: 'flex', gap: size.sp1 }}>
        <NavLink to="/map"      style={navStyle}>Map</NavLink>
        <NavLink to="/lots"     style={navStyle}>Lots</NavLink>
        <NavLink to="/settings" style={navStyle}>Settings</NavLink>
      </nav>

      {/* WebSocket status */}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: size.sp2 }}>
        <span className={`status-dot ${wsConnected ? 'running' : 'offline'}`} />
        <span style={{ fontSize: 11, color: color.textDim, fontFamily: font.mono }}>
          {wsConnected ? 'LIVE' : 'OFFLINE'}
        </span>
      </div>
    </header>
  )
}

function LoadingPane() {
  return (
    <div style={{
      flex:            1,
      display:         'flex',
      alignItems:      'center',
      justifyContent:  'center',
      color:           color.textDim,
      fontFamily:      font.mono,
      fontSize:        12,
      letterSpacing:   '0.1em',
    }}>
      LOADING…
    </div>
  )
}
