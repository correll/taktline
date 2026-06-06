// Design tokens derived from the Veridion Systems brand:
// deep navy base, cobalt blue primary action, steel silver secondary.

export const color = {
  // ── Backgrounds ──────────────────────────────────────────────────────────
  bgDeep:     '#060E1E',   // page / map canvas
  bgPanel:    '#0B1627',   // sidebar, topbar, panel backgrounds
  bgCard:     '#101E35',   // cards, inputs, list items
  bgElevated: '#162845',   // hover, focused, elevated surfaces
  bgHover:    '#1A3054',   // interactive hover overlay

  // ── Borders ───────────────────────────────────────────────────────────────
  border:       '#1E3A5F',
  borderActive: '#2D6EDF',
  borderBright: '#3B82F6',

  // ── Blue (primary action / brand) ─────────────────────────────────────────
  bluePrimary: '#2563EB',
  blueBright:  '#3B82F6',
  blueDim:     '#1D4ED8',
  blueGlow:    'rgba(37, 99, 235, 0.28)',
  blueSubtle:  'rgba(37, 99, 235, 0.10)',

  // ── Text ──────────────────────────────────────────────────────────────────
  textPrimary:   '#EBF1F8',
  textSecondary: '#8FA3BC',
  textDim:       '#4A6080',
  textDisabled:  '#2D4A6B',

  // ── Machine status ────────────────────────────────────────────────────────
  statusRunning: '#10B981',
  statusIdle:    '#6B7280',
  statusWarning: '#F59E0B',
  statusFault:   '#EF4444',
  statusOffline: '#374151',

  statusRunningBg: 'rgba(16, 185, 129, 0.15)',
  statusIdleBg:    'rgba(107, 114, 128, 0.15)',
  statusWarningBg: 'rgba(245, 158, 11, 0.15)',
  statusFaultBg:   'rgba(239, 68, 68, 0.15)',

  // ── Lot card palette ──────────────────────────────────────────────────────
  lotBlue:   '#3B82F6',
  lotGreen:  '#10B981',
  lotAmber:  '#F59E0B',
  lotPurple: '#8B5CF6',
  lotRed:    '#EF4444',

  white: '#FFFFFF',
} as const

export const font = {
  sans: '"Inter", system-ui, -apple-system, sans-serif',
  mono: '"JetBrains Mono", "Fira Code", monospace',
} as const

export const size = {
  radiusSm:   '2px',
  radius:     '4px',
  radiusMd:   '6px',
  radiusLg:   '10px',
  radiusFull: '9999px',

  sp1: '4px',
  sp2: '8px',
  sp3: '12px',
  sp4: '16px',
  sp5: '20px',
  sp6: '24px',
  sp8: '32px',
  sp10: '40px',
  sp12: '48px',

  sidebarWidth: '320px',
  topbarHeight: '48px',
} as const

export const shadow = {
  sm:   '0 1px 3px rgba(0,0,0,0.45)',
  md:   '0 4px 12px rgba(0,0,0,0.55)',
  lg:   '0 8px 32px rgba(0,0,0,0.65)',
  glow: '0 0 20px rgba(37, 99, 235, 0.35)',
} as const

export const transition = {
  fast:   'all 0.1s ease',
  normal: 'all 0.18s ease',
} as const
