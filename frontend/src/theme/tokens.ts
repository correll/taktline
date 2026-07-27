// Design tokens per BRANDING.md — warm ink neutrals, coral for brand chrome
// only (buttons, links, nav), andon colors reserved for state.
// Token keys keep their historical names (bluePrimary = the primary action
// color) so the swap is value-only.
//
// Themed values resolve through the day/night CSS variables in global.css
// (toggled via `data-theme` on <html>). Tokens that get an alpha suffix
// concatenated onto them (`${color.bluePrimary}18`) or fed to non-CSS
// consumers must stay literal hex — they are all theme-invariant anyway.

export const color = {
  // ── Backgrounds (warm inks) ───────────────────────────────────────────────
  bgDeep:     'var(--tk-bg-deep)',       // page / map canvas
  bgPanel:    'var(--tk-bg-panel)',      // sidebar, topbar, panel backgrounds
  bgCard:     'var(--tk-bg-card)',       // cards, inputs, list items
  bgElevated: 'var(--tk-bg-elevated)',   // hover, focused, elevated surfaces
  bgHover:    'var(--tk-bg-hover)',      // interactive hover overlay
  bgInput:    'var(--tk-bg-input)',      // text inputs

  // ── Borders ───────────────────────────────────────────────────────────────
  border:       'var(--tk-border)',
  borderStrong: 'var(--tk-border-strong)',
  borderActive: '#D85A30',               // coral-400, both themes (alpha-concatenated)
  borderBright: 'var(--tk-border-bright)',

  // ── Primary action (brand coral) ──────────────────────────────────────────
  bluePrimary: '#D85A30',                  // coral-400 — fills, primary buttons (both themes)
  blueBright:  'var(--tk-brand-text)',     // links / accent text: coral-200 on dark, coral-600 on light
  blueDim:     '#993C1D',                  // coral-600
  blueGlow:    'rgba(216, 90, 48, 0.28)',
  blueSubtle:  'rgba(216, 90, 48, 0.10)',

  // ── Text (warm) ───────────────────────────────────────────────────────────
  textPrimary:   'var(--tk-text-primary)',
  textSecondary: 'var(--tk-text-secondary)',
  textDim:       'var(--tk-text-dim)',
  textDisabled:  'var(--tk-text-disabled)',

  // ── Floating chrome & backdrops ───────────────────────────────────────────
  glass:       'var(--tk-glass)',          // translucent pills/toolbars over the map
  glassBorder: 'var(--tk-glass-border)',
  glassText:   'var(--tk-glass-text)',
  backdrop:    'var(--tk-backdrop)',       // full-screen modal scrim
  warnText:    'var(--tk-warn-text)',      // amber that stays readable on light surfaces

  // ── Andon status (reserved for state — never in chrome) ──────────────────
  statusRunning: '#639922',
  statusIdle:    '#888780',
  statusWarning: '#EF9F27',   // starved
  statusFault:   '#E24B4A',   // blocked
  statusOffline: '#4A4741',

  statusRunningBg: 'rgba(99, 153, 34, 0.15)',
  statusIdleBg:    'rgba(136, 135, 128, 0.15)',
  statusWarningBg: 'rgba(239, 159, 39, 0.15)',
  statusFaultBg:   'rgba(226, 75, 74, 0.15)',

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
  sm:   'var(--tk-shadow-sm)',
  md:   'var(--tk-shadow-md)',
  lg:   'var(--tk-shadow-lg)',
  glow: '0 0 20px rgba(216, 90, 48, 0.35)',
} as const

export const transition = {
  fast:   'all 0.1s ease',
  normal: 'all 0.18s ease',
} as const
