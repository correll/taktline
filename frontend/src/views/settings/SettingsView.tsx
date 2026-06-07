import React, { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { color, font, size } from '../../theme/tokens'
import StationsTab   from './StationsTab'
import ProcessesTab  from './ProcessesTab'
import TemplatesTab  from './TemplatesTab'
import MapConfigTab  from './MapConfigTab'
import GlobalTab     from './GlobalTab'

type Tab = 'stations' | 'processes' | 'templates' | 'map' | 'global'

const TABS: { id: Tab; label: string }[] = [
  { id: 'stations',  label: 'Locations' },
  { id: 'processes', label: 'Processes' },
  { id: 'templates', label: 'Templates' },
  { id: 'map',       label: 'Map'       },
  { id: 'global',    label: 'Global'    },
]

export default function SettingsView() {
  const [searchParams] = useSearchParams()
  const [tab, setTab]  = useState<Tab>((searchParams.get('tab') as Tab) ?? 'stations')
  const initialStation = searchParams.get('station')

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding:      `${size.sp3} ${size.sp6}`,
        borderBottom: `1px solid ${color.border}`,
        display:      'flex',
        alignItems:   'center',
        gap:          size.sp6,
        flexShrink:   0,
      }}>
        <span style={{ fontSize: 12, fontFamily: font.mono, color: color.textSecondary, letterSpacing: '0.08em' }}>
          SETTINGS
        </span>
        <nav style={{ display: 'flex', gap: size.sp1 }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                padding:      `${size.sp1} ${size.sp3}`,
                borderRadius: size.radius,
                background:   tab === t.id ? color.bgElevated : 'transparent',
                border:       tab === t.id ? `1px solid ${color.border}` : '1px solid transparent',
                color:        tab === t.id ? color.textPrimary : color.textSecondary,
                cursor:       'pointer',
                fontSize:     12,
                fontFamily:   font.sans,
                fontWeight:   tab === t.id ? 600 : 400,
              }}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {tab === 'stations'  && <StationsTab  />}
        {tab === 'processes' && <ProcessesTab />}
        {tab === 'templates' && <TemplatesTab initialStationId={initialStation} />}
        {tab === 'map'       && <MapConfigTab />}
        {tab === 'global'    && <GlobalTab    />}
      </div>
    </div>
  )
}
