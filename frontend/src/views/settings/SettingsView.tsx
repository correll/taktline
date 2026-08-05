import React, { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { color, font, size } from '../../theme/tokens'
import StationsTab   from './StationsTab'
import ProcessesTab  from './ProcessesTab'
import TemplatesTab  from './TemplatesTab'
import MapConfigTab  from './MapConfigTab'
import GlobalTab       from './GlobalTab'
import { useAuthStore } from '../../store/auth.store'
import MembersTab      from './MembersTab'
import IntegrationsTab from './IntegrationsTab'
import BillingTab from './BillingTab'

type Tab = 'stations' | 'processes' | 'templates' | 'map' | 'members' | 'integrations' | 'global' | 'billing'

const TABS: { id: Tab; label: string }[] = [
  { id: 'stations',     label: 'Stations'    },
  { id: 'processes',    label: 'Processes'    },
  { id: 'templates',    label: 'Templates'    },
  { id: 'map',          label: 'Floor plan'   },
  { id: 'members',      label: 'Members'      },
  { id: 'integrations', label: 'Integrations' },
  { id: 'global',       label: 'Global'       },
  { id: 'billing',      label: 'Billing'      },
]

// Capabilities a sandbox account doesn't have (server-enforced too). The tabs
// stay visible but greyed — clicking one leads to registration.
const SANDBOX_LOCKED: Tab[] = ['map', 'members', 'integrations', 'billing']

/** Billing is a page of prose and cards rather than a table, so it needs the
 *  scroll container the table tabs provide for themselves. */
function BillingScroll() {
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: size.sp6 }}>
      <BillingTab />
    </div>
  )
}

export default function SettingsView() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [tab, setTab]  = useState<Tab>((searchParams.get('tab') as Tab) ?? 'stations')
  const initialStation = searchParams.get('station')
  const isSandbox = useAuthStore((s) => s.user?.isSandbox === true)
  const isLocked = (t: Tab) => isSandbox && SANDBOX_LOCKED.includes(t)

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
              data-tour={`settings-tab-${t.id}`}
              onClick={() => (isLocked(t.id) ? navigate('/signup') : setTab(t.id))}
              title={isLocked(t.id) ? 'Available with a free account — click to register' : undefined}
              style={{
                padding:      `${size.sp1} ${size.sp3}`,
                borderRadius: size.radius,
                background:   tab === t.id ? color.bgElevated : 'transparent',
                border:       tab === t.id ? `1px solid ${color.border}` : '1px solid transparent',
                color:        isLocked(t.id) ? color.textDisabled
                            : tab === t.id ? color.textPrimary : color.textSecondary,
                opacity:      isLocked(t.id) ? 0.6 : 1,
                cursor:       'pointer',
                fontSize:     12,
                fontFamily:   font.sans,
                fontWeight:   tab === t.id ? 600 : 400,
              }}
            >
              {t.label}{isLocked(t.id) ? ' 🔒' : ''}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {/* display:flex is what lets a tab's own overflow work: as a plain
          block, the tab's height was its content height, the wrapper clipped
          it, and inner overflowY:auto never engaged — the Map tab's panel
          could not scroll at all on a small window. */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
        {tab === 'stations'  && <StationsTab  />}
        {tab === 'processes' && <ProcessesTab />}
        {tab === 'templates' && <TemplatesTab initialStationId={initialStation} />}
        {tab === 'map'          && <MapConfigTab   />}
        {tab === 'members'      && <MembersTab     />}
        {tab === 'integrations' && <IntegrationsTab />}
        {tab === 'global'       && <GlobalTab      />}
        {tab === 'billing'      && <BillingScroll  />}
      </div>
    </div>
  )
}
